# -*- coding: utf-8 -*-
"""黑白 IDE 风共用控件：卡片、开关行、16 色点选色板、九宫格、显示器缩略图等。"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from .theme import (BG_DEEP, BRAND, BRAND_DEEP, BRAND_SOFT, CARD,
                    FG, FG_FAINT, LINE)

GRAY_SCALE = ("#1F2328", "#3D444D", "#5A626D", "#767F8B",
              "#8C959F", "#B8C0CA", "#D8DEE4", "#FFFFFF")
LOW_SAT = ("#C9413A", "#C77A3A", "#B79A3A", "#1F9D55",
           "#0969DA", "#6B5BD2", "#A2568F", "#4B8A99")
SWATCH_EDGE = "#aeb8c2"
# 预设缩略图的「屏幕底色」：模拟桌面壁纸，否则浅色墨迹在浅灰底上看不见
PREVIEW_BG = "#1B2430"
PREVIEW_EDGE = "#2C3947"   # 色块描边：比分隔线深一档，浅色块也能看出边界


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(10)

    def add(self, widget):
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self._layout.addLayout(layout)
        return layout


class SectionTitle(QWidget):
    """分区标题 + 1px 细分隔线。

    QLabel 的 QSS border-bottom 在本机 Qt 6 上不绘制（实测抓图无线），
    所以改用真实的 1px QWidget 画分隔线，稳定且符合「只用细线分区」。
    """

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lab = QLabel(text)
        lab.setObjectName("section")
        lay.addWidget(lab)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{LINE};")
        lay.addWidget(line)


class Hint(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("hint")
        self.setWordWrap(True)


class FlatToggle(QAbstractButton):
    """零圆角平涂开关：深蓝轨道 + 白色方钮。

    直接自绘，避开 QSS ::indicator 无法画钮、以及原生 CheckBox 在白卡片上
    显得笨重的问题。纯色填充，无渐变 / 发光 / 阴影，彩色面积仅 34×18。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(34, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(lambda _v=False: self.update())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        on = self.isChecked()
        p.fillRect(self.rect(), QColor(BRAND_DEEP if on else CARD))
        p.setPen(QPen(QColor(BRAND_DEEP if on else LINE), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        knob_x = self.width() - 14 if on else 2
        p.fillRect(QRect(knob_x, 2, 12, self.height() - 4),
                   QColor(CARD if on else FG_FAINT))
        p.end()


class SwitchRow(QWidget):
    toggled = Signal(bool)

    def __init__(self, label: str, desc: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        left = QVBoxLayout()
        left.setSpacing(2)
        name = QLabel(label)
        name.setObjectName("rowname")
        left.addWidget(name)
        if desc:
            tip = Hint(desc)
            left.addWidget(tip)
        lay.addLayout(left, 1)
        self.box = FlatToggle()
        self.box.toggled.connect(self.toggled.emit)
        lay.addWidget(self.box, 0, Qt.AlignmentFlag.AlignRight)

    def set_checked(self, value: bool) -> None:
        self.box.blockSignals(True)
        self.box.setChecked(bool(value))
        self.box.blockSignals(False)
        self.box.update()


class ColorSwatch(QPushButton):
    """点一下即设色的色块：26×22、1px 细边、零圆角。

    边框用比 LINE 更深的 SWATCH_EDGE，否则白色 / 浅灰色块在白卡片上
    几乎看不到边界（用户反馈「方块不够整齐」就是这一条）。
    """

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color.upper()
        self.setFixedSize(26, 22)
        self.setCheckable(True)
        self.setObjectName("swatch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton#swatch{{background:{self.color};"
            f"border:1px solid {SWATCH_EDGE};}}"
            f"QPushButton#swatch:hover{{border:1px solid {FG_FAINT};}}"
            f"QPushButton#swatch:checked{{border:2px solid {BRAND};}}"
        )


class ColorPalette(QWidget):
    """鼠标一点即设色的 16 色点选色板 + 最近使用 4 色 + 自定义颜色。"""
    colorSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self._swatches: list[ColorSwatch] = []
        grid = QGridLayout()
        grid.setSpacing(3)
        for row, colors in enumerate((GRAY_SCALE, LOW_SAT)):
            for col, color in enumerate(colors):
                sw = ColorSwatch(color)
                sw.clicked.connect(lambda _c=False, c=color: self._pick(c))
                grid.addWidget(sw, row, col)
                self._swatches.append(sw)
        # 尾列吃掉多余宽度，否则 8 列会被卡片宽度均匀拉散，色块之间出现大片空隙
        grid.setColumnStretch(len(GRAY_SCALE), 1)
        root.addLayout(grid)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(QLabel("最近使用"))
        self.recent_layout = QHBoxLayout()
        self.recent_layout.setSpacing(4)
        bottom.addLayout(self.recent_layout)
        bottom.addStretch(1)
        custom = QPushButton("自定义颜色…")
        custom.clicked.connect(self._custom)
        bottom.addWidget(custom)
        root.addLayout(bottom)
        self._current = "#1F2328"
        self.set_current(self._current)

    def _pick(self, color: str) -> None:
        self.set_current(color)
        self.colorSelected.emit(color)

    def _custom(self) -> None:
        color = QColorDialog.getColor(QColor(self._current), self, "选择文字颜色")
        if color.isValid():
            self._pick(color.name().upper())

    def set_current(self, color: str) -> None:
        self._current = (color or "#1F2328").upper()
        for sw in self._swatches:
            sw.blockSignals(True)
            sw.setChecked(sw.color == self._current)
            sw.blockSignals(False)

    def set_recent(self, colors: list[str]) -> None:
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for c in (colors or [])[:4]:
            sw = ColorSwatch(c)
            sw.setFixedSize(22, 20)
            sw.clicked.connect(lambda _c=False, v=c: self._pick(v))
            self.recent_layout.addWidget(sw)
        self.recent_layout.addStretch(1)


class PositionGrid(QWidget):
    """9 个预设位置：左上 / 上 / 右上 / 左 / 中 / 右 / 左下 / 下 / 右下。"""
    positionSelected = Signal(str)
    LABELS = ("左上", "上", "右上", "左", "居中", "右", "左下", "下", "右下")
    KEYS = ("top-left", "top", "top-right", "left", "center", "right",
            "bottom-left", "bottom", "bottom-right")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buttons: list[QPushButton] = []
        grid = QGridLayout(self)
        grid.setSpacing(4)
        for i, (label, key) in enumerate(zip(self.LABELS, self.KEYS)):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("posbtn")
            b.setFixedHeight(34)
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            grid.addWidget(b, i // 3, i % 3)
            self.buttons.append(b)
        self.set_current("top-right")

    def _pick(self, key: str) -> None:
        self.set_current(key)
        self.positionSelected.emit(key)

    def set_current(self, key: str) -> None:
        for b, k in zip(self.buttons, self.KEYS):
            b.blockSignals(True)
            b.setChecked(k == key)
            b.blockSignals(False)


class MonitorPreview(QWidget):
    """按真实虚拟桌面比例绘制显示器缩略图，点选目标屏。"""
    monitorSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitors = []
        self.selected = 0
        self._rects: list[tuple[int, QRect]] = []
        self.setFixedHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_monitors(self, monitors) -> None:
        self.monitors = list(monitors)
        self.update()

    def set_selected(self, index: int) -> None:
        self.selected = index
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CARD))
        p.setPen(QPen(QColor(LINE), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        if not self.monitors:
            p.setPen(QColor(FG_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "未检测到显示器")
            p.end()
            return
        l = min(m.left for m in self.monitors)
        t = min(m.top for m in self.monitors)
        r = max(m.right for m in self.monitors)
        b = max(m.bottom for m in self.monitors)
        vw, vh = max(1, r - l), max(1, b - t)
        area = QRect(18, 18, max(10, self.width() - 36), max(10, self.height() - 36))
        scale = min(area.width() / vw, area.height() / vh)
        offx = area.x() + (area.width() - vw * scale) / 2
        offy = area.y() + (area.height() - vh * scale) / 2
        self._rects = []
        f = QFont("Consolas")
        f.setPixelSize(11)
        p.setFont(f)
        for m in self.monitors:
            x = int(offx + (m.left - l) * scale)
            y = int(offy + (m.top - t) * scale)
            w = int(m.width * scale)
            h = int(m.height * scale)
            rect = QRect(x, y, w, h)
            self._rects.append((m.index, rect))
            active = m.index == self.selected
            p.fillRect(rect, QColor(BRAND_SOFT if active else BG_DEEP))
            p.setPen(QPen(QColor(BRAND_DEEP if active else LINE), 2 if active else 1))
            p.drawRect(rect)
            if active:
                p.fillRect(QRect(x, y, 3, h), QColor(BRAND_DEEP))  # 深蓝竖条零间隙
            p.setPen(QColor(BRAND_DEEP if active else FG))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       f"{m.index + 1}\n{m.work_width}×{m.work_height}")
        p.end()

    def mousePressEvent(self, event) -> None:
        for index, rect in self._rects:
            if rect.contains(event.position().toPoint()):
                self.set_selected(index)
                self.monitorSelected.emit(index)
                return


class PresetCard(QFrame):
    """样式预设卡：标题 + 副标 + 真实渲染缩略图。

    缩略图是拿该预设真的跑一遍渲染管线得到的，不是画个假图标 ——
    电子表的段码、指针的表盘、炫彩的辉光在卡片上就能看出区别。
    """

    clicked = Signal(str)
    HEIGHT = 104          # 03 页按它算「正好两行」的滚动区高度

    def __init__(self, key: str, title: str, badge: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("preset")
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(4)
        name = QLabel(title)
        name.setObjectName("presetname")
        head.addWidget(name)
        badge_lbl = QLabel(badge)
        badge_lbl.setObjectName("badge")
        head.addWidget(badge_lbl, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(head)

        self.preview = QLabel()
        self.preview.setObjectName("presetpreview")
        self.preview.setFixedHeight(54)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.preview)

        self._src_pix = None

        self.set_active(False)

    def set_preview(self, pixmap) -> None:
        # 原始图缓存起来，按标签实际宽度重缩放 —— 缩略图比标签宽时 QLabel 只会居中裁切，
        # 计时环的圆、虚线的框会被切掉半边（实测踩坑）
        self._src_pix = pixmap
        self._apply_preview()

    def _apply_preview(self) -> None:
        if self._src_pix is None or self._src_pix.isNull():
            return
        box_w = max(8, self.preview.width() - 2)
        box_h = max(8, self.preview.height() - 2)
        pix = self._src_pix
        if pix.width() > box_w or pix.height() > box_h:
            pix = pix.scaled(box_w, box_h, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pix)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_preview()

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "1" if active else "0")
        self.setStyleSheet(
            f"QFrame#preset{{background:{CARD};border:1px solid {LINE};}}"
            f"QFrame#preset[active='1']{{background:{BRAND_SOFT};"
            f"border:1px solid {LINE};border-left:3px solid {BRAND_DEEP};}}"
            # 缩略图底必须是深色：20 套预设全是「无底色 + 浅色墨」，
            # 摆在浅灰底上等于白纸看白字（极简/指针/翻页 直接看不见）。
            f"QLabel#presetpreview{{background:{PREVIEW_BG};"
            f"border:1px solid {PREVIEW_EDGE};}}"
        )
        self.style().polish(self)

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit(self.key)


class FeedbackBar(QFrame):
    undoClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("feedback")
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        self.label = QLabel("最近一次切换    暂无")
        self.label.setObjectName("hint")
        lay.addWidget(self.label, 1)
        self.undo_btn = QPushButton("撤销上一次切换")
        self.undo_btn.setObjectName("link")
        self.undo_btn.setFlat(True)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undoClicked.emit)
        lay.addWidget(self.undo_btn)

    def set_info(self, info: dict | None) -> None:
        if not info or not info.get("valid"):
            self.label.setText("最近一次切换    暂无可用回滚点")
            self.undo_btn.setEnabled(False)
            return
        self.label.setText(f"最近一次切换    {info.get('from', '?')}  →  {info.get('to', '?')}")
        self.undo_btn.setEnabled(True)


class ConfirmDialog(QDialog):
    """自绘确认框：按钮全中文，默认只给「确认」，取消 = ✕ / Esc。"""

    def __init__(self, parent, title: str, text: str, confirm: str = "确认", danger: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("dialog")
        self.setFixedWidth(360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("section")
        head.addWidget(t, 1)
        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.setObjectName("link")
        close.setFlat(True)
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setObjectName("hint")
        lay.addWidget(body)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(confirm)
        if danger:
            ok.setObjectName("danger")
        ok.setFixedWidth(96)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        self.setStyleSheet(
            f"QDialog#dialog{{background:{CARD};border:1px solid {LINE};}}"
        )
        self.center_on_parent()

    def center_on_parent(self) -> None:
        p = self.parent()
        if not isinstance(p, QWidget):
            return
        g = p.frameGeometry()
        titlebar = 31  # Windows 外框与客户区差值
        x = g.x() + (g.width() - self.width()) // 2
        y = g.y() + titlebar + (g.height() - titlebar - self.height()) // 2
        self.move(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)
