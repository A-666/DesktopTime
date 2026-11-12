# -*- coding: utf-8 -*-
"""抓取「打包后 exe」的设置窗口，验证冻结环境下 QSS 贴图 / 配色 / 图标真的生效。

Win32 抓屏踩坑（务必保留）：GetDIBits 用负高度 biHeight 取 top-down DIB，
buffer 首行就是图像顶行，PIL.frombuffer 必须 orientation=1 且不做 FLIP_TOP_BOTTOM，
否则整张图会上下颠倒。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXE = ROOT / "dist" / "DesktopTime.exe"
OUT = Path(os.environ.get("TEMP", ".")) / "dt_ui" / "exe_settings.png"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def find_window(title: str) -> int:
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = []

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if title in buf.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found[0] if found else 0


def grab(hwnd: int):
    r = RECT()
    user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(ctypes.c_void_p(hwnd))
    mem = gdi32.CreateCompatibleDC(ctypes.c_void_p(hdc))
    bmp = gdi32.CreateCompatibleBitmap(ctypes.c_void_p(hdc), w, h)
    gdi32.SelectObject(ctypes.c_void_p(mem), ctypes.c_void_p(bmp))
    user32.PrintWindow(ctypes.c_void_p(hwnd), ctypes.c_void_p(mem), 2)

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h          # top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(ctypes.c_void_p(mem), ctypes.c_void_p(bmp), 0, h,
                    buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(ctypes.c_void_p(bmp))
    gdi32.DeleteDC(ctypes.c_void_p(mem))
    user32.ReleaseDC(ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc))

    from PIL import Image
    # 负高度 top-down：首行即顶行，禁止再做上下翻转
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)


def main() -> int:
    if not EXE.is_file():
        print("EXE_MISSING")
        return 1
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(key, None)
    # ★ 沙箱 APPDATA：截图会切预设/改字号，不能落在用户真实配置上
    sandbox = Path(os.environ.get("TEMP", ".")) / "dt_exe_capture" / "appdata"
    sandbox.mkdir(parents=True, exist_ok=True)
    env["APPDATA"] = str(sandbox)
    workdir = Path(os.environ.get("TEMP", ".")) / "dt_exe_capture"
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(EXE)], cwd=str(workdir), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(7)
        # 唤醒已运行的实例，弹出设置窗口
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket
        sys.path.insert(0, str(ROOT))
        from core.single_instance import SOCKET_NAME   # 单一来源，避免改名后静默失效
        app = QCoreApplication([])
        sock = QLocalSocket()
        sock.connectToServer(SOCKET_NAME)
        if sock.waitForConnected(1200):
            sock.write(b"raise")
            sock.flush()
            sock.waitForBytesWritten(1200)
            sock.disconnectFromServer()
        time.sleep(2)
        hwnd = find_window("DesktopTime · 设置")
        print("HWND", hwnd)
        if not hwnd:
            return 1
        user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        time.sleep(1)
        img = grab(hwnd)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(OUT)
        print("SAVED", OUT, img.size)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
