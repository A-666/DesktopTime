# -*- coding: utf-8 -*-
"""窗口自身抓图：逐页保存 PNG 供肉眼复核，不受桌面 z-order 遮挡影响。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_core import IsolatedStore  # noqa: E402

from core.controller import AppController  # noqa: E402
from ui.clock_window import ClockWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

OUT = Path(os.environ.get("TEMP", ".")) / "dt_ui"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication([])
iso = IsolatedStore()
iso.__enter__()
c = AppController(dpi_mode="TEST")
win = MainWindow(c)
win.resize(1000, 720)
win.show()
app.processEvents()

for i in range(7):
    win.nav.setCurrentRow(i)
    app.processEvents()
    path = OUT / f"page{i + 1:02d}.png"
    win.grab().save(str(path))
    print("PAGE", i + 1, path.name)

# 03 页预设区是两行高滚动区：再抓一张滚到底的，肉眼复核第 3~5 行的缩略图
from PySide6.QtWidgets import QScrollArea  # noqa: E402
win.nav.setCurrentRow(2)
app.processEvents()
sc = win.pages[2].findChild(QScrollArea, "presetscroll")
if sc is not None:
    bar = sc.verticalScrollBar()
    bar.setValue(bar.maximum())
    app.processEvents()
    win.grab().save(str(OUT / "page03b.png"))
    print("PAGE 3B page03b.png  scroll max =", bar.maximum())

clock = ClockWindow(c, None)
clock.show()
app.processEvents()
# 合成到浅灰底，避免透明背景在查看器里显示成黑块
pm = clock.grab()
canvas = QImage(pm.width(), pm.height(), QImage.Format_ARGB32)
canvas.fill(QColor("#EEF1F6"))
p = QPainter(canvas)
p.drawPixmap(0, 0, pm)
p.end()
clock_path = OUT / "clock.png"
canvas.save(str(clock_path))
print("CLOCK", clock_path, canvas.width(), canvas.height())

c._timer.stop()
c.settings.set("tray.onClose", "exit")
win.close()
clock.close()
iso.__exit__(None, None, None)
