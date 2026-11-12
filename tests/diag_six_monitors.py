# -*- coding: utf-8 -*-
"""诊断：6 台显示器时，01 页的缩略图放不放得下、字看不看得清。

真实场景是「虚拟桌面越宽，缩略图越小」，控件高度又写死 170px，
所以不能只看会不会溢出，还要量每块缩略图里那行 `宽×高` 放不放得下。

用法：QT_QPA_PLATFORM=windows python tests/diag_six_monitors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QFont, QFontMetrics                 # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from test_core import IsolatedStore                           # noqa: E402
from core.controller import AppController                     # noqa: E402
from core.monitors import Monitor                             # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402

OUT = Path(__import__("os").environ.get("TEMP", ".")) / "dt_ui"
# 注意：QFont 必须在 QApplication 之后构造。模块级构造 QFont 时字体数据库还不存在，
# Qt 会直接终止进程（无栈、无输出，只看到 SIGTERM），极难排查。
FONT_FAMILY, FONT_PX = "Consolas", 11


def mk(index: int, x: int, y: int, w: int, h: int, dpi: int = 96,
       primary: bool = False) -> Monitor:
    return Monitor(index=index, name=f"MON{index + 1}", left=x, top=y,
                   right=x + w, bottom=y + h, wl=x, wt=y, wr=x + w, wb=y + h - 48,
                   dpi=dpi, primary=primary)


def layouts() -> dict[str, list[Monitor]]:
    """几种真实的 6 屏组合。"""
    return {
        "一行 6 台 1080p": [
            mk(i, i * 1920, 0, 1920, 1080, 96, i == 0) for i in range(6)
        ],
        "3×2 阵列（1080p）": [
            mk(i, (i % 3) * 1920, (i // 3) * 1080, 1920, 1080, 96, i == 0)
            for i in range(6)
        ],
        "2 列 × 3 层（竖排，最容易压扁）": [
            mk(i, (i % 2) * 1920, (i // 2) * 1080, 1920, 1080, 96, i == 0)
            for i in range(6)
        ],
        "一行 6 台 4K": [
            mk(i, i * 3840, 0, 3840, 2160, 144, i == 0) for i in range(6)
        ],
        "混排（4K + 2K + 1080p）": [
            mk(0, 0, 0, 3840, 2160, 144, True),
            mk(1, 3840, 0, 2560, 1440, 120),
            mk(2, 6400, 0, 1920, 1080, 96),
            mk(3, 6400, 1080, 1920, 1080, 96),
            mk(4, 8320, 0, 1920, 1080, 96),
            mk(5, 8320, 1080, 1920, 1080, 96),
        ],
    }


def main() -> int:
    app = QApplication.instance() or QApplication([])
    iso = IsolatedStore()
    iso.__enter__()
    c = AppController(dpi_mode="TEST")
    win = MainWindow(c)
    win.resize(1000, 720)          # 默认尺寸
    page = win.stack.widget(0)     # 01 显示器
    OUT.mkdir(parents=True, exist_ok=True)

    fm_font = QFont(FONT_FAMILY)
    fm_font.setPixelSize(FONT_PX)
    fm = QFontMetrics(fm_font)
    text_w = max(fm.horizontalAdvance(t) for t in ("1920×1080", "3840×2160"))

    for name, monitors in layouts().items():
        c.monitors = monitors
        page.sync_all()
        win.show()
        app.processEvents()
        pv = page.preview
        print(f"\n== {name} ==")
        for win_w in (860, 1000, 1280):      # 最小尺寸 / 默认 / 放大
            win.resize(win_w, 720)
            app.processEvents()
            pv.repaint()
            app.processEvents()
            rects = pv._rects
            widths = [r.width() for _, r in rects]
            heights = [r.height() for _, r in rects]
            need = text_w + 16                 # 两侧各留 8px 呼吸
            verdict = "放得下" if min(widths) >= need else "会被裁"
            print(f"  窗口 {win_w}: 预览 {pv.width()}×{pv.height()}  "
                  f"单块最小 {min(widths)}×{min(heights)}  需 {need}px → {verdict}")
        win.resize(1000, 720)
        app.processEvents()
        pv.repaint()
        pv.grab().save(str(OUT / f"six_{list(layouts()).index(name)}.png"))

    # 整页截图：分别存「3 列 × 2 层」和「2 列 × 3 层竖排」，后者是高度自适应的关键用例
    # 缩略图改高度后父布局要重排一轮，只 processEvents 一次会抓到旧几何（看起来像文字压住方块）
    for tag, key in (("six_page", "3×2 阵列（1080p）"),
                     ("six_page_stacked", "2 列 × 3 层（竖排，最容易压扁）")):
        c.monitors = layouts()[key]
        page.sync_all()
        win.layout().activate()
        page.layout().activate()
        for _ in range(3):
            app.processEvents()
        page.grab().save(str(OUT / f"{tag}.png"))
    print("\n已存", OUT)
    # 必须先关掉「每次询问」：否则 win.close() 会弹模态确认框，
    # 进程卡死在那里，表现为无输出 + 被 SIGTERM（test_gui 里同样处理）
    c.settings.set("tray.onClose", "exit")
    win.close()
    iso.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
