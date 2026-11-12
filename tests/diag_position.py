# -*- coding: utf-8 -*-
"""定位坐标系诊断：ctypes 物理几何 vs Qt 屏幕几何 vs 窗口真实落点。"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from core.monitors import compute_origin, enum_monitors  # noqa: E402
from core.settings import defaults  # noqa: E402

app = QApplication([])
mons = enum_monitors()

print("=== ctypes EnumDisplayMonitors (物理像素) ===")
for m in mons:
    print(f"  #{m.index} work=({m.wl},{m.wt})-({m.wr},{m.wb}) "
          f"size={m.work_width}x{m.work_height} dpi={m.dpi} scale={m.scale} primary={m.primary}")

print("=== Qt QScreen (Qt 坐标系) ===")
for s in app.screens():
    g, a = s.geometry(), s.availableGeometry()
    print(f"  {s.name()} geom=({g.x()},{g.y()},{g.width()},{g.height()}) "
          f"avail=({a.x()},{a.y()},{a.width()},{a.height()}) "
          f"dpr={s.devicePixelRatio()} logicalDPI={s.logicalDotsPerInch()}")

W, H = 231, 76
cfg = defaults()
cfg["position"]["preset"] = "center"
for idx in range(len(mons)):
    x, y = compute_origin(cfg, mons, W, H, idx)
    print(f"=== 目标屏 #{idx} 居中：compute_origin -> ({x}, {y}) ===")

    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.resize(W, H)
    w.move(x, y)
    w.show()
    app.processEvents()

    hwnd = int(w.winId())
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    fg = w.frameGeometry()
    print(f"  Win32 GetWindowRect = ({r.left},{r.top})-({r.right},{r.bottom})  "
          f"size={r.right - r.left}x{r.bottom - r.top}")
    print(f"  Qt  frameGeometry   = ({fg.x()},{fg.y()}) {fg.width()}x{fg.height()}")
    print(f"  偏差 = ({r.left - x}, {r.top - y})")
    w.close()
