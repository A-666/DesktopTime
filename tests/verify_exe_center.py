# -*- coding: utf-8 -*-
"""抓「打包后 exe」的时间窗口，量日期 / 星期是否压在时间正中。

渲染器单测只能证明代码里 x 算对了，这个脚本证明冻结环境里**看到的结果**也对：
字色之所以写死成白色，是因为时间窗口是透明窗，PrintWindow 抓下来会带上桌面底色，
用亮度阈值找墨迹才稳。

Win32 抓屏踩坑同 capture_exe.py：负高度 top-down DIB，首行即顶行，禁止再翻转。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_exe import find_window, grab    # noqa: E402  复用 PrintWindow 抓屏

EXE = ROOT / "dist" / "DesktopTime.exe"
OUT = Path(os.environ.get("TEMP", ".")) / "dt_ui" / "exe_center.png"
TOL = 3.0          # 允许的字形亚像素偏差（「1」左侧留白天然不对称）


def seed(sandbox: Path) -> None:
    """沙箱配置：白字、带日期与星期、居中预设。"""
    cfg_dir = sandbox / "DesktopTime"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    real = Path(os.environ.get("APPDATA", ".")) / "DesktopTime" / "settings.json"
    if real.is_file():
        raw = json.loads(real.read_text(encoding="utf-8"))
    else:
        from core import settings as st
        raw = st.defaults()
    raw.setdefault("style", {}).update({
        "color": "#FFFFFF", "size": 58, "textStyles": [],
    })
    raw["style"]["background"]["enabled"] = False
    raw.setdefault("time", {}).update({
        "format": "HH:mm:ss", "showSeconds": True,
        "showDate": True, "showWeekday": True,
    })
    raw.setdefault("position", {}).update({"mode": "preset", "preset": "center"})
    (cfg_dir / "settings.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def measure(img) -> tuple[float, float, int]:
    """按行找墨迹（亮像素）的横向中位线，返回 (上半中线, 下半中线, 行数)。"""
    w, h = img.size
    px = img.load()
    spans = []
    for y in range(h):
        xs = [x for x in range(w)
              if px[x, y][3] > 40
              and (px[x, y][0] + px[x, y][1] + px[x, y][2]) / 3 > 130]
        spans.append((min(xs), max(xs)) if xs else None)
    half = h // 2
    top = [s for s in spans[:half] if s]
    bot = [s for s in spans[half:] if s]
    if not top or not bot:
        return -1.0, -1.0, len(top) + len(bot)
    ct = (min(a for a, _ in top) + max(b for _, b in top)) / 2
    cb = (min(a for a, _ in bot) + max(b for _, b in bot)) / 2
    return ct, cb, len(top) + len(bot)


def main() -> int:
    if not EXE.is_file():
        print("EXE_MISSING")
        return 1
    sandbox = Path(os.environ.get("TEMP", ".")) / "dt_exe_center" / "appdata"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    seed(sandbox)
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(key, None)
    env["APPDATA"] = str(sandbox)
    workdir = sandbox.parent
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(EXE)], cwd=str(workdir), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        hwnd = find_window("DesktopTime")
        print("时钟窗口 HWND", hwnd)
        if not hwnd:
            print("RESULT FAIL (未找到时间窗口)")
            return 1
        img = grab(hwnd)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(OUT)
        ct, cb, rows = measure(img)
        print(f"尺寸 {img.size}  墨迹行 {rows}")
        if ct < 0:
            print("RESULT FAIL (上半或下半没有墨迹，日期可能没显示)")
            return 1
        dev = cb - ct
        print(f"主行中线 {ct:.1f}  副行中线 {cb:.1f}  偏差 {dev:+.1f}px")
        ok = abs(dev) <= TOL
        print("RESULT", "PASS" if ok else f"FAIL (超过 {TOL}px)")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
