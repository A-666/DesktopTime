# -*- coding: utf-8 -*-
"""诊断：03 / 04 页的「显示器」下拉框，以及每屏独立样式是否真的生效。

用法：QT_QPA_PLATFORM=windows python tests/diag_per_monitor.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication                  # noqa: E402

from test_core import IsolatedStore                         # noqa: E402
from test_gui import fake_monitors                          # noqa: E402
from core.controller import AppController                   # noqa: E402
from ui.clock_window import ClockWindow                     # noqa: E402
from ui.main_window import MainWindow                       # noqa: E402

OUT = Path(os.environ.get("TEMP", ".")) / "dt_ui"


def settle(app, win=None, page=None) -> None:
    if win is not None:
        win.layout().activate()
    if page is not None:
        page.layout().activate()
    for _ in range(4):
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    iso = IsolatedStore()
    iso.__enter__()
    c = AppController(dpi_mode="TEST")
    c.monitors = fake_monitors(2)
    win = MainWindow(c)
    win.resize(1000, 720)
    win.show()
    settle(app, win)

    OUT.mkdir(parents=True, exist_ok=True)

    # 1) 单屏模式：下拉框应该在，但「应用到全部 / 取消单独设置」是灰的
    win.nav.setCurrentRow(2)
    page3 = win.pages[2]
    settle(app, win, page3)
    print("== 单屏模式 ==")
    print("  下拉项:", [page3.picker.combo.itemText(i) for i in range(page3.picker.combo.count())])
    print("  可编辑:", page3.picker.combo.isEnabled(), "应用全部:", page3.picker.apply_btn.isEnabled())
    print("  提示:", page3.picker.hint.text())
    page3.grab().save(str(OUT / "pm_style_single.png"))

    # 2) 多屏模式：给两块屏设不同预设，看是否各走各的
    c.set("display.all", True)
    c.set_edit_index(0)
    c.set_preset("neon")
    c.set_edit_index(1)
    c.set_preset("lcd")
    settle(app, win, page3)
    print("\n== 多屏模式 ==")
    print("  提示:", page3.picker.hint.text())
    print("  picker 选中:", page3.picker.combo.currentData(), "编辑目标:", c.edit_index())
    print("  0 号屏预设:", c.config_for(0)["style"]["preset"],
          "| 1 号屏预设:", c.config_for(1)["style"]["preset"])
    page3.grab().save(str(OUT / "pm_style_multi.png"))

    win.nav.setCurrentRow(3)
    page4 = win.pages[3]
    settle(app, win, page4)
    print("  04 页编辑目标:", page4.picker.combo.currentData(),
          "| 位置预设:", c.get("position.preset"))
    page4.grab().save(str(OUT / "pm_position_multi.png"))

    # 3) 两台时钟窗口各自用自己那份样式
    w0 = ClockWindow(c, 0)
    w1 = ClockWindow(c, 1)
    settle(app)
    print("\n== 时钟窗口 ==")
    print("  窗口0 预设:", w0.cfg()["style"]["preset"], "尺寸", w0.width(), "x", w0.height())
    print("  窗口1 预设:", w1.cfg()["style"]["preset"], "尺寸", w1.width(), "x", w1.height())
    w0.grab().save(str(OUT / "pm_clock0.png"))
    w1.grab().save(str(OUT / "pm_clock1.png"))

    c.settings.set("tray.onClose", "exit")
    for w in (w0, w1):
        w.close()
    win.close()
    iso.__exit__(None, None, None)
    print("\n已存", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
