# -*- coding: utf-8 -*-
"""像素级验证：混合 DPI 双屏下「居中 / 九宫格 / 边距」真实落点。

对照 Win32 GetWindowRect（物理像素）与时间窗口渲染尺寸，
直接比较窗口物理中心和目标屏工作区物理中心，误差必须 ≤ 2px。

运行：
  set PYTHONPATH=<site-packages>;<项目根>
  python tests/verify_position.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from core.monitors import enum_monitors, set_dpi_awareness  # noqa: E402

set_dpi_awareness()  # 必须早于 QApplication

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from core import stylepack  # noqa: E402
from core.renderer import Renderer  # noqa: E402
from core.settings import defaults  # noqa: E402
from ui.screens import build_screen_map  # noqa: E402

app = QApplication([])
mons = enum_monitors()
smap = build_screen_map(mons)

cfg = defaults()
pack = stylepack.validate_pack(stylepack.get_builtin("digital"))[0]
img = Renderer().render(datetime(2026, 11, 11, 14, 35, 8), cfg, pack, 0)
W, H = img.width(), img.height()

print(f"时间窗口渲染尺寸 = {W}×{H}（逻辑像素，含文字 + 装饰留白）")
print(f"ctypes 屏数={len(mons)}  Qt 屏数={len(QGuiApplication.screens())}  fallback={smap.fallback}")
for m in mons:
    info = smap.infos[m.index]
    print(f"\n#{m.index} {m.name} 物理work=({m.wl},{m.wt})-({m.wr},{m.wb}) "
          f"scale={m.scale} primary={m.primary}")
    print(f"   Qt 逻辑work={info.work}  dpr={info.dpr}  ({info.name})")


def real_rect(w: QWidget):
    hwnd = int(w.winId())
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def probe(logical_x: int, logical_y: int):
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.resize(W, H)
    w.move(logical_x, logical_y)
    w.show()
    app.processEvents()
    rect = real_rect(w)
    w.close()
    return rect


ANCHOR = {
    "top-left": ("left", "top"), "top": ("center", "top"), "top-right": ("right", "top"),
    "left": ("left", "middle"), "center": ("center", "middle"), "right": ("right", "middle"),
    "bottom-left": ("left", "bottom"), "bottom": ("center", "bottom"),
    "bottom-right": ("right", "bottom"),
}


def check(preset: str, margin: int, tolerance: int = 2) -> bool:
    """独立 oracle：只用 ctypes 物理工作区 + 实测窗口物理尺寸推算期望落点。"""
    ok = True
    cfg["position"]["preset"] = preset
    cfg["position"]["margin"] = margin
    cx, cy = ANCHOR[preset]
    for m in mons:
        lx, ly = smap.origin(cfg, W, H, m.index)
        px, py, pw, ph = probe(lx, ly)
        pad = margin * m.scale  # margin 落盘为逻辑像素 → 物理距离
        want_x = {"left": m.wl + pad,
                  "center": (m.wl + m.wr) / 2 - pw / 2,
                  "right": m.wr - pw - pad}[cx]
        want_y = {"top": m.wt + pad,
                  "middle": (m.wt + m.wb) / 2 - ph / 2,
                  "bottom": m.wb - ph - pad}[cy]
        dx, dy = px - want_x, py - want_y
        good = abs(dx) <= tolerance and abs(dy) <= tolerance
        ok &= good
        print(f"  [{preset:12s} margin={margin:3d}] #{m.index} "
              f"逻辑move=({lx},{ly}) → 物理=({px},{py}) {pw}×{ph}  "
              f"期望=({want_x:.1f},{want_y:.1f}) 偏差=({dx:+.1f},{dy:+.1f})  "
              f"{'OK' if good else 'FAIL'}")
    return ok


print("\n=== 真实 HWND 落点校验 ===")
all_ok = True
all_ok &= check("center", 0)
all_ok &= check("top-left", 24)
all_ok &= check("bottom-right", 0)

print(f"\nRESULT {'PASS' if all_ok else 'FAIL'}")
sys.exit(0 if all_ok else 1)
