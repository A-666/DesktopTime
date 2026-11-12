# -*- coding: utf-8 -*-
"""7 个设置页。所有改动即时生效：控件信号 → controller.set → 落盘 + 重建渲染。"""
from __future__ import annotations

import copy
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from core import clock, store, stylepack
from core.renderer import Renderer
from core.settings import APP_VERSION, TEXT_STYLES
from .theme import CARD, LINE
from .widgets import (Card, ColorPalette, ConfirmDialog, FeedbackBar, Hint,
                      MonitorPreview, PositionGrid, PresetCard, SectionTitle, SwitchRow)

TEXT_STYLE_LABELS = {"bold": "加粗", "italic": "斜体", "underline": "下划线",
                     "outline": "描边", "shadow": "阴影"}


class NameDialog(QDialog):
    """自绘单行输入对话框：按钮全中文，取消 = ✕ / Esc。"""

    def __init__(self, parent, title: str, label: str, initial: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("dialog")
        self.setFixedWidth(360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        h = QLabel(title)
        h.setObjectName("section")
        head.addWidget(h, 1)
        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.setFlat(True)
        close.setObjectName("link")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)
        lay.addWidget(QLabel(label))
        self.edit = QLineEdit(initial)
        self.edit.selectAll()
        self.edit.returnPressed.connect(self.accept)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("确认")
        ok.setFixedWidth(96)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        self.setStyleSheet(f"QDialog#dialog{{background:{CARD};border:1px solid {LINE};}}")
        p = self.parent()
        if isinstance(p, QWidget):
            g = p.frameGeometry()
            self.move(g.x() + (g.width() - self.width()) // 2,
                      g.y() + 31 + (g.height() - 31 - self.height()) // 2)
        self.edit.setFocus()

    def value(self) -> str:
        return self.edit.text().strip()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


class BasePage(QWidget):
    def __init__(self, controller, title: str):
        super().__init__()
        self.c = controller
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("scroll")
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(24, 20, 24, 24)
        self.lay.setSpacing(14)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # 只留页标题：正文交给卡片标题表达，不再加一行「本页负责什么」的说明文字。
        head = QLabel(title)
        head.setObjectName("h1")
        self.lay.addWidget(head)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{LINE};")
        self.lay.addWidget(line)
        self.build()
        self.lay.addStretch(1)

        controller.settingsReplaced.connect(self.sync_all)
        controller.settingsChanged.connect(self.on_external_change)
        controller.profilesChanged.connect(self.on_profiles_changed)
        controller.monitorsChanged.connect(self.on_monitors_changed)
        self.sync_all()

    # 焦点控件不同步，避免正在输入时被 setText 打断光标
    def _sync(self, widget, setter, value) -> None:
        if widget is QApplication.focusWidget():
            return
        widget.blockSignals(True)
        try:
            setter(value)
        finally:
            widget.blockSignals(False)

    def build(self) -> None:  # pragma: no cover - 子类实现
        pass

    def sync_all(self) -> None:
        pass

    def on_external_change(self, _path, _value) -> None:
        self.sync_all()

    def on_profiles_changed(self) -> None:
        pass

    def on_monitors_changed(self) -> None:
        pass

    def card(self, title: str) -> Card:
        card = Card()
        card.add(SectionTitle(title))
        self.lay.addWidget(card)
        return card


class Page01Display(BasePage):
    def __init__(self, c):
        super().__init__(c, "01  显示器")

    def build(self) -> None:
        card = self.card("显示器布局")
        self.preview = MonitorPreview()
        self.preview.monitorSelected.connect(lambda i: self.c.set("display.index", i))
        card.add(self.preview)
        self.info = Hint("")
        card.add(self.info)

        row = Card()
        row.add(SectionTitle("显示范围"))
        self.all = SwitchRow("所有显示器同时显示", "每台显示器各显示一份，共用同一个时钟节拍")
        self.all.toggled.connect(lambda v: self.c.set("display.all", v))
        row.add(self.all)
        self.auto_refresh = SwitchRow("显示器变化自动刷新", "插拔显示器或改分辨率后重新识别")
        self.auto_refresh.toggled.connect(lambda v: self.c.set("display.autoRefresh", v))
        row.add(self.auto_refresh)
        self.identify = SwitchRow("选中时显示序号", "在对应屏幕中央短暂显示编号，方便辨认")
        self.identify.toggled.connect(lambda v: self.c.set("display.identifyOnSelect", v))
        row.add(self.identify)
        btn = QPushButton("识别显示器")
        btn.setFixedWidth(120)
        btn.clicked.connect(self.c.identifyRequested.emit)
        row.add(btn)
        self.lay.addWidget(row)

    def sync_all(self) -> None:
        self.preview.set_monitors(self.c.monitors)
        self.preview.set_selected(int(self.c.get("display.index", 0)))
        # 只留「序号 / 分辨率·缩放 / 主副屏」，不显示 \\.\DISPLAY1 这类设备路径：
        # 对用户没有决策价值，还会把这一行挤到折行。
        lines = [f"检测到 {len(self.c.monitors)} 台显示器"]
        for m in self.c.monitors:
            lines.append(f"  {m.index + 1}   {m.label}   "
                         f"{'主屏' if m.primary else '副屏'}")
        self.info.setText("\n".join(lines))
        self.all.set_checked(bool(self.c.get("display.all", False)))
        self.auto_refresh.set_checked(bool(self.c.get("display.autoRefresh", True)))
        self.identify.set_checked(bool(self.c.get("display.identifyOnSelect", True)))

    def on_monitors_changed(self) -> None:
        self.sync_all()


class Page02Time(BasePage):
    def __init__(self, c):
        super().__init__(c, "02  时间格式")

    def build(self) -> None:
        card = self.card("格式")
        self.fmt = QComboBox()
        for key, label in clock.FORMAT_PRESETS:
            self.fmt.addItem(label, key)
        self.fmt.currentIndexChanged.connect(
            lambda i: self.c.set("time.format", self.fmt.itemData(i)))
        card.add(self.fmt)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("自定义格式串，例如  HH:mm:ss dddd")
        self.custom.textChanged.connect(lambda t: self.c.set("time.custom", t))
        card.add(self.custom)
        self.lay.addWidget(Hint("可用标记：HH / H 小时，mm 分，ss 秒，yyyy-MM-dd 日期，dddd 星期，tt 上下午。"))

        row = Card()
        row.add(SectionTitle("附加内容"))
        for label, path in (("显示秒", "time.showSeconds"),
                            ("12 小时制", "time.hour12"),
                            ("显示日期", "time.showDate"),
                            ("显示星期", "time.showWeekday")):
            sw = SwitchRow(label)
            sw.toggled.connect(lambda v, p=path: self.c.set(p, v))
            row.add(sw)
            setattr(self, "sw_" + path.split(".")[-1], sw)
        self.lay.addWidget(row)

        prev = Card()
        prev.add(SectionTitle("预览"))
        self.preview = QLabel("14:35:08")
        f = QFont("Consolas")
        f.setPixelSize(34)
        self.preview.setFont(f)
        prev.add(self.preview)
        self.lay.addWidget(prev)
        self.c.tick.connect(self._tick)

    def _tick(self, _ms) -> None:
        main, sub = clock.build_lines(datetime.now(), self.c.data())
        self.preview.setText(main + (("\n" + sub) if sub else ""))

    def sync_all(self) -> None:
        key = self.c.get("time.format", "HH:mm:ss")
        idx = self.fmt.findData(key)
        self._sync(self.fmt, self.fmt.setCurrentIndex, max(0, idx))
        self._sync(self.custom, self.custom.setText, str(self.c.get("time.custom", "")))
        for name, path in (("showSeconds", "time.showSeconds"), ("hour12", "time.hour12"),
                           ("showDate", "time.showDate"), ("showWeekday", "time.showWeekday")):
            getattr(self, "sw_" + name).set_checked(bool(self.c.get(path, False)))
        self._tick(0)


class Page03Style(BasePage):
    # 全部无底色；20 张卡刻意做成一眼能分辨的风格，4 列 × 5 行
    PRESET_CARDS = (
        ("minimal", "极简", "无装饰"),
        ("lcd", "电子表", "段码残影"),
        ("analog", "指针", "线描表盘"),
        ("tech", "科技", "括号扫描线"),
        ("neon", "炫彩", "红青错位"),
        ("pop", "潮流", "贴纸描边"),
        ("flip", "翻页", "线框翻页"),
        ("matrix", "点阵", "LED 圆点"),
        ("serif", "衬线", "细下划线"),
        ("mono", "终端", "绿光标线"),
        ("amber", "琥珀", "CRT 荧光"),
        ("glitch", "故障", "RGB 错位"),
        ("caption", "字幕", "黑描边"),
        ("float", "浮起", "柔和投影"),
        ("ink", "墨字", "白描边"),
        ("ring", "计时环", "秒进度"),
        ("frame", "取景", "长角括号"),
        ("dash", "虚线", "细虚线框"),
        ("twin", "双线", "上下夹线"),
        ("thin", "细体", "Light 细字"),
    )

    def __init__(self, c):
        super().__init__(c, "03  外观样式")

    def build(self) -> None:
        card = self.card("样式预设")
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.cards: list[PresetCard] = []
        for i, (key, title, badge) in enumerate(self.PRESET_CARDS):
            pc = PresetCard(key, title, badge)
            pc.clicked.connect(self.c.set_preset)
            grid.addWidget(pc, i // 4, i % 4)
            self.cards.append(pc)
        # 尾列吃掉多余宽度，否则 4 列会被拉散成大片空隙
        grid.setColumnStretch(4, 1)
        # 20 套预设 = 5 行；固定只露两行、其余交给滚动条，
        # 免得下面的「文字 / 颜色 / 效果」被推到很远的地方。
        scroll = QScrollArea()
        scroll.setObjectName("presetscroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFixedHeight(PresetCard.HEIGHT * 2 + 10)
        scroll.setWidget(holder)
        card.add(scroll)
        self._build_previews()

        row = Card()
        row.add(SectionTitle("文字"))
        g = QGridLayout()
        g.setSpacing(8)
        self.font = QComboBox()
        for fam in sorted(QFontDatabase.families(), key=str.lower):
            self.font.addItem(fam, fam)
            # 每项用它自己的字体显示，选字体时能直接看到字形
            self.font.setItemData(self.font.count() - 1, QFont(fam),
                                  Qt.ItemDataRole.FontRole)
        self.font.currentIndexChanged.connect(self._font_changed)
        self.size = QSpinBox()
        self.size.setRange(12, 200)
        self.size.setSuffix(" px")
        self.size.valueChanged.connect(lambda v: self.c.set("style.size", v))
        self.weight = QComboBox()
        self.weight.addItems(("Light", "Regular", "Medium", "Bold"))
        self.weight.currentTextChanged.connect(lambda t: self.c.set("style.weight", t))
        for col, (label, widget) in enumerate((("字体", self.font), ("字号", self.size),
                                               ("字重", self.weight))):
            g.addWidget(QLabel(label), 0, col * 2)
            g.addWidget(widget, 0, col * 2 + 1)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 1)
        g.setColumnStretch(5, 1)
        row.add_layout(g)

        ts = QHBoxLayout()
        ts.setSpacing(12)
        ts.addWidget(QLabel("文字样式"))
        self.style_checks: dict[str, QCheckBox] = {}
        for key, label in TEXT_STYLE_LABELS.items():
            cb = QCheckBox(label)
            cb.toggled.connect(lambda _v, k=key: self._styles_changed())
            ts.addWidget(cb)
            self.style_checks[key] = cb
        ts.addStretch(1)
        row.add_layout(ts)
        self.lay.addWidget(row)

        color_card = Card()
        color_card.add(SectionTitle("文字颜色"))
        self.palette = ColorPalette()
        self.palette.colorSelected.connect(self._pick_color)
        color_card.add(self.palette)
        self.lay.addWidget(color_card)

        fx = Card()
        fx.add(SectionTitle("效果"))
        op = QHBoxLayout()
        op.setSpacing(10)
        op.addWidget(QLabel("不透明度"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.valueChanged.connect(self._opacity_changed)
        op.addWidget(self.opacity, 1)
        self.opacity_val = QLabel("100%")
        self.opacity_val.setObjectName("hint")
        self.opacity_val.setFixedWidth(38)
        self.opacity_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        op.addWidget(self.opacity_val)
        fx.add_layout(op)
        self.background = SwitchRow("背景板", "在时间后方绘制纯色底板")
        self.background.toggled.connect(lambda v: self.c.set("style.background.enabled", v))
        fx.add(self.background)
        self.lay.addWidget(fx)

        pack_card = Card()
        pack_card.add(SectionTitle("开放样式接口"))
        self.pack_label = Hint("")
        pack_card.add(self.pack_label)
        btns = QHBoxLayout()
        for text, slot in (("导入 .dtstyle…", self._import), ("清除样式包", self.c.clear_pack),
                           ("打开样式目录", self._open_styles)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        pack_card.add_layout(btns)
        self.lay.addWidget(pack_card)
        self.notice = Hint("")
        self.notice.hide()
        self.lay.addWidget(self.notice)
        self.c.notice.connect(self._show_notice)
        self.c.packChanged.connect(self._sync_pack)

    def _build_previews(self) -> None:
        """每张卡片缩略图都是该预设真跑一遍渲染管线得到的，不是画的假图标。"""
        renderer = Renderer()
        for pc in self.cards:
            pack = stylepack.get_builtin(pc.key)
            cfg = copy.deepcopy(self.c.data())
            cfg["style"].update({
                "font": pack["text"]["font"],
                "size": pack["text"]["size"],
                "weight": pack["text"]["weight"],
                "color": pack["text"]["color"],
                "textStyles": [],
                "opacity": 1.0,
                "background": {
                    "enabled": bool(pack.get("bg", {}).get("enabled")),
                    "color": pack.get("bg", {}).get("color", "#FFFFFF"),
                    "padding": pack.get("bg", {}).get("padding", 12),
                },
            })
            cfg["time"].update({"format": "HH:mm", "custom": "", "showSeconds": False,
                                "hour12": False, "showDate": False, "showWeekday": False})
            img = renderer.render(datetime(2026, 11, 11, 10, 9, 0), cfg, pack, 0, 1.0)
            pix = QPixmap.fromImage(img)
            # 这里不做缩放：卡片拿到原图后按自己实际宽度缩一次，二次缩放会糊
            pc.set_preview(pix)

    def _font_changed(self, index: int) -> None:
        family = self.font.itemData(index)
        if family:
            self.c.set("style.font", str(family))

    def _opacity_changed(self, value: int) -> None:
        self.opacity_val.setText(f"{value}%")
        self.c.set("style.opacity", round(value / 100, 2))

    def _show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _styles_changed(self) -> None:
        self.c.set("style.textStyles", [k for k, cb in self.style_checks.items() if cb.isChecked()])

    def _pick_color(self, color: str) -> None:
        self.c.set("style.color", color)
        self.c.push_recent_color(color)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 .dtstyle 样式包", "", "样式包 (*.dtstyle);;JSON (*.json)")
        if not path:
            return
        ok, msg = self.c.import_pack(path)
        self._show_notice(msg)
        if not ok:
            self.c.notice.emit(msg)

    def _open_styles(self) -> None:
        store.ensure_dirs()
        import os
        os.startfile(str(store.STYLES_DIR))

    def _sync_pack(self) -> None:
        ref = str(self.c.get("style.packRef", "") or "")
        preset = str(self.c.get("style.preset", "minimal"))
        current = f"样式包 {ref}" if ref else stylepack.PRESET_LABELS.get(preset, preset)
        self.pack_label.setText(
            f"当前    {current}        装饰层 {len(self.c.pack.get('decorations', []))} · "
            f"特效 {len(self.c.pack.get('effects', []))}")

    def sync_all(self) -> None:
        preset = str(self.c.get("style.preset", "minimal"))
        has_pack = bool(self.c.get("style.packRef", ""))
        for pc in self.cards:
            pc.set_active(pc.key == preset and not has_pack)
        idx = self.font.findData(str(self.c.get("style.font", "Consolas")))
        self._sync(self.font, self.font.setCurrentIndex, max(0, idx))
        self._sync(self.size, self.size.setValue, int(self.c.get("style.size", 48)))
        self._sync(self.weight, self.weight.setCurrentText, str(self.c.get("style.weight", "Medium")))
        active = set(self.c.get("style.textStyles", []) or [])
        for key, cb in self.style_checks.items():
            self._sync(cb, cb.setChecked, key in active)
        self.palette.set_current(str(self.c.get("style.color", "#1F2328")))
        self.palette.set_recent(list(self.c.get("style.recentColors", []) or []))
        value = int(float(self.c.get("style.opacity", 1.0)) * 100)
        self._sync(self.opacity, self.opacity.setValue, value)
        self.opacity_val.setText(f"{value}%")
        self.background.set_checked(bool(self.c.get("style.background.enabled", False)))
        self._sync_pack()


class Page04Position(BasePage):
    def __init__(self, c):
        super().__init__(c, "04  位置布局")

    def build(self) -> None:
        card = self.card("预设位置")
        self.grid = PositionGrid()
        # 九宫格是「相对桌面的固定锚点」：点一下即回到预设模式，不吃任何偏移量
        self.grid.positionSelected.connect(self.c.set_position_preset)
        card.add(self.grid)

        row = Card()
        row.add(SectionTitle("自定义位置"))
        g = QGridLayout()
        g.setSpacing(8)
        self.cx = QSpinBox()
        self.cy = QSpinBox()
        self.margin = QSpinBox()
        for spin in (self.cx, self.cy):
            spin.setRange(0, 20000)
        self.margin.setRange(0, 200)
        self.cx.valueChanged.connect(lambda v: self._edit_custom(v, None))
        self.cy.valueChanged.connect(lambda v: self._edit_custom(None, v))
        self.margin.valueChanged.connect(lambda v: self.c.set("position.margin", v))
        for i, (label, widget) in enumerate((("X", self.cx), ("Y", self.cy), ("边距", self.margin))):
            lab = QLabel(label)
            lab.setFixedWidth(30)
            g.addWidget(lab, 0, i * 3)
            g.addWidget(widget, 0, i * 3 + 1)
            if i < 2:                      # 两组之间留一列空白，否则 Y 会贴住 X 的输入框
                g.setColumnMinimumWidth(i * 3 + 2, 18)
        g.setColumnStretch(9, 1)
        row.add_layout(g)
        self.drag = SwitchRow("允许拖动", "点下方按钮后 15 秒内可拖动，结束自动恢复点击穿透")
        self.drag.toggled.connect(lambda v: self.c.set("position.dragEnabled", v))
        row.add(self.drag)
        self.snap = SwitchRow("对齐辅助线", "拖动时贴合工作区边缘")
        self.snap.toggled.connect(lambda v: self.c.set("position.snapGuides", v))
        row.add(self.snap)
        self.lock = SwitchRow("锁定位置", "锁定后拖动不改坐标")
        self.lock.toggled.connect(lambda v: self.c.set("position.lockPosition", v))
        row.add(self.lock)
        btns = QHBoxLayout()
        update = QPushButton("更新位置")
        update.clicked.connect(self.c.positionSyncRequested.emit)
        drag_btn = QPushButton("自定义拖动")
        drag_btn.clicked.connect(self.c.dragRequested.emit)
        btns.addWidget(update)
        btns.addWidget(drag_btn)
        btns.addStretch(1)
        row.add_layout(btns)
        self.lay.addWidget(row)

    def _edit_custom(self, x, y) -> None:
        """手改 X/Y = 用自定义落点覆盖位置；预设锚点本身不动。"""
        dx = int(self.cx.value() if x is None else x)
        dy = int(self.cy.value() if y is None else y)
        self.c.set_custom_position(int(self.c.get("display.index", 0)), dx, dy)

    def sync_all(self) -> None:
        # 预设模式下九宫格高亮；自定义模式下不高亮任何格子（一眼看出当前不是预设位）
        preset_mode = str(self.c.get("position.mode", "preset")) == "preset"
        self.grid.set_current(self.c.get("position.preset", "top-right") if preset_mode else "")
        self._sync(self.cx, self.cx.setValue, int(self.c.get("position.custom.x", 0)))
        self._sync(self.cy, self.cy.setValue, int(self.c.get("position.custom.y", 0)))
        self._sync(self.margin, self.margin.setValue, int(self.c.get("position.margin", 24)))
        self.drag.set_checked(bool(self.c.get("position.dragEnabled", True)))
        self.snap.set_checked(bool(self.c.get("position.snapGuides", True)))
        self.lock.set_checked(bool(self.c.get("position.lockPosition", False)))


class Page05General(BasePage):
    def __init__(self, c):
        super().__init__(c, "05  常规与行为")

    def build(self) -> None:
        card = self.card("启动与窗口")
        self.autostart = SwitchRow("开机自动启动", "写入当前用户注册表启动项")
        self.autostart.toggled.connect(lambda v: self.c.set("app.autoStart", v))
        card.add(self.autostart)
        self.tray = SwitchRow("常驻系统托盘，显示托盘图标", "")
        self.tray.toggled.connect(lambda v: self.c.set("tray.enabled", v))
        card.add(self.tray)
        self.ontop = SwitchRow("时间窗口置顶", "")
        self.ontop.toggled.connect(lambda v: self.c.set("window.alwaysOnTop", v))
        card.add(self.ontop)
        self.through = SwitchRow("鼠标点击穿透", "常态下鼠标可穿过时间；拖动时临时关闭")
        self.through.toggled.connect(lambda v: self.c.set("window.clickThrough", v))
        card.add(self.through)
        self.relocate = SwitchRow("显示器变化后自动重定位", "")
        self.relocate.toggled.connect(lambda v: self.c.set("window.autoRelocate", v))
        card.add(self.relocate)

        close = Card()
        close.add(SectionTitle("关闭窗口时"))
        self.close_combo = QComboBox()
        self.close_combo.addItem("每次询问", "ask")
        self.close_combo.addItem("最小化到托盘", "minimize")
        self.close_combo.addItem("退出软件", "exit")
        self.close_combo.currentIndexChanged.connect(
            lambda i: self.c.set("tray.onClose", self.close_combo.itemData(i)))
        close.add(self.close_combo)
        self.lay.addWidget(close)

        paths = Card()
        paths.add(SectionTitle("配置文件"))
        for text in (f"当前配置    {store.SETTINGS_FILE}",
                     f"配置方案    {store.PROFILES_DIR / '*.dtconfig'}",
                     f"样式包      {store.STYLES_DIR / '*.dtstyle'}",
                     f"回滚快照    {store.SNAPSHOT_FILE}"):
            lab = QLabel(text)
            lab.setObjectName("path")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            paths.add(lab)
        open_btn = QPushButton("打开配置目录")
        open_btn.setFixedWidth(130)
        open_btn.clicked.connect(store.open_config_dir)
        paths.add(open_btn)
        self.lay.addWidget(paths)

        danger = Card()
        danger.add(SectionTitle("恢复出厂"))
        btn = QPushButton("重置为默认")
        btn.setObjectName("danger")
        btn.setFixedWidth(130)
        btn.clicked.connect(self._reset)
        danger.add(btn)
        self.lay.addWidget(danger)

    def _reset(self) -> None:
        dlg = ConfirmDialog(self.window(), "重置为默认",
                            "全部设置将恢复为出厂值。已保存的配置方案与样式包会保留。",
                            confirm="重置", danger=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.c.reset_defaults()

    def sync_all(self) -> None:
        self.autostart.set_checked(bool(self.c.get("app.autoStart", False)))
        self.tray.set_checked(bool(self.c.get("tray.enabled", True)))
        self.ontop.set_checked(bool(self.c.get("window.alwaysOnTop", False)))
        self.through.set_checked(bool(self.c.get("window.clickThrough", True)))
        self.relocate.set_checked(bool(self.c.get("window.autoRelocate", True)))
        idx = self.close_combo.findData(self.c.get("tray.onClose", "ask"))
        self._sync(self.close_combo, self.close_combo.setCurrentIndex, max(0, idx))


class Page06Profiles(BasePage):
    def __init__(self, c):
        super().__init__(c, "06  配置方案")

    def build(self) -> None:
        self.feedback = FeedbackBar()
        self.feedback.undoClicked.connect(self.c.undo)
        # 页头只剩「标题 + 细线」两层，插到 2 才是紧贴细分隔线、位于首个卡片之上
        self.lay.insertWidget(2, self.feedback)

        card = self.card("已保存方案")
        self.list = QListWidget()
        self.list.setFixedHeight(220)
        self.list.itemClicked.connect(self._on_item_clicked)
        card.add(self.list)
        self.lay.addWidget(card)

        ops = Card()
        ops.add(SectionTitle("方案管理"))
        row = QHBoxLayout()
        for text, slot in (("保存当前设置", self._save), ("另存为…", self._save_as),
                           ("复制方案", self._duplicate), ("重命名", self._rename),
                           ("删除方案", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        ops.add_layout(row)
        self.lay.addWidget(ops)
        self.c.undoStateChanged.connect(self._refresh_feedback)
        self.c.profilesChanged.connect(self._refresh_list)

    def _current_name(self) -> str | None:
        item = self.list.currentItem()
        return item.text() if item else None

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.c.switch_profile(item.text())

    def _save(self) -> None:
        name = self._current_name() or self.c.current_label
        if name in ("当前配置", ""):
            self._save_as()
            return
        self.c.save_profile(name)

    def _save_as(self) -> None:
        dlg = NameDialog(self.window(), "另存为方案", "方案名称", "我的配置")
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.value():
            self.c.save_profile(dlg.value())

    def _duplicate(self) -> None:
        name = self._current_name()
        if not name:
            self.c.notice.emit("请先选择一个方案")
            return
        self.c.duplicate_profile(name)

    def _rename(self) -> None:
        name = self._current_name()
        if not name:
            self.c.notice.emit("请先选择一个方案")
            return
        dlg = NameDialog(self.window(), "重命名方案", "新名称", name)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.value():
            self.c.rename_profile(name, dlg.value())

    def _delete(self) -> None:
        name = self._current_name()
        if not name:
            self.c.notice.emit("请先选择一个方案")
            return
        dlg = ConfirmDialog(self.window(), "删除方案",
                            f"方案「{name}」将被删除，且不可恢复。", confirm="删除", danger=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.c.delete_profile(name)

    def _refresh_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for row in self.c.profiles.list():
            item = QListWidgetItem(row["name"])
            if row["savedAt"]:
                item.setToolTip(f"保存于 {row['savedAt']}")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._refresh_feedback()

    def _refresh_feedback(self, *_args) -> None:
        self.feedback.set_info(self.c.undo_info())

    def on_profiles_changed(self) -> None:
        self._refresh_list()

    def sync_all(self) -> None:
        self._refresh_list()


class Page07About(BasePage):
    def __init__(self, c):
        super().__init__(c, "07  关于")

    def build(self) -> None:
        card = self.card("DesktopTime")
        for text in (
            f"版本    {APP_VERSION}",
            "作者    Clear",
            "邮箱    1722430560@qq.com",
            "版权    Copyright (C) 2026 Clear. 保留所有权利.",
            "系统    Windows 10 / 11  x64",
        ):
            lab = QLabel(text)
            lab.setObjectName("about")
            card.add(lab)
        self.lay.addWidget(card)

        tech = Card()
        tech.add(SectionTitle("技术与接口"))
        for text in (
            "技术栈    Python 3.12 + PySide6 (Qt 6) + Windows API",
            "当前配置  settings.json    ·    配置方案  .dtconfig    ·    样式包  .dtstyle",
            "开放样式接口    8 类装饰 + 4 类特效 + 3 种绘制方式，纯 JSON 数据，不执行脚本",
            "内置预设        20 套：极简 / 电子表 / 指针 / 科技 / 炫彩 / 潮流 / 翻页 / 点阵 / 衬线 / 终端 / 琥珀 / 故障 / 字幕 / 浮起 / 墨字 / 计时环 / 取景 / 虚线 / 双线 / 细体",
            "界面规范        黑白 IDE 风：两层底色、零圆角、1px 细线、彩色仅表达状态",
        ):
            lab = Hint(text)
            tech.add(lab)
        self.lay.addWidget(tech)
        link = Hint("设计稿    https://ardot.tencent.com/file/746274895717591")
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(link)

    def sync_all(self) -> None:
        pass
