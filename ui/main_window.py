# -*- coding: utf-8 -*-
"""设置主窗口：7 页导航、黑白 IDE 风、即时生效、关闭行为三选一。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .pages import (Page01Display, Page02Time, Page03Style, Page04Position,
                    Page05General, Page06Profiles, Page07About)
from .theme import BG_DEEP, CARD, LINE, STYLESHEET
from .widgets import ConfirmDialog


class CloseChoiceDialog(QDialog):
    """关闭窗口「每次询问」：三个中文按钮，取消 = ✕ / Esc。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("dialog")
        self.setFixedSize(360, 150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(12)
        head = QHBoxLayout()
        h = QLabel("关闭窗口")
        h.setObjectName("section")
        head.addWidget(h, 1)
        x = QPushButton("✕")
        x.setFixedWidth(26)
        x.setFlat(True)
        x.setObjectName("link")
        x.clicked.connect(self.reject)
        head.addWidget(x)
        lay.addLayout(head)
        tip = QLabel("要最小化到托盘，还是退出软件？")
        tip.setObjectName("hint")
        lay.addWidget(tip)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, key in (("最小化到托盘", "minimize"), ("退出软件", "exit")):
            b = QPushButton(text)
            b.setObjectName("danger" if key == "exit" else "")
            b.clicked.connect(lambda _c=False, k=key: self._choose(k))
            row.addWidget(b)
        lay.addLayout(row)
        self.setStyleSheet(f"QDialog#dialog{{background:{CARD};border:1px solid {LINE};}}")
        p = self.parent()
        if isinstance(p, QWidget):
            g = p.frameGeometry()
            self.move(g.x() + (g.width() - self.width()) // 2,
                      g.y() + 31 + (g.height() - 31 - self.height()) // 2)

    def _choose(self, key: str) -> None:
        self.choice = key
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


class MainWindow(QWidget):
    quitRequested = Signal()
    windowHidden = Signal()

    NAV = ("01   显示器", "02   时间格式", "03   外观样式", "04   位置布局",
           "05   常规与行为", "06   配置方案", "07   关于")

    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.setWindowTitle("DesktopTime · 设置")
        self.setObjectName("root")
        self.resize(1000, 720)
        self.setMinimumSize(860, 600)
        # 窗口底色用 QPalette 明确指定，QSS 里不再给通用 QWidget 刷底色，
        # 白卡片内的子控件才不会变成一条条灰带。
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(BG_DEEP))
        self.setPalette(pal)
        self.setStyleSheet(STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.notice = QLabel("")
        self.notice.setObjectName("notice")
        self.notice.setFixedHeight(0)
        root.addWidget(self.notice)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._clear_notice)

        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(180)
        for text in self.NAV:
            self.nav.addItem(text)
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        self.pages = [Page01Display(controller), Page02Time(controller), Page03Style(controller),
                      Page04Position(controller), Page05General(controller),
                      Page06Profiles(controller), Page07About(controller)]
        for page in self.pages:
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)
        root.addLayout(body)

        self.nav.currentRowChanged.connect(self._on_nav)
        controller.notice.connect(self.show_notice)
        controller.settingsReplaced.connect(self._sync_current)

    def _on_nav(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
            self.pages[index].sync_all()

    def _sync_current(self) -> None:
        self.pages[self.stack.currentIndex()].sync_all()

    def show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setFixedHeight(30)
        self._notice_timer.start(5000)

    def _clear_notice(self) -> None:
        self.notice.setText("")
        self.notice.setFixedHeight(0)

    def closeEvent(self, event) -> None:
        action = self.c.get("tray.onClose", "ask")
        # 托盘不可见时不能最小化到托盘，否则软件无法恢复
        if not self.c.get("tray.enabled", True) and action == "minimize":
            action = "ask"
        if action == "ask":
            dlg = CloseChoiceDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice == "cancel":
                event.ignore()
                return
            action = dlg.choice
        if action == "exit":
            event.accept()
            self.quitRequested.emit()
        else:
            event.ignore()
            self.hide()
            self.windowHidden.emit()

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
