# -*- coding: utf-8 -*-
"""诊断：退出路径上是否弹出「Unhandled exception in script」对话框。

背景：用户点「退出软件」后弹 `AttributeError: 'NoneType' object has no attribute
'flush'`。console=False 的冻结产物里 sys.stdout / sys.stderr 都是 None，
`_hard_exit` 里的 `sys.stdout.flush()` 必然抛异常，且 except 只兜了
(OSError, ValueError)。

`verify_quit.py` 之前只断言「进程没了」，查不出这个 —— 除非把两条退出路径
（--quit 命令行 / 托盘退出）分别枚举窗口标题。本脚本就是那个尺子。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "DesktopTime.exe"

user32 = ctypes.windll.user32
BAD = ("unhandled exception", "traceback", "error")


def window_titles() -> list[str]:
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    out: list[str] = []

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                out.append(buf.value)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return out


def pids() -> list[str]:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq DesktopTime.exe", "/FO", "CSV", "/NH"],
            text=True, encoding="utf-8", errors="ignore", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    got = []
    for line in out.splitlines():
        if "desktoptime.exe" not in line.lower():
            continue
        parts = line.split('","')
        if len(parts) >= 2 and parts[1].strip().isdigit():
            got.append(parts[1].strip())
    return got


def main() -> int:
    if pids():
        print("先结束已在运行的实例")
        return 1
    appdata = Path(tempfile.gettempdir()) / "dt_quit_diag"
    if appdata.exists():
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(appdata)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    appdata.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for k in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(k, None)
    env["APPDATA"] = str(appdata)

    def launch(*a: str) -> subprocess.Popen:
        return subprocess.Popen([str(EXE), *a], cwd=str(appdata), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def launch_bare(*a: str) -> subprocess.Popen:
        """模拟资源管理器双击：无控制台、不继承任何标准句柄。

        用 stdout=DEVNULL 启动时子进程拿到的是有效的 NUL 句柄，PyInstaller
        会把 sys.stdout 建成正常流；只有彻底没有控制台时它才置 None ——
        这正是用户那条 traceback 的触发条件，用 DEVNULL 复现不出来。
        """
        DETACHED_PROCESS, CREATE_NO_WINDOW = 0x00000008, 0x08000000
        return subprocess.Popen([str(EXE), *a], cwd=str(appdata), env=env,
                                close_fds=True,
                                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)

    print("== 路径 A：命令行 --quit ==")
    first = launch()
    time.sleep(9)
    print("  首实例 pids", pids())
    q = launch("--quit")
    for t in (2, 4, 8):
        time.sleep(t if t == 2 else t - 2)
        bad = [s for s in window_titles() if any(b in s.lower() for b in BAD)]
        print(f"  t≈{t}s  quit进程 rc={q.poll()}  pids={pids()}  异常窗={bad}")
    if q.poll() is None:
        q.kill()
    left = [s for s in window_titles() if any(b in s.lower() for b in BAD)]
    print("  收尾异常窗", left)

    print("== 路径 B：托盘退出（发 quit 后再看首实例）==")
    # 首实例可能已被 A 路径关掉，重新起一个
    if not pids():
        first = launch()
        time.sleep(9)
    q2 = launch("--quit")
    try:
        q2.wait(timeout=12)
        print("  quit 进程退出码", q2.returncode)
    except subprocess.TimeoutExpired:
        print("  quit 进程 12s 未退出（疑似弹窗阻塞）")
        q2.kill()
    time.sleep(3)
    left = [s for s in window_titles() if any(b in s.lower() for b in BAD)]
    print("  事后异常窗", left, " 残留 pids", pids())
    for pid in pids():
        subprocess.run(["taskkill", "/F", "/PID", pid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("== 路径 C：无控制台启动（等价双击）+ 托盘退出 ==")
    if pids():
        for pid in pids():
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    bare = launch_bare()
    time.sleep(9)
    print("  首实例 pids", pids(), " rc=", bare.poll())
    q3 = launch("--quit")
    try:
        q3.wait(timeout=12)
        print("  quit 进程退出码", q3.returncode)
    except subprocess.TimeoutExpired:
        print("  quit 进程 12s 未退出（疑似弹窗阻塞）")
        q3.kill()
    time.sleep(4)
    left = [s for s in window_titles() if any(b in s.lower() for b in BAD)]
    print("  事后异常窗", left, " 残留 pids", pids(), " 首实例 rc=", bare.poll())
    for pid in pids():
        subprocess.run(["taskkill", "/F", "/PID", pid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
