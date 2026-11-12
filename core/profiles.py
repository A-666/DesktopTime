# -*- coding: utf-8 -*-
"""本机配置方案 CRUD、一键整组切换、撤销回滚点。

范围：单机本地多配置，不做跨设备迁移 / 导入导出 / 云端同步（D-005）。
快照结构：snapshots/last_switch.json = {snapshot, from, to, at, valid}
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from . import store
from .settings import APP_VERSION, SCHEMA, coerce, now_iso

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name: str) -> str:
    cleaned = _BAD.sub("_", (name or "").strip()).strip(". ")
    return (cleaned or "未命名方案")[:60]


class ProfileManager:
    def __init__(self) -> None:
        store.ensure_dirs()

    def _path(self, name: str) -> Path:
        return store.PROFILES_DIR / f"{safe_name(name)}.dtconfig"

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(store.PROFILES_DIR.glob("*.dtconfig")):
            try:
                raw = store.read_json(path)
                rows.append({
                    "name": str(raw.get("name") or path.stem),
                    "savedAt": str(raw.get("savedAt") or ""),
                    "note": str(raw.get("note") or ""),
                    "preset": str((raw.get("style") or {}).get("preset") or ""),
                    "path": str(path),
                })
            except (OSError, ValueError):
                store.log(f"跳过损坏的方案文件 {path.name}", "WARN")
        return rows

    def save(self, name: str, settings_data: dict, note: str = "") -> Path:
        """保存当前设置为完整快照（不是差异项），保证整组切换不残留半套设置。"""
        clean, _ = coerce(settings_data)
        clean["name"] = safe_name(name)
        clean["savedAt"] = now_iso()
        clean["appVersion"] = APP_VERSION
        clean["schema"] = SCHEMA
        clean["note"] = note
        path = self._path(name)
        store.atomic_write_json(path, clean)
        store.log(f"保存方案 {clean['name']} -> {path.name}")
        return path

    def load(self, name: str) -> tuple[dict, list[str]]:
        raw = store.read_json(self._path(name))
        return coerce(raw)

    def duplicate(self, name: str) -> str:
        data, _ = self.load(name)
        base = safe_name(name)
        i = 2
        while self.exists(f"{base} 副本{i}"):
            i += 1
        new_name = f"{base} 副本{i}"
        self.save(new_name, data)
        return new_name

    def rename(self, old: str, new: str) -> str:
        data, _ = self.load(old)
        target = safe_name(new)
        if target != safe_name(old):
            self.save(target, data, str(data.get("note") or ""))
            self.delete(old)
            self.invalidate(f"方案 {old} 已重命名")
        return target

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.is_file():
            return False
        path.unlink()
        store.log(f"删除方案 {name}")
        self.invalidate(f"方案 {name} 已删除")
        return True

    # ---- 一键切换与撤销 ----

    def switch(self, name: str, current_data: dict, current_label: str = "当前配置") -> tuple[dict, list[str]]:
        """切换前原子留快照，再整组替换。不弹确认框。"""
        snap = {
            "snapshot": copy.deepcopy(current_data),
            "from": current_label,
            "to": safe_name(name),
            "at": now_iso(),
            "valid": True,
        }
        store.atomic_write_json(store.SNAPSHOT_FILE, snap)
        data, warnings = self.load(name)
        store.log(f"切换方案 {current_label} -> {snap['to']}")
        return data, warnings

    def undo_info(self) -> dict | None:
        try:
            return store.read_json(store.SNAPSHOT_FILE)
        except (OSError, ValueError):
            return None

    def can_undo(self) -> bool:
        info = self.undo_info()
        return bool(info and info.get("valid") and isinstance(info.get("snapshot"), dict))

    def undo(self) -> tuple[dict, list[str]] | None:
        info = self.undo_info()
        if not info or not info.get("valid"):
            return None
        data, warnings = coerce(info.get("snapshot"))
        self.invalidate("已执行撤销")
        store.log(f"撤销上一次切换 -> {info.get('from')}")
        return data, warnings

    def invalidate(self, reason: str = "") -> bool:
        """任一设置改动 / 撤销 / 重启 / 删除目标方案后，回滚点失效。"""
        info = self.undo_info()
        if not info or not info.get("valid"):
            return False
        info["valid"] = False
        info["invalidatedBy"] = reason
        store.atomic_write_json(store.SNAPSHOT_FILE, info)
        return True
