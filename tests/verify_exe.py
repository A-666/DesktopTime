# -*- coding: utf-8 -*-
"""独立 exe 验证：干净环境启动 → 单实例唤醒 → 窗口枚举 → 日志/版本资源检查。

★ 沙箱 APPDATA：产品启动会回写 settings.json，直接在真实 %APPDATA% 上跑
  会把用户正在用的样式/位置改掉（已踩过）。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXE = ROOT / "dist" / "DesktopTime.exe"
SANDBOX = Path(os.environ.get("TEMP", ".")) / "dt_exe_check" / "appdata"

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

from core.single_instance import SOCKET_NAME  # noqa: E402  单一来源，避免改名后静默失效


def visible_desktoptime_windows() -> list[str]:
    user32 = ctypes.windll.user32
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[str] = []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if "DesktopTime" in buf.value:
                    found.append(buf.value)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found


def main() -> int:
    if not EXE.is_file():
        print("EXE_MISSING", EXE)
        return 1
    print(f"EXE {EXE}  {EXE.stat().st_size / 1024 / 1024:.1f} MB")

    # 干净环境：去掉所有可能让 exe 蹭到本机 Python/Qt 的变量
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM",
                "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        env.pop(key, None)
    env["APPDATA"] = str(SANDBOX)          # ★ 隔离用户真实配置
    workdir = Path(os.environ.get("TEMP", ".")) / "dt_exe_check"
    workdir.mkdir(parents=True, exist_ok=True)

    log = SANDBOX / "DesktopTime" / "logs" / "desktoptime.log"
    log_before = log.stat().st_size if log.is_file() else 0

    proc = subprocess.Popen([str(EXE)], cwd=str(workdir), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(9)
    alive = proc.poll() is None
    print(f"PROCESS_ALIVE {alive}  pid={proc.pid}")
    if not alive:
        print("STDOUT", proc.stdout.read().decode("utf-8", "replace")[-1500:])
        print("STDERR", proc.stderr.read().decode("utf-8", "replace")[-1500:])

    print("WINDOWS_BEFORE_WAKE", visible_desktoptime_windows())
    app = QCoreApplication([])
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if sock.waitForConnected(1200):
        sock.write(b"raise")
        sock.flush()
        sock.waitForBytesWritten(1200)
        sock.disconnectFromServer()
        print("WAKE_SENT True")
    else:
        print("WAKE_SENT False", sock.errorString())
    time.sleep(2)
    print("WINDOWS_AFTER_WAKE", visible_desktoptime_windows())

    fresh = ""
    if log.is_file():
        with log.open("rb") as f:
            f.seek(log_before)
            fresh = f.read().decode("utf-8", errors="replace")
    print("---- THIS RUN LOG ----")
    print(fresh.strip()[-2000:] or "(no new log lines)")
    print(f"HAS_ERROR {'[ERROR]' in fresh}")

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{EXE}').VersionInfo | Select-Object CompanyName,"
             "FileDescription,LegalCopyright,ProductVersion | Format-List"],
            capture_output=True, text=True, encoding="gbk", errors="replace", timeout=20,
        )
        print("---- VERSION INFO ----")
        print(((out.stdout or "") + (out.stderr or "")).strip()[:700] or "(empty)")
    except Exception as exc:
        print("VERSION_INFO_SKIPPED", exc)

    # 清理：onefile 的 exe 一次启动就有「引导器 + 主程序」两个进程，
    # 只 terminate Popen 句柄（引导器）会把主程序留成孤儿。
    # 先走产品自己的退出通道，再按镜像名兜底，确保不留进程。
    try:
        subprocess.run([str(EXE), "--quit"], cwd=str(workdir), env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.terminate()
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    time.sleep(2)
    left = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DesktopTime.exe", "/NH"],
                          capture_output=True, text=True, encoding="gbk",
                          errors="replace", timeout=20).stdout
    if "DesktopTime.exe" in left:
        subprocess.run(["taskkill", "/IM", "DesktopTime.exe", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        print("CLEANUP 强制结束残留进程")
    print("DONE")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(main())
