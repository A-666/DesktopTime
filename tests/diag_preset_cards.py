# -*- coding: utf-8 -*-
"""诊断：03 页 20 张样式预设卡的宽高到底等不等。

用户看到的现象是「有几列明显更宽/更窄」。QGridLayout 里只给尾列设了
stretch，前 4 列按各自的 sizeHint 分配 —— 而 sizeHint 又受标题文字、
缩略图像素宽度影响，于是列宽跟着内容走。

用法：QT_QPA_PLATFORM=windows python tests/diag_preset_cards.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QScrollArea      # noqa: E402

from test_core import IsolatedStore                          # noqa: E402
from core.controller import AppController                     # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402

OUT = Path(os.environ.get("TEMP", ".")) / "dt_ui"


def settle(app, win, page) -> None:
    """改完尺寸必须让布局真跑一轮：只 processEvents 一次会抓到旧几何。"""
    win.layout().activate()
    page.layout().activate()
    for _ in range(4):
        app.processEvents()


def report(tag: str, cards) -> None:
    ws = Counter(c.width() for c in cards)
    hs = Counter(c.height() for c in cards)
    print(f"\n== {tag} ==")
    for row in range(5):
        cells = []
        for col in range(4):
            c = cards[row * 4 + col]
            cells.append(f"{c.width():>4}")
        print("  第%d行 " % (row + 1) + " ".join(cells))
    uniq_w = sorted(ws)
    uniq_h = sorted(hs)
    if max(uniq_w) - min(uniq_w) <= 1:
        verdict_w = f"等宽（{uniq_w}，差 ≤1px 为整数取整）"
    else:
        verdict_w = f"宽 {len(uniq_w)} 种：{uniq_w}"
    verdict_h = "等高" if len(uniq_h) == 1 else f"高 {len(uniq_h)} 种：{uniq_h}"
    print(f"  → {verdict_w}；{verdict_h}")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    iso = IsolatedStore()
    iso.__enter__()
    c = AppController(dpi_mode="TEST")
    win = MainWindow(c)
    win.show()
    settle(app, win, win)

    win.nav.setCurrentRow(2)           # 03 外观样式
    page = win.pages[2]
    box = page.findChild(QScrollArea, "presetscroll")

    OUT.mkdir(parents=True, exist_ok=True)
    for win_w in (860, 1000, 1280):
        win.resize(win_w, 720)
        settle(app, win, page)
        report(f"窗口 {win_w}（滚动区视口 {box.viewport().width()}）", page.cards)

    win.resize(1000, 720)
    settle(app, win, page)
    page.grab().save(str(OUT / "preset_cards.png"))
    print(f"\n截图：{OUT / 'preset_cards.png'}")

    c.settings.set("tray.onClose", "exit")   # 否则 close() 弹模态框卡死
    win.close()
    iso.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
