# -*- coding: utf-8 -*-
"""DesktopTime 入口：DPI 感知 → 单实例 → 装配 → 事件循环 → 硬退出。

作者 Clear · 1722430560@qq.com · Copyright (C) 2026 Clear. 保留所有权利.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
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


def _flush_streams() -> None:
    """刷标准流，且必须容忍它们是 None。

    `console=False` 的冻结产物在**没有控制台**启动时（资源管理器双击、计划任务、
    另一台机器上从 Release 解压运行），`sys.stdout` / `sys.stderr` 都是 None。
    直接 `.flush()` 抛的是 `AttributeError`，它不是 `OSError`，旧代码的
    `except (OSError, ValueError)` 兜不住，异常一路冲出 `main()`，被 PyInstaller
    引导器接住后弹「Unhandled exception in script」，进程还得等用户点关闭才死。
    从命令行/带重定向启动时句柄有效、流不是 None，所以这个坑只在双击时出现 ——
    自动化脚本用 `stdout=DEVNULL` 启动永远测不出来。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.flush()
        except (OSError, ValueError):
            pass


def _log_unhandled(exc_type, exc, tb) -> None:
    """未捕获异常只写日志，绝不把 traceback 甩给用户看。"""
    try:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        store.log(f"未捕获异常：\n{text}", "ERROR")
    except Exception:      # 日志本身失败也不能再引发二次异常
        pass


def _hard_exit(code: int) -> None:
    """立即结束进程，不做任何析构（用于还没有 Qt 对象、或已确认无救的场合）。"""
    _flush_streams()
    os._exit(code)


def _exit_with_watchdog(code: int, timeout: float = 2.5) -> None:
    """先给解释器一次体面收尾的机会，卡死再硬杀。

    为什么不能直接 `os._exit`：事件循环跑完之后 Qt 的托盘、窗口、内部线程都还活着，
    此时 `os._exit`（即 ExitProcess）会在别的线程还在跑的时候强拆 DLL —— 实测退出码
    变成 `0xC0000005`（访问冲突）。进程是没了、用户也看不出来，但 Windows 事件日志
    里会记一条应用错误，某些杀软会据此报毒，属于「能收场但脏」。

    也不能纯靠正常返回：PySide6 + onefile 的析构顺序不确定，历史上就是它会卡住，
    表现成「点了退出进程还在」。所以两头都要 —— 正常走解释器收尾拿到 rc=0，
    再用一个 daemon 定时器兜底；正常情况它永远不触发，真卡死了它替我们把进程收掉。
    """
    timer = threading.Timer(timeout, lambda: (_flush_streams(), os._exit(code)))
    timer.daemon = True
    timer.start()


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
    # 走到这里说明事件循环已退出：先把去抖中的配置补写，再体面退出（带看门狗兜底）
    store.log(f"事件循环结束 rc={rc}，进程退出")
    controller.flush_pending()
    _exit_with_watchdog(0)
    return 0  # 正常收尾时从这里返回，让解释器把 rc=0 交回引导器


if __name__ == "__main__":
    # Qt 槽里漏出的异常先交给 excepthook 记账，不让它冒到引导器变成弹窗
    sys.excepthook = _log_unhandled
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:                  # noqa: BLE001 —— 兜底必须最宽
        # 任何漏网异常都在这里收口：写日志 + 硬退出。
        # 否则 PyInstaller 引导器会弹「Unhandled exception in script」，
        # 而那个弹窗是阻塞的，用户不点关闭进程就一直挂着。
        _log_unhandled(*sys.exc_info())
        _hard_exit(1)
    except Exception as exc:  # 启动期异常留痕，避免无窗口静默退出
        store.log(f"启动失败: {type(exc).__name__}: {exc}", "ERROR")
        raise
