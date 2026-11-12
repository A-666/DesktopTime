# -*- coding: utf-8 -*-
"""冻结 exe 端到端落点验证（不修改用户任何配置）。

读取当前 settings.json，启动 dist/DesktopTime.exe，枚举它真实创建的
Qt 时间窗口 HWND，用 Win32 GetWindowRect 量物理落点，与 ctypes 物理工作区
独立推算的期望值比较。这是「打包产物」层面的像素级验证，而非源码层。

★ 必须跑在**沙箱 APPDATA** 里：产品启动会回写 settings.json（迁移、自动重定位），
  直接在真实 %APPDATA% 上跑会把用户正在用的样式/位置改掉（已踩过）。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXE = ROOT / "dist" / "DesktopTime.exe"

# 沙箱：exe 的 APPDATA 指到这里，用户的 %APPDATA%\DesktopTime 全程不被读写
SANDBOX = Path(os.environ.get("TEMP", ".")) / "dt_exe_pos" / "appdata"
CFG = SANDBOX / "DesktopTime" / "settings.json"

from core.monitors import enum_monitors, set_dpi_awareness  # noqa: E402

# ★ 本进程也必须是 PER_MONITOR_AWARE_V2，否则 GetWindowRect / EnumDisplayMonitors
#   返回的是 DPI 虚拟化后的逻辑坐标，量出来的物理落点是错的。
print("DPI", set_dpi_awareness())
user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def qt_tool_windows() -> list[tuple[int, int, int, int]]:
    """DesktopTime 的时间窗口：Qt Tool 窗、标题 "DesktopTime"。

    实测类名 Qt6111QWindowToolSaveBits；不能用「无标题」筛选，
    因为 Qt 给这个 Tool 窗带了标题，而设置窗标题是 "DesktopTime · 设置"。
    """
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[tuple[int, int, int, int]] = []

    def cb(hwnd, _lp):
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), cls, 128)
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), title, 256)
        if (cls.value.startswith("Qt") and title.value == "DesktopTime"
                and user32.IsWindowVisible(hwnd)):
            r = RECT()
            user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if 40 < w < 900 and 20 < h < 400:   # 排除 ThemeChangeObserver 等辅助窗
                found.append((r.left, r.top, w, h))
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found


def seed_sandbox() -> None:
    """准备沙箱配置：优先抄一份用户当下的真实配置（最贴近实机），没有就用出厂值。"""
    CFG.parent.mkdir(parents=True, exist_ok=True)
    if CFG.exists():
        return
    real = Path(os.environ.get("APPDATA", ".")) / "DesktopTime" / "settings.json"
    if real.exists():
        shutil.copyfile(real, CFG)
        return
    from core import settings as st
    CFG.write_text(json.dumps(st.defaults(), ensure_ascii=False, indent=2),
                   encoding="utf-8")


CUSTOM_CASE = "--custom"
CUSTOM_POINT = {"x": 300, "y": 120}     # 逻辑像素，相对目标屏工作区左上角


def main() -> int:
    seed_sandbox()
    # 两条用例各自把 mode 钉死：用户真实配置里 mode 可能是 custom，
    # 直接 seed 过来会让默认用例也跑 custom 分支，预设模式等于没测。
    raw = json.loads(CFG.read_text(encoding="utf-8"))
    if CUSTOM_CASE in sys.argv:
        # 自定义落点用例：模式切 custom，锚点保持不动（验证两者互不干扰）
        raw["position"]["mode"] = "custom"
        raw["position"]["custom"] = dict(CUSTOM_POINT)
    else:
        # 预设用例：强制 preset，锚点用真实配置里的值
        raw["position"]["mode"] = "preset"
    CFG.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    mons = enum_monitors()
    idx = max(0, min(int(cfg["display"]["index"]), len(mons) - 1))
    m = mons[idx]
    pos = cfg["position"]
    preset = pos["preset"]
    mode = str(pos.get("mode", "preset"))
    pad = pos["margin"] * m.scale
    print(f"配置：屏 #{idx} scale={m.scale} work=({m.wl},{m.wt})-({m.wr},{m.wb}) "
          f"mode={mode} preset={preset} margin={pos['margin']} custom={pos.get('custom')}")

    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
        env.pop(key, None)
    env["APPDATA"] = str(SANDBOX)          # ★ 隔离用户真实配置
    workdir = Path(os.environ.get("TEMP", ".")) / "dt_exe_pos"
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(EXE)], cwd=str(workdir), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        wins = qt_tool_windows()
        print("时间窗口物理矩形", wins)
        if not wins:
            print("RESULT FAIL (未找到时间窗口)")
            return 1
        x, y, w, h = wins[0]
        # 独立 oracle：只用 ctypes 物理工作区，不调用产品定位代码。
        # custom 落点是「相对该屏工作区左上角的逻辑像素」，物理换算 ×scale。
        if mode == "custom":
            cus = pos.get("custom") or {}
            want_x = m.wl + int(cus.get("x", 0)) * m.scale
            want_y = m.wt + int(cus.get("y", 0)) * m.scale
        elif preset == "center":
            want_x = (m.wl + m.wr) / 2 - w / 2
            want_y = (m.wt + m.wb) / 2 - h / 2
        else:
            cx = "left" if preset.startswith("left") or preset.endswith("left") else "right"
            cy = "top" if preset.startswith("top") or preset.endswith("top") else "bottom"
            want_x = m.wl + pad if cx == "left" else m.wr - w - pad
            want_y = m.wt + pad if cy == "top" else m.wb - h - pad
        dx, dy = x - want_x, y - want_y
        ok = abs(dx) <= 2 and abs(dy) <= 2
        print(f"实际物理落点 = ({x},{y}) {w}×{h}")
        print(f"期望物理落点 = ({want_x:.1f},{want_y:.1f})  偏差 = ({dx:+.1f},{dy:+.1f})")
        print(f"RESULT {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        # 先让产品自己退出（会带走引导器与主程序两个进程），再兜底清理。
        # 只 terminate Popen 句柄等于只杀引导器，主程序会变成孤儿留在任务管理器里。
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
        time.sleep(2)
        left = subprocess.run(["tasklist", "/FI", "IMAGENAME eq DesktopTime.exe", "/NH"],
                              capture_output=True, text=True, encoding="gbk",
                              errors="replace", timeout=20).stdout
        if "DesktopTime.exe" in left:
            subprocess.run(["taskkill", "/IM", "DesktopTime.exe", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            print("CLEANUP 强制结束残留进程")


if __name__ == "__main__":
    sys.exit(main())
