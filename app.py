# -*- coding: utf-8 -*-
"""DesktopTime 入口：DPI 感知 → 单实例 → 装配 → 事件循环 → 硬退出。

作者 Clear · 1722430560@qq.com · Copyright (C) 2026 Clear. 保留所有权利.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_qt_on_path() -> None:
    """允许用系统 Python 直接运行：补上本机已有的 PySide6 site-packages。"""
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "Lib" / "site-packages",
        Path(os.environ.get("APPDATA", "")) / "Python" / "Python312" / "site-packages",
    ]
    for path in candidates:
        if (path / "PySide6").is_dir():
            sys.path.append(str(path))
            return


_ensure_qt_on_path()

from PySide6.QtCore import QObject, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from core import clock, single_instance, store, stylepack  # noqa: E402,F401
from core.controller import BUILTIN_DIR, AppController  # noqa: E402
from core.monitors import enum_monitors, set_dpi_awareness  # noqa: E402
from tray import TrayController, make_icon  # noqa: E402
from ui.clock_window import ClockWindow, IdentifyOverlay  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


class ClockManager(QObject):
    """持有全部时间窗口；display.all 时每屏一个，共享 controller 的唯一 QTimer。"""

    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self.windows: list[ClockWindow] = []
        self.overlays: list[IdentifyOverlay] = []
        self._visible = True
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.timeout.connect(self.end_drag)

        self.c.dragRequested.connect(self.begin_drag)
        self.c.positionSyncRequested.connect(self.sync_position)
        self.c.identifyRequested.connect(self.identify)
        self.c.rebuildRequested.connect(self.rebuild)
        self.c.settingsReplaced.connect(self.rebuild)
        self.c.monitorsChanged.connect(self.rebuild)
        self.c.settingsChanged.connect(self.on_settings_changed)
        self.rebuild()

    def rebuild(self) -> None:
        for w in self.windows:
            w.blockSignals(True)
            w.close()
            w.deleteLater()
        self.windows = []
        cfg = self.c.data()
        targets: list[int | None] = ([m.index for m in self.c.monitors]
                                     if cfg["display"]["all"] else [None])
        for idx in targets:
            w = ClockWindow(self.c, idx)
            if not self._visible:
                w.hide()
            self.windows.append(w)
        store.log(f"时间窗口重建：{len(self.windows)} 个（display.all={cfg['display']['all']}）")

    def on_settings_changed(self, path: str, _value) -> None:
        if path == "display.all":
            self.rebuild()
        elif path == "display.index":
            for w in self.windows:
                w._reposition()

    def toggle_visible(self) -> None:
        self._visible = not self._visible
        for w in self.windows:
            w.setVisible(self._visible)
        store.log(f"时间显示：{'开' if self._visible else '关'}")

    def begin_drag(self) -> None:
        cfg = self.c.data()
        if not cfg["position"]["dragEnabled"] or cfg["position"]["lockPosition"]:
            self.c.notice.emit("拖动未开启或位置已锁定，请到 04 页检查")
            return
        for w in self.windows:
            w.set_drag_mode(True)
        self.c.notice.emit("拖动模式已开启，15 秒后自动恢复点击穿透")
        self._drag_timer.start(15000)

    def sync_position(self) -> None:
        """「更新位置」：把时间窗口当前落点记成自定义位置（不动九宫格预设）。"""
        for w in self.windows:
            w.commit_current_position()
        self.c.notice.emit("当前位置已记为自定义位置")

    def end_drag(self) -> None:
        for w in self.windows:
            w.set_drag_mode(False)

    def identify(self) -> None:
        if not self.c.get("display.identifyOnSelect", True):
            return
        self._clear_overlays()
        from ui.screens import build_screen_map
        smap = build_screen_map(self.c.monitors)
        self.overlays = [IdentifyOverlay(m, m.index + 1, smap.infos[i].work)
                         for i, m in enumerate(self.c.monitors)]
        for overlay in self.overlays:
            overlay.show()
        QTimer.singleShot(2000, self._clear_overlays)

    def _clear_overlays(self) -> None:
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []


class MonitorPoller(QObject):
    """显示器热插拔 / 缩放变化：2s 签名轮询 + 500ms 去抖。

    等价于 WM_DISPLAYCHANGE / WM_SETTINGCHANGE 监听，但不依赖原生消息泵，
    在 Qt 与 Python 3.12/3.13 下都不会因 nativeEventFilter 签名差异崩溃。
    """

    def __init__(self, controller: AppController):
        super().__init__()
        self.c = controller
        self._sig = self._signature()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(2000)

    @staticmethod
    def _signature():
        return tuple((m.name, m.wl, m.wt, m.wr, m.wb, m.dpi) for m in enum_monitors())

    def check(self) -> None:
        sig = self._signature()
        if sig == self._sig:
            return
        self._sig = sig
        QTimer.singleShot(500, self.on_change)

    def on_change(self) -> None:
        if self.c.get("display.autoRefresh", True):
            store.log("显示器布局变化，重新枚举")
            self.c.refresh_monitors()


def _cli_command(argv: list[str]) -> str | None:
    """支持 --quit（让已在跑的实例退出，用于打包产物的退出自检）。"""
    for arg in argv:
        if arg in ("--quit", "-q"):
            return "quit"
        if arg in ("--raise", "-r"):
            return "raise"
    return None


def _hard_exit(code: int) -> None:
    """绕过解释器析构阶段直接结束进程。

    PySide6 + PyInstaller onefile 在退出时会按任意顺序析构 QSystemTrayIcon /
    QLocalServer / QMenu，偶发析构阻塞 —— 表现就是「点了退出，任务管理器里
    进程还在」，用户只能手动结束。配置已落盘、日志已 flush 之后，
    进程状态已没有需要保留的东西，硬退出在语义上是等价且确定的。
    """
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    os._exit(code)


def main() -> int:
    dpi_mode = set_dpi_awareness()  # 必须早于 QApplication
    want = _cli_command(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("DesktopTime")
    app.setOrganizationName("Clear")
    app.setQuitOnLastWindowClosed(False)
    # 任务栏 / Alt-Tab / 标题栏图标；托盘与 exe 图标共用同一份资源
    app_icon = make_icon()
    app.setWindowIcon(app_icon)

    store.ensure_dirs()
    first_run = not store.SETTINGS_FILE.exists()
    stylepack.export_builtin_files(BUILTIN_DIR)
    store.log(f"启动：DPI={dpi_mode}，首次运行={first_run}，参数={sys.argv[1:]}")

    # 单实例判据是内核互斥量：拿不到锁就说明已有实例，绝不能再起第二套窗口。
    if not single_instance.acquire():
        delivered = single_instance.send(want or "raise")
        store.log(f"已有实例在运行，投递 {want or 'raise'} "
                  f"{'成功' if delivered else '失败（对方可能无响应）'}，本次启动直接退出")
        _hard_exit(0)
    if want == "quit":
        store.log("当前没有实例在运行，--quit 无对象可退")
        _hard_exit(0)

    controller = AppController(dpi_mode=dpi_mode)
    controller.apply_autostart(bool(controller.get("app.autoStart", False)))
    clocks = ClockManager(controller)
    win = MainWindow(controller)
    win.setWindowIcon(app_icon)
    tray = TrayController(app, controller, win, clocks)

    def on_command(command: str) -> None:
        store.log(f"收到外部指令：{command}")
        if command == "quit":
            tray.quit_app()
        else:
            win.show_and_raise()

    server = single_instance.start_server(on_command)
    poller = MonitorPoller(controller)
    _keep = (server, poller, tray, clocks)  # 防止被 GC

    if first_run:
        win.show()
        win.show_and_raise()
    else:
        # 注意：PySide6 的 showMessage 第三个参数名是 icon，不是 type
        try:
            tray.icon.showMessage("DesktopTime", "已启动，双击托盘图标可打开设置。",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception as exc:  # 气泡不是关键路径，签名差异不应拖垮启动
            store.log(f"托盘启动提示失败: {exc}", "WARN")

    rc = app.exec()
    # 走到这里说明事件循环已退出：先把去抖中的配置补写，再硬退出
    store.log(f"事件循环结束 rc={rc}，进程退出")
    controller.flush_pending()
    _hard_exit(0)
    return 0  # 不会执行，保留让类型检查通过


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # 启动期异常留痕，避免无窗口静默退出
        store.log(f"启动失败: {type(exc).__name__}: {exc}", "ERROR")
        raise
