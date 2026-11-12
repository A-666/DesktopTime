# -*- coding: utf-8 -*-
"""冻结 exe 退出自检：单实例唯一 + 退出后不留进程。

背景：用户报「退了软件以后进程还在」，任务管理器里还挂着两个 DesktopTime.exe。
两个进程本身是 onefile 引导器 + 主程序（单次启动的正常形态），
真正的问题是主进程退出时没有结束干净。本脚本用独立 APPDATA 跑，不碰用户配置。

断言四件事：
1. 首次启动后 exe 进程存在；
2. 再点一次启动（不带参数）会在数秒内自己退出，且首实例还活着 —— 不会出现第二套时间；
3. 发 --quit 后，所有 DesktopTime.exe 进程在 10 秒内全部消失；
4. 全程不出现「Unhandled exception in script」弹窗，且首实例自己退出（不是被 kill）。

第 4 条是补的：用户双击启动后点「退出软件」会弹 `AttributeError: 'NoneType'
object has no attribute 'flush'`。原因是 console=False 且**没有控制台**启动时
sys.stdout 是 None。旧脚本用 stdout=DEVNULL 启动，子进程拿到了有效的 NUL 句柄，
sys.stdout 不是 None，于是永远复现不出来；而且只断言「进程没了」，弹窗（阻塞式，
用户不点关闭进程就不死）也查不出来。现在一律用 DETACHED_PROCESS 启动，等价双击。
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
IMAGE = "DesktopTime.exe"
BAD_TITLES = ("unhandled exception", "traceback")

user32 = ctypes.windll.user32


def bad_windows() -> list[str]:
    """枚举可见窗口，挑出「Python 异常弹窗」那一类标题。"""
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[str] = []

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                low = buf.value.lower()
                if any(b in low for b in BAD_TITLES):
                    found.append(buf.value)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found


def exe_pids() -> list[str]:
    """用 tasklist 数真实进程，不依赖 psutil。

    tasklist CSV 形如 "DesktopTime.exe","1234","Console","1","44,732 K"，
    按 '","' 切开后 field0 是 "DesktopTime.exe（带前引号），field1 是 pid。
    """
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {IMAGE}", "/FO", "CSV", "/NH"],
            text=True, encoding="utf-8", errors="ignore", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[str] = []
    for line in out.splitlines():
        if IMAGE.lower() not in line.lower():
            continue
        parts = line.split('","')
        if len(parts) >= 2 and parts[1].strip().isdigit():
            pids.append(parts[1].strip())
    return pids


def wait_until(pred, timeout: float, step: float = 0.4) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


def main() -> int:
    if not EXE.is_file():
        print(f"FAIL 未找到 {EXE}")
        return 1
    if exe_pids():
        print("FAIL 打包前请先结束已在运行的实例（否则测的是旧进程）")
        return 1

    appdata = Path(tempfile.gettempdir()) / "dt_quit_check"
    if appdata.exists():
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(appdata)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    appdata.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(key, None)
    env["APPDATA"] = str(appdata)

    def launch(*args: str) -> subprocess.Popen:
        # DETACHED_PROCESS | CREATE_NO_WINDOW = 完全不给控制台，等价双击。
        # 若这里改成 stdout=DEVNULL，sys.stdout 会变成有效流，就测不出弹窗了。
        return subprocess.Popen([str(EXE), *args], cwd=str(appdata), env=env,
                                close_fds=True,
                                creationflags=0x00000008 | 0x08000000)

    first = launch()
    ok_start = wait_until(lambda: len(exe_pids()) >= 1, 25)
    print(f"首实例启动 {ok_start}，进程 {exe_pids()}")
    if not ok_start:
        print("RESULT FAIL (启动失败)")
        return 1
    time.sleep(4)   # 等托盘与时间窗口就绪

    # 2) 重复启动必须自己退出，不能留下第二个实例
    second = launch()
    try:
        rc2 = second.wait(timeout=20)
        print(f"第二次启动已在 {rc2=} 内退出（无第二套窗口）")
        no_dup = True
    except subprocess.TimeoutExpired:
        second.kill()
        print("第二次启动 20s 内没有退出 —— 单实例失效")
        no_dup = False

    # 3) 指令退出，所有进程必须消失
    quit_proc = launch("--quit")
    try:
        quit_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        quit_proc.kill()
    gone = wait_until(lambda: not exe_pids(), 10)
    alive = exe_pids()
    print(f"退出后残留进程 {alive if alive else '无'}")
    dialogs = bad_windows()
    print(f"异常弹窗 {dialogs if dialogs else '无'}")
    first_rc = first.poll()
    print(f"首实例退出码 {first_rc}")
    first_alive = first_rc is None
    if first_alive:
        first.kill()

    log = appdata / "DesktopTime" / "logs" / "desktoptime.log"
    if log.is_file():
        tail = [ln for ln in log.read_text(encoding="utf-8", errors="ignore").splitlines()
                if "退出" in ln or "已有实例" in ln or "事件循环" in ln][-8:]
        print("--- 日志 ---")
        print("\n".join(tail))

    clean_exit = (first_rc == 0) and not dialogs
    if not clean_exit:
        print("  ↑ 退出必须是 0 且无弹窗：非 0 或出现弹窗都说明退出路径上有异常")
    ok = ok_start and no_dup and gone and not first_alive and clean_exit
    print(f"RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
