# -*- coding: utf-8 -*-
"""黑白 IDE 风视觉令牌 —— 与 LanFTP `lanftp/ui_kit.py::Palette` 对齐。

用户明确要求「全部控件要有简洁的 UI 效果，类似于 LanFTP 项目的 UI」，
因此这里直接采用 LanFTP 的 GitHub Light 配色，而不是另造一套近似色。

铁律：
  * 底色只两层：窗口 BG_DEEP + 卡片 CARD；第三层一律用 1px LINE 分隔
  * 零圆角、纯色平涂，禁止渐变 / 发光 / 阴影
  * 彩色只表达状态，面积 < 5%；选中态 = 浅蓝底 + 深蓝竖条，零间隙
  * 低饱和深绿 OK / 深红 DANGER（不用亮绿、正红）
"""
from __future__ import annotations

import sys
from pathlib import Path


def asset_path(relative: str) -> Path:
    """资源绝对路径：源码运行读工程目录，PyInstaller 冻结后读 _MEIPASS。"""
    base = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent)
    return base / "resources" / "icons" / relative


ICON_FILE = asset_path("desktoptime.ico")
ARROW_UP = asset_path("spin_up.png").as_posix()
ARROW_DOWN = asset_path("spin_down.png").as_posix()
CHECK_MARK = asset_path("check.png").as_posix()
ARROW_COMBO = asset_path("combo_down.png").as_posix()

BG_DEEP = "#f6f7f9"      # 窗口底
CARD = "#ffffff"         # 卡片 / 控件底
FG = "#1f2328"           # 主文字
FG_DIM = "#57606a"       # 次文字
FG_FAINT = "#8c959f"     # 弱提示
LINE = "#d8dee4"         # 1px 分隔线 / 控件描边
BRAND = "#0969da"        # 链接 / 焦点
BRAND_SOFT = "#ddf4ff"   # 选中态浅蓝底
BRAND_DEEP = "#0550ae"   # 深蓝竖条 / 开关轨道
OK = "#1f9d55"           # 低饱和深绿
DANGER = "#c9413a"       # 低饱和深红
DANGER_SOFT = "#fbefee"
HOVER = "#f3f4f6"
PRESSED = "#e8eaee"

MENU_STYLESHEET = f"""
QMenu {{ background:{CARD}; border:1px solid {LINE}; padding:4px; }}
QMenu::item {{ padding:6px 24px; color:{FG}; }}
QMenu::item:selected {{ background:{BRAND_SOFT}; color:{BRAND_DEEP}; }}
QMenu::item:disabled {{ color:{FG_FAINT}; }}
QMenu::separator {{ height:1px; background:{LINE}; margin:4px 2px; }}
"""

# ★ 关键：绝不在通用 `QWidget` 选择器里写 background。
# 旧版 `QWidget { background:#F6F8FA }` 会级联到白卡片内的每一个子控件，
# 于是 SectionTitle 变成灰色标题条、每个 SwitchRow 变成灰色横带 —— 视觉上
# 就是「白 + 灰白 + 更灰」三层交替，正是用户反馈「不够简洁」的根因。
STYLESHEET = f"""
QWidget {{
    color:{FG};
    font-family:'Microsoft YaHei UI','Microsoft YaHei','Segoe UI';
    font-size:12px;
}}
QWidget#root {{ background:{BG_DEEP}; }}

QFrame#card {{ background:{CARD}; border:1px solid {LINE}; }}
QFrame#feedback {{ background:{CARD}; border:1px solid {LINE}; }}

/* 分区标题只用 1px 细线，不用灰底标题条 */
QLabel#h1 {{ font-size:19px; font-weight:600; }}
QLabel#section {{ font-size:13px; font-weight:600; }}
QLabel#hint, QLabel#badge {{ color:{FG_DIM}; font-size:11px; }}
QLabel#path, QLabel#about {{ font-family:Consolas,'Microsoft YaHei UI';
                            font-size:11px; color:{FG_DIM}; }}
QLabel#rowname {{ font-size:12px; }}
QLabel#presetname {{ font-size:13px; font-weight:600; }}
QLabel#sample {{ color:{FG}; }}
QLabel#notice {{ background:{BRAND_SOFT}; color:{BRAND_DEEP};
                 padding:6px 14px; border-bottom:1px solid {LINE}; }}

QScrollArea#scroll {{ border:0; background:transparent; }}
QScrollArea#scroll > QWidget > QWidget {{ background:transparent; }}
QScrollArea#presetscroll {{ border:0; background:transparent; }}
QScrollArea#presetscroll > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:0; border:0; }}
QScrollBar::handle:vertical {{ background:{LINE}; min-height:30px; border:0; }}
QScrollBar::handle:vertical:hover {{ background:{FG_FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; border:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
QScrollBar:horizontal {{ height:0; }}

/* 导航 / 列表：浅蓝底 + 深蓝竖条，零间隙 */
QListWidget#nav {{ background:{CARD}; border:1px solid {LINE}; outline:0; }}
QListWidget#nav::item {{ height:42px; padding-left:14px; color:{FG};
                         border-bottom:1px solid {HOVER}; border-left:3px solid transparent; }}
QListWidget#nav::item:selected {{ background:{BRAND_SOFT}; color:{BRAND_DEEP};
                                  border-left:3px solid {BRAND_DEEP}; }}
QListWidget#nav::item:hover:!selected {{ background:{HOVER}; }}
QListWidget {{ background:{CARD}; border:1px solid {LINE}; outline:0; }}
QListWidget::item {{ height:30px; padding-left:8px; color:{FG}; }}
QListWidget::item:selected {{ background:{BRAND_SOFT}; color:{BRAND_DEEP};
                              border-left:3px solid {BRAND_DEEP}; }}
QListWidget::item:hover:!selected {{ background:{HOVER}; }}

/* 输入控件：白底 + 1px 细线，零圆角，hover / focus 只换线色 */
QLineEdit, QSpinBox, QComboBox, QFontComboBox {{
    background:{CARD}; border:1px solid {LINE}; padding:5px 7px; min-height:22px;
    selection-background-color:{BRAND_SOFT}; selection-color:{FG};
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QFontComboBox:hover {{ border-color:{FG_FAINT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QFontComboBox:focus {{ border-color:{BRAND}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    background:{BG_DEEP}; color:{FG_FAINT};
}}
QComboBox::drop-down {{ border:0; width:18px; }}
/* 同 QSpinBox 的坑：定制过 drop-down 之后原生三角不再绘制，
   不给 ::down-arrow 图片，下拉框看起来就像纯输入框。 */
QComboBox::down-arrow {{ image:url("{ARROW_COMBO}"); width:9px; height:6px; }}
QComboBox::down-arrow:hover {{ image:url("{ARROW_COMBO}"); }}
QComboBox QAbstractItemView {{
    background:{CARD}; border:1px solid {LINE}; outline:0;
    selection-background-color:{BRAND_SOFT}; selection-color:{FG};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width:16px; background:{CARD}; border-left:1px solid {LINE};
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background:{HOVER}; }}
/* QSS 一旦自定义了 up/down-button，原生三角就不再绘制，
   必须显式给 ::up-arrow / ::down-arrow 指定图片，否则是空方框。 */
QSpinBox::up-arrow {{ image:url("{ARROW_UP}"); }}
QSpinBox::down-arrow {{ image:url("{ARROW_DOWN}"); }}

/* 按钮：白底细边，hover 只换极浅底色，不加发光 */
QPushButton {{ background:{CARD}; color:{FG}; border:1px solid {LINE};
               padding:6px 12px; min-height:20px; }}
QPushButton:hover {{ background:{HOVER}; border-color:{FG_FAINT}; }}
QPushButton:pressed {{ background:{PRESSED}; }}
QPushButton:disabled {{ background:{BG_DEEP}; color:{FG_FAINT}; border-color:{LINE}; }}
QPushButton:checked {{ background:{BRAND_SOFT}; border-color:{BRAND}; color:{BRAND_DEEP}; }}
QPushButton#danger {{ color:{DANGER}; border-color:{DANGER}; }}
QPushButton#danger:hover {{ background:{DANGER_SOFT}; }}
QPushButton#link {{ border:0; background:transparent; color:{BRAND}; padding:2px; }}
QPushButton#link:hover {{ color:{BRAND_DEEP}; background:transparent; }}
QPushButton#link:disabled {{ color:{FG_FAINT}; }}
QPushButton#posbtn:checked {{
    background:{BRAND_SOFT}; color:{BRAND_DEEP};
    border:1px solid {LINE}; border-left:3px solid {BRAND_DEEP};
}}
QPushButton#swatch {{ border:1px solid {LINE}; }}
QPushButton#swatch:checked {{ border:2px solid {BRAND}; }}

/* 小复选框：去掉原生立体边，勾选只给浅蓝底 */
QCheckBox {{ spacing:6px; color:{FG}; }}
QCheckBox::indicator {{ width:14px; height:14px; }}
QCheckBox::indicator:unchecked {{ background:{CARD}; border:1px solid {LINE}; }}
QCheckBox::indicator:checked {{ background:{BRAND_SOFT}; border:1px solid {BRAND};
                                image:url("{CHECK_MARK}"); }}
QCheckBox::indicator:hover {{ border-color:{FG_FAINT}; }}

/* 滑块：细轨 + 方柄 */
QSlider::groove:horizontal {{ height:3px; background:{LINE}; border:0; }}
QSlider::handle:horizontal {{ width:12px; height:12px; margin:-5px 0;
                              background:{BRAND}; border:0; }}
QSlider::sub-page:horizontal {{ background:{BRAND_SOFT}; border:0; }}

QToolTip {{ background:{CARD}; color:{FG}; border:1px solid {LINE}; padding:4px; }}
"""
