# -*- coding: utf-8 -*-
"""单实例锁 + 进程间指令投递。

为什么权威判据必须是内核互斥量，而不是 QLocalServer
-------------------------------------------------
旧实现靠「连得上 socket 说明已有实例，连不上就自己 listen」。这在启动期
有一个明确窗口：首个进程还没执行到 listen()，第二个进程 connect 失败，
于是走 removeServer() + listen() —— 它反客为主，两个实例同时活下来，
桌面上出现两份时间、两个托盘图标，退掉其中一个另一个还在。

CreateMutexW 没有这个窗口：调用即代表「要么我拿到，要么别人已经持有」，
进程结束由内核自动释放，不会像锁文件那样留下陈旧状态。
QLocalSocket 退化成单纯的信使，只负责把 raise / quit 送到已在跑的实例。

打包注意：onefile 的 exe 会出现两个同名进程（引导器 + 主程序），
那是正常现象；退出后两个都必须消失，见 app.py 的硬退出逻辑。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import store

SOCKET_NAME = "DesktopTime_Clear_SingleInstance_v1"
MUTEX_NAME = "Local\\DesktopTime_Clear_SingleInstance_v1"
ERROR_ALREADY_EXISTS = 183

# 只接受这几个指令，避免把 socket 当成任意命令通道
COMMANDS = ("raise", "quit")

_held: InstanceLock | None = None


class InstanceLock:
    """进程级单实例锁：acquire() 返回 True 表示本进程是唯一实例。"""

    def __init__(self) -> None:
        self.handle: int | None = None
        self.already_running = False

    def acquire(self) -> bool:
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, wintypes.BOOL(False), MUTEX_NAME)
            err = kernel32.GetLastError()
        except OSError as exc:  # 非 Windows 或受限环境：降级为放行
            store.log(f"单实例锁不可用: {exc}", "WARN")
            return True
        if not handle:
            store.log("单实例锁创建失败，按首实例处理", "WARN")
            return True
        self.handle = handle
        self.already_running = err == ERROR_ALREADY_EXISTS
        return not self.already_running

    def release(self) -> None:
        if self.handle:
            try:
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except OSError:
                pass
            self.handle = None


def acquire() -> bool:
    """模块级保活：句柄必须比 main() 活得久，否则锁会被提前释放。"""
    global _held
    _held = InstanceLock()
    return _held.acquire()


def send(command: str, timeout_ms: int = 800) -> bool:
    """把指令发给已在运行的实例。返回是否送达（连不上就是没人接）。"""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError as exc:
        store.log(f"单实例通道不可用: {exc}", "WARN")
        return False
    if command not in COMMANDS:
        return False
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(command.encode("ascii"))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


def start_server(on_command) -> object | None:
    """首实例监听指令；on_command(cmd) 由调用方决定行为。"""
    try:
        from PySide6.QtNetwork import QLocalServer
    except ImportError as exc:
        store.log(f"指令通道不可用: {exc}", "WARN")
        return None

    QLocalServer.removeServer(SOCKET_NAME)  # 清掉上次崩溃留下的陈旧端点
    server = QLocalServer()
    if not server.listen(SOCKET_NAME):
        store.log(f"指令通道监听失败: {server.errorString()}", "WARN")
        return None

    def _on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        # 小 payload 也会分段到达，必须等一下再读
        conn.waitForReadyRead(300)
        raw = bytes(conn.readAll()).decode("ascii", "ignore").strip()
        conn.close()
        if raw in COMMANDS:
            on_command(raw)
        else:
            on_command("raise")

    server.newConnection.connect(_on_connection)
    return server
