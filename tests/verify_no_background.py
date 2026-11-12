# -*- coding: utf-8 -*-
"""冻结 exe 的「背景板」回归验证（沙箱 APPDATA，不碰用户配置）。

用户反馈过两件事：
  1) 电子表 / 科技等样式自带黑底 —— 已把 20 套预设的背景板全部关掉；
  2) **刚开始没有背景，过了一秒背景冒出来** —— 根因是 `set_preset()` 里写
     `style.background.enabled`，走 150ms 去抖 + 信号链，第一帧干净、随后才铺底。

本脚本把「历史遗留 enabled=true」塞进沙箱配置，启动冻结 exe 后检查：
  A. settings.json 里的 background.enabled 被启动迁移清成 false；
  B. 日志里有迁移记录；
  C. 时钟窗口四角像素在 t=1.0s 与 t=3.0s 两个时刻不出现「突然变成实心色块」。
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
EXE = ROOT / "dist" / "DesktopTime.exe"

SANDBOX = Path(os.environ.get("TEMP", ".")) / "dt_nobg"
APPDATA = SANDBOX / "appdata"
CFG = APPDATA / "DesktopTime" / "settings.json"
LOG = APPDATA / "DesktopTime" / "logs" / "desktoptime.log"


def seed() -> None:
    """用用户当下配置打底（最接近实机），但强制打开背景板模拟旧版本残留。"""
    if APPDATA.exists():
        shutil.rmtree(APPDATA, ignore_errors=True)
    CFG.parent.mkdir(parents=True, exist_ok=True)
    real = Path(os.environ.get("APPDATA", ".")) / "DesktopTime" / "settings.json"
    if real.is_file():
        cfg = json.loads(real.read_text(encoding="utf-8"))
    else:
        from core import settings as st
        cfg = st.defaults()
    cfg["style"]["packRef"] = ""
    cfg["style"]["background"] = {"enabled": True, "color": "#FFFFFF", "padding": 12}
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def corner_pixels(rect: tuple[int, int, int, int]) -> list[tuple[int, int, int]]:
    """抓屏幕上该矩形四角内侧 3px 的像素（窗口是逐像素透明，背景板一出现就会变实心）。

    ★ 必须 `include_layered_windows=True`：时钟窗是 WS_EX_LAYERED + 逐像素 alpha，
      Pillow 默认不抓分层窗口，量出来整片 (0,0,0)，等于什么都没测。
    """
    from PIL import ImageGrab
    x, y, w, h = rect
    shot = ImageGrab.grab(bbox=(x, y, x + w, y + h),
                          include_layered_windows=True,
                          all_screens=True).convert("RGB")
    pts = [(3, 3), (w - 4, 3), (3, h - 4), (w - 4, h - 4)]
    return [shot.getpixel(p) for p in pts]


def find_clock_rect() -> tuple[int, int, int, int] | None:
    """枚举标题为 DesktopTime 的可见 Qt 窗口（Qt Tool 窗，设置窗是 "DesktopTime · 设置"）。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[tuple[int, int, int, int]] = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    def cb(hwnd, _lp):
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), cls, 128)
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, 256)
        if cls.value.startswith("Qt") and title.value == "DesktopTime" and user32.IsWindowVisible(hwnd):
            r = RECT()
            user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if 40 < w < 1200 and 20 < h < 500:
                found.append((r.left, r.top, w, h))
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found[0] if found else None


def main() -> int:
    if not EXE.is_file():
        print("EXE_MISSING", EXE)
        return 1
    # ★ 本进程也要 PER_MONITOR_AWARE_V2，否则 GetWindowRect 拿到 DPI 虚拟化后的逻辑坐标，
    #   拿去裁剪物理像素截图会整体错位。
    from core.monitors import set_dpi_awareness
    print("DPI", set_dpi_awareness())
    seed()
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(key, None)
    env["APPDATA"] = str(APPDATA)

    proc = subprocess.Popen([str(EXE)], cwd=str(SANDBOX), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    try:
        # onefile 引导器解包要 1~3s，轮询等窗口出现，出现后立刻抓一帧
        rect = None
        for _ in range(60):
            rect = find_clock_rect()
            if rect:
                break
            time.sleep(0.25)
        early = corner_pixels(rect) if rect else []
        time.sleep(2.5)                     # 越过 150ms 去抖，看会不会「冒出来」
        late = corner_pixels(rect) if rect else []
        print("时钟矩形", rect)
        print("t=1.0s 四角", early)
        print("t=3.0s 四角", late)
        if early and late and early != late:
            # 只有「整块变实心」才算失败；文字笔画扫过角落造成的微差属于正常
            big = any(sum(abs(a - b) for a, b in zip(p, q)) > 90 for p, q in zip(early, late))
            print("四角突变", big)
            ok = ok and not big
        else:
            print("四角稳定（无背景板浮现）")

        time.sleep(1.5)                     # 等去抖落盘
        after = json.loads(CFG.read_text(encoding="utf-8"))
        bg = after["style"]["background"]["enabled"]
        print("启动后 background.enabled =", bg)
        text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.is_file() else ""
        hit = [ln for ln in text.splitlines() if "背景" in ln]
        print("迁移日志", hit or "(未命中)")
        ok = ok and bg is False and bool(hit)
        print("RESULT", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        try:
            subprocess.run([str(EXE), "--quit"], cwd=str(SANDBOX), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(2)
        left = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DesktopTime.exe", "/NH"],
                              capture_output=True, text=True, encoding="gbk",
                              errors="replace", timeout=20).stdout
        if "DesktopTime.exe" in left:
            subprocess.run(["taskkill", "/IM", "DesktopTime.exe", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            print("CLEANUP 强制结束残留进程")


if __name__ == "__main__":
    sys.exit(main())
