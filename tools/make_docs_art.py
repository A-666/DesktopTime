# -*- coding: utf-8 -*-
"""生成 docs/ 里的两张展示图：README 首图（hero）与 GitHub 社交预览图。

关键点：时钟不是贴图，而是**用产品自己的渲染器实时画出来的** —— 以后改了
样式或排版，重跑本脚本即可同步，不会出现「图上是旧版本」的假宣传。

用法（必须带真实字体后端，offscreen 没有字体，字形会变成方框）：
    QT_QPA_PLATFORM=windows python tools/make_docs_art.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt                    # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage,  # noqa: E402
                           QPainter, QPen)
from PySide6.QtWidgets import QApplication                      # noqa: E402

from core import renderer as R, stylepack                       # noqa: E402
from core.settings import defaults                              # noqa: E402

DOCS = ROOT / "docs"
SCREEN = QColor("#1b1f26")       # 屏幕底色
TASKBAR = QColor("#232833")
BEZEL = QColor("#ffffff")
EDGE = QColor("#d3dae2")
INK = QColor("#1f2328")          # 主文字
MUTED = QColor("#5b6472")        # 次要文字
CANVAS = QColor("#eef1f6")
DARK = QColor("#161a20")
ACCENT = QColor("#2f6df6")


def ui_font(px: int, bold: bool = False) -> QFont:
    f = QFont("Microsoft YaHei")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def clock(style: str, size: int, fmt: str, with_date: bool, scale: float = 2.0) -> QImage:
    """用真实渲染器画一枚时钟，白字、无背景板。"""
    pack = stylepack.get_builtin(style)
    cfg = defaults()
    cfg["style"].update({"color": "#FFFFFF", "size": size, "textStyles": []})
    cfg["style"]["background"]["enabled"] = False
    cfg["time"].update({
        "format": fmt, "showSeconds": "ss" in fmt,
        "showDate": with_date, "showWeekday": with_date,
    })
    return R.Renderer().render(datetime(2026, 11, 12, 21, 8, 36), cfg, pack, 0, scale)


def draw_clock(p: QPainter, img: QImage, x: float, y: float, w: float, h: float) -> None:
    p.drawImage(QRect(int(x), int(y), int(w), int(h)), img)


def screen(p: QPainter, box: QRect, radii: int = 0) -> QRect:
    """画一台显示器：白边框 + 深色屏 + 底部任务栏，返回屏幕内容矩形。"""
    p.setPen(QPen(EDGE, 1))
    p.setBrush(BEZEL)
    p.drawRect(box)
    inner = box.adjusted(9, 9, -9, -9)
    p.setPen(Qt.NoPen)
    p.setBrush(SCREEN)
    p.drawRect(inner)
    p.setBrush(TASKBAR)
    p.drawRect(QRect(inner.left(), inner.bottom() - 22, inner.width(), 23))
    p.setBrush(QColor("#4a5568"))                       # 任务栏几个小方块，暗示桌面
    for i in range(3):
        p.drawRect(QRect(inner.left() + 14 + i * 20, inner.bottom() - 15, 11, 11))
    return inner


def build_hero() -> Path:
    w, h = 1600, 800
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(CANVAS)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # 左上角字标：图片被单独转发时也能自报家门
    p.setPen(INK)
    p.setFont(ui_font(28, True))
    p.drawText(QPoint(96, 104), "DesktopTime")
    p.setPen(MUTED)
    p.setFont(ui_font(15))
    p.drawText(QPoint(96, 132), "Windows 桌面悬浮时钟 · 多显示器 · 20 套开源样式")

    # 左屏：科技风、右上预设。底边与右屏对齐，标签才能排成一行
    left = QRect(96, 178, 800, 472)
    li = screen(p, left)
    # 屏里叠一个暗色窗口，说明这是「桌面」而不是一块黑板；纯平涂，不加阴影
    win = QRect(li.left() + 46, li.bottom() - 262, 336, 186)
    p.setPen(QPen(QColor("#2b3140"), 1))
    p.setBrush(QColor("#20242d"))
    p.drawRect(win)
    p.fillRect(QRect(win.left() + 1, win.top() + 1, win.width() - 1, 20), QColor("#262b35"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#4a5568"))
    for i in range(3):
        p.drawRect(QRect(win.left() + 10 + i * 13, win.top() + 8, 5, 5))

    tech = clock("tech", 52, "HH:mm:ss", True)
    draw_clock(p, tech, li.right() - tech.width() / 2 - 46, li.top() + 40,
               tech.width() / 2, tech.height() / 2)

    # 右屏：衬线风、居中（尺寸更小，对标 1.5 倍缩放的副屏）
    right = QRect(932, 230, 580, 420)
    ri = screen(p, right)
    serif = clock("serif", 44, "HH:mm", True)
    draw_clock(p, serif, ri.center().x() - serif.width() / 4,
               ri.center().y() - serif.height() / 4 - 18,
               serif.width() / 2, serif.height() / 2)

    p.setPen(MUTED)
    p.setFont(ui_font(14))
    p.drawText(QRect(left.left(), left.bottom() + 22, left.width(), 24),
               Qt.AlignHCenter, "显示器 1 · 1.0x · 右上预设")
    p.drawText(QRect(right.left(), right.bottom() + 22, right.width(), 24),
               Qt.AlignHCenter, "显示器 2 · 1.5x · 居中 · 逐屏原生渲染")

    # 页脚一句核心卖点
    p.setPen(QColor("#8a94a3"))
    p.setFont(ui_font(15))
    p.drawText(QRect(0, h - 44, w, 24), Qt.AlignHCenter,
               "九宫格预设与自定义拖动两套位置模型 · 全部设置即时生效 · 无背景板，只有文字与线状装饰")
    p.end()

    out = DOCS / "hero.png"
    img.convertToFormat(QImage.Format_RGB32).save(str(out))
    return out


def build_social() -> Path:
    w, h = 1280, 640
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(DARK)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # 右侧：三枚不同风格的时钟右对齐排成一列 —— 一张卡片就把「20 套样式」说清
    # 用 lcd 而不是 flip：翻页卡的卡框缩到这个尺寸会糊成一排方框，反而像画坏了
    right_edge = 1192
    for key, top, with_date in (("tech", 176, False), ("lcd", 334, False), ("serif", 472, True)):
        art = clock(key, 48, "HH:mm", with_date)
        w2, h2 = art.width() / 2, art.height() / 2
        draw_clock(p, art, right_edge - w2, top, w2, h2)

    p.setPen(QColor("#FFFFFF"))
    p.setFont(ui_font(66, True))
    p.drawText(QPoint(88, 312), "DesktopTime")
    p.setPen(QColor("#a8b3c1"))
    p.setFont(ui_font(26))
    p.drawText(QPoint(90, 362), "Windows 桌面悬浮时钟")
    p.setPen(QColor("#7d8798"))
    p.setFont(ui_font(19))
    p.drawText(QPoint(90, 418), "多显示器 · 九宫格预设 · 20 套开源样式")
    p.drawText(QPoint(90, 452), "开放样式接口 .dtstyle · 全部设置即时生效")

    p.setPen(QColor("#5c6675"))
    p.setFont(ui_font(16))
    p.drawText(QPoint(90, 578), "Python 3.12 · PySide6 · MIT")

    p.fillRect(QRect(0, h - 6, w, 6), ACCENT)     # 底部一条强调线，克制地只占 6px
    p.end()

    out = DOCS / "social-preview.png"
    img.convertToFormat(QImage.Format_RGB32).save(str(out))
    return out


def main() -> int:
    if QApplication.instance() is None:
        QApplication([])
    if "Microsoft YaHei" not in QFontDatabase.families():
        print("WARN 没有 Microsoft YaHei，中文会退化成别的字体")
    DOCS.mkdir(exist_ok=True)
    for path in (build_hero(), build_social()):
        print("已生成", path, path.stat().st_size, "字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
