# -*- coding: utf-8 -*-
"""系统托盘：动态方案菜单、一键切换、撤销上一次切换、关闭行为提示。"""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core import store
from ui.theme import BRAND_DEEP, CARD, FG, ICON_FILE, MENU_STYLESHEET


def make_icon() -> QIcon:
    """应用图标：exe / 标题栏 / 任务栏 / 托盘共用同一份 .ico。"""
    if ICON_FILE.is_file():
        icon = QIcon(str(ICON_FILE))
        if not icon.isNull():
            return icon
    store.log("应用图标资源缺失，使用内置绘制兜底", "WARN")
    # 兜底：资源被误删时仍要保证托盘可见
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(CARD))
    p.setPen(QPen(QColor(BRAND_DEEP), 2))
    p.drawEllipse(QRectF(2, 2, 28, 28))
    p.setPen(QPen(QColor(FG), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(16, 16, 16, 8)
    p.drawLine(16, 16, 22, 19)
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    def __init__(self, app: QApplication, controller, main_window, clock_manager):
        super().__init__()
        self.app = app
        self.c = controller
        self.win = main_window
        self.clocks = clock_manager
        self.icon = QSystemTrayIcon(make_icon(), self)
        self.icon.setToolTip("DesktopTime · 桌面时间")
        self.menu = QMenu()
        self.menu.setStyleSheet(MENU_STYLESHEET)
        self.icon.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self.rebuild_menu)
        self.icon.activated.connect(self._activated)
        self._quitting = False

        self.c.profilesChanged.connect(self.rebuild_menu)
        self.c.undoStateChanged.connect(self.rebuild_menu)
        self.c.settingsReplaced.connect(self.rebuild_menu)
        self.win.quitRequested.connect(self.quit_app)
        self.win.windowHidden.connect(
            lambda: self.icon.showMessage("DesktopTime", "已最小化到托盘，双击图标可打开设置。",
                                          QSystemTrayIcon.MessageIcon.Information, 3000))
        self.rebuild_menu()
        self.set_enabled(bool(self.c.get("tray.enabled", True)))

    def quit_app(self) -> None:
        """唯一的退出入口：窗口关闭 / 托盘菜单 / 外部 --quit 都走这里。

        顺序不能省：先隐藏托盘图标（否则通知区会留一个死图标到鼠标划过为止），
        再把去抖中的配置落盘，最后退出事件循环；进程终结由 app.py 的硬退出兜底。
        """
        if self._quitting:
            return
        self._quitting = True
        store.log("退出：开始收尾")
        try:
            self.menu.hide()
            self.icon.hide()
            self.win.hide()
        except RuntimeError as exc:
            store.log(f"退出时隐藏界面失败: {exc}", "WARN")
        self.c.flush_pending()
        store.log("退出：请求事件循环结束")
        self.app.quit()

    def set_enabled(self, enabled: bool) -> None:
        if enabled and QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()
        else:
            self.icon.hide()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.win.show_and_raise()

    def rebuild_menu(self) -> None:
        self.menu.clear()
        toggle = self.menu.addAction("显示 / 隐藏时间")
        toggle.triggered.connect(self.clocks.toggle_visible)
        self.menu.addAction("打开设置", self.win.show_and_raise)
        self.menu.addSeparator()

        rows = self.c.profiles.list()
        if rows:
            group_label = self.menu.addAction("本机配置方案    /    点一下即切换")
            group_label.setEnabled(False)
            current = self.c.current_label
            for row in rows:
                act = self.menu.addAction(row["name"])
                act.setCheckable(True)
                act.setChecked(row["name"] == current)
                act.triggered.connect(lambda _c=False, n=row["name"]: self.c.switch_profile(n))
            self.menu.addSeparator()
        undo = self.menu.addAction("撤销上一次切换")
        undo.setEnabled(self.c.can_undo())
        info = self.c.undo_info()
        if info and info.get("valid"):
            undo.setToolTip(f"{info.get('from')} → {info.get('to')}")
        undo.triggered.connect(self.c.undo)
        self.menu.addSeparator()
        self.menu.addAction("退出", self.quit_app)
