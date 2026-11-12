# -*- coding: utf-8 -*-
"""运行时目录管理与原子化 JSON IO。

所有写入走「临时文件 + os.replace」，避免断电 / 强杀写坏配置。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

APPDATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
APP_DIR = APPDATA / "DesktopTime"
SETTINGS_FILE = APP_DIR / "settings.json"
PROFILES_DIR = APP_DIR / "profiles"
STYLES_DIR = APP_DIR / "styles"
SNAPSHOTS_DIR = APP_DIR / "snapshots"
LOGS_DIR = APP_DIR / "logs"
SNAPSHOT_FILE = SNAPSHOTS_DIR / "last_switch.json"
LOG_FILE = LOGS_DIR / "desktoptime.log"
MAX_PACK_BYTES = 256 * 1024

_DIRS = (APP_DIR, PROFILES_DIR, STYLES_DIR, SNAPSHOTS_DIR, LOGS_DIR)


def ensure_dirs() -> None:
    for d in _DIRS:
        d.mkdir(parents=True, exist_ok=True)
    rotate_logs()


def rotate_logs(days: int = 7) -> None:
    try:
        if not LOG_FILE.exists():
            return
        if datetime.fromtimestamp(LOG_FILE.stat().st_mtime) < datetime.now() - timedelta(days=days):
            stamp = datetime.now().strftime("%Y%m%d")
            LOG_FILE.rename(LOG_FILE.with_name(f"desktoptime.{stamp}.log"))
    except OSError:
        pass


def log(msg: str, level: str = "INFO") -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        line = f"{datetime.now().isoformat(timespec='seconds')} [{level}] {msg}\n"
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, max_bytes: int | None = None) -> Any:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValueError(f"文件超过 {max_bytes} 字节上限：{path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def backup_corrupt(path: Path) -> str:
    """把坏文件改名留证，返回备份文件名。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    try:
        shutil.copy2(path, dst)
        path.unlink(missing_ok=True)
    except OSError:
        return ""
    return dst.name


def load_raw_settings() -> tuple[Any, str | None]:
    """返回 (数据, 错误)。文件不存在 -> (None, None)；损坏 -> (None, 错误信息)。"""
    if not SETTINGS_FILE.exists():
        return None, None
    try:
        return read_json(SETTINGS_FILE), None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        name = backup_corrupt(SETTINGS_FILE)
        return None, f"settings.json 读取失败（{exc}），已备份为 {name}，回落默认配置"


def save_settings(data: dict[str, Any]) -> None:
    atomic_write_json(SETTINGS_FILE, data)


def open_config_dir() -> None:
    ensure_dirs()
    os.startfile(str(APP_DIR))  # noqa: S606 - Windows-only deliberate
