# -*- coding: utf-8 -*-
"""多显示器枚举、DPI 与坐标换算（纯 ctypes，零第三方依赖）。

约定：rcWork 是工作区（排除任务栏），落盘 offsetX / offsetY 为物理像素。

★ 坐标系铁律（2026-11-11 双屏 100% + 150% 实测修复）
  ctypes EnumDisplayMonitors 返回「物理像素」；QWidget.move() 收「Qt 逻辑 DIP」。
  两者只在 100% 屏上相等。混合 DPI 下把物理坐标直接给 move()，Qt 会按目标屏
  dpr 再映射一次，实测 150% 屏居中落点偏 (422, 233)，窗口尺寸也被放大 1.5 倍。
  因此：
    - 本模块保留物理坐标系的 compute_origin（供测试、缩略图、热插拔签名）；
    - 另提供 anchor_origin()，由调用方传入目标坐标系的工作区矩形；
    - UI 层统一改用 Qt 逻辑工作区（见 ui/screens.py）计算再 move()。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

user32 = ctypes.windll.user32
try:
    shcore = ctypes.windll.shcore
except AttributeError:  # pragma: no cover - 极旧系统
    shcore = None

MDT_EFFECTIVE_DPI = 0
MONITORINFOF_PRIMARY = 1
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), wintypes.LPARAM
)

user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
if shcore is not None:
    shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    shcore.GetDpiForMonitor.restype = ctypes.c_long


def set_dpi_awareness() -> str:
    """必须在 QApplication 构造之前调用，且两种 API 只能选一个。"""
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "PER_MONITOR_AWARE_V2"
    except (AttributeError, OSError, ValueError, ctypes.ArgumentError):
        pass
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)
            return "PER_MONITOR_DPI_AWARE"
    except (AttributeError, OSError, ctypes.ArgumentError):
        pass
    return "NONE"


@dataclass
class Monitor:
    index: int
    name: str
    left: int
    top: int
    right: int
    bottom: int
    wl: int
    wt: int
    wr: int
    wb: int
    dpi: int
    primary: bool

    @property
    def scale(self) -> float:
        return self.dpi / 96.0

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def work_width(self) -> int:
        return self.wr - self.wl

    @property
    def work_height(self) -> int:
        return self.wb - self.wt

    @property
    def label(self) -> str:
        return f"{self.work_width} × {self.work_height}  ·  {int(round(self.scale * 100))}%"

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "name": self.name, "primary": self.primary,
            "rect": [self.left, self.top, self.right, self.bottom],
            "work": [self.wl, self.wt, self.wr, self.wb], "dpi": self.dpi,
        }


def enum_monitors() -> list[Monitor]:
    rows: list[dict[str, Any]] = []

    def cb(hmon, _hdc, _lprc, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        handle = ctypes.c_void_p(hmon)
        if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return 1
        dx, dy = ctypes.c_uint(96), ctypes.c_uint(96)
        if shcore is not None:
            try:
                shcore.GetDpiForMonitor(handle, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy))
            except OSError:
                pass
        rows.append({
            "name": info.szDevice,
            "left": info.rcMonitor.left, "top": info.rcMonitor.top,
            "right": info.rcMonitor.right, "bottom": info.rcMonitor.bottom,
            "wl": info.rcWork.left, "wt": info.rcWork.top,
            "wr": info.rcWork.right, "wb": info.rcWork.bottom,
            "dpi": int(dx.value) or 96,
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        })
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    rows.sort(key=lambda r: (r["wl"], r["wt"]))
    return [Monitor(index=i, **r) for i, r in enumerate(rows)]


def physical_rects(monitors: list[Monitor]) -> list[tuple[int, int, int, int]]:
    """ctypes 物理工作区 (l, t, r, b)。"""
    return [(m.wl, m.wt, m.wr, m.wb) for m in monitors]


def anchor_origin(cfg: dict, rects: list[tuple[int, int, int, int]],
                  scales: list[float], clock_w: int, clock_h: int,
                  index: int | None = None,
                  offset_divisors: list[float] | None = None) -> tuple[int, int]:
    """九宫格锚点 / 自定义落点 → 调用方指定坐标系的落点。坐标系无关。

    rects[i]            (l, t, r, b)：第 i 块屏在该坐标系下的工作区
    scales[i]           margin 与自定义落点的倍率：物理坐标系传 dpr，Qt 逻辑坐标系传 1.0
                        （margin 落盘为逻辑像素，物理坐标系需乘 dpr 才是物理距离）
    offset_divisors[i]  兼容旧签名保留；新模型不再有偏移量
    clock_w / clock_h   时间窗口在该坐标系下的实际尺寸（含文字 + 装饰留白）

    两条定位路径互斥：
      mode = "preset"  → 严格按九宫格锚点摆放，**永远不吃偏移量**（预设位置永久不变）
      mode = "custom"  → 用 position.custom 的绝对落点（逻辑像素，相对屏幕工作区左上角）
    """
    from .settings import PRESET_ANCHOR

    if not rects:
        return (0, 0)
    idx = cfg["display"]["index"] if index is None else index
    idx = max(0, min(int(idx), len(rects) - 1))
    l, t, r, b = rects[idx]
    s = scales[idx] if idx < len(scales) else 1.0
    pos = cfg["position"]

    if str(pos.get("mode", "preset")) == "custom":
        cus = pos.get("custom") or {}
        try:
            cx = int(cus.get("x", 0))
            cy = int(cus.get("y", 0))
        except (TypeError, ValueError):
            cx = cy = 0
        return (l + int(cx * s), t + int(cy * s))

    cx, cy = PRESET_ANCHOR.get(pos["preset"], ("center", "middle"))
    px = {"left": l, "center": (l + r - clock_w) // 2, "right": r - clock_w}[cx]
    py = {"top": t, "middle": (t + b - clock_h) // 2, "bottom": b - clock_h}[cy]
    mx = {"left": 1, "center": 0, "right": -1}[cx]
    my = {"top": 1, "middle": 0, "bottom": -1}[cy]
    return (px + mx * int(pos["margin"] * s), py + my * int(pos["margin"] * s))


def compute_origin(cfg: dict, monitors: list[Monitor], clock_w: int, clock_h: int,
                   index: int | None = None) -> tuple[int, int]:
    """九宫格 + 自定义偏移 → 虚拟桌面「物理像素」坐标。

    保留给单元测试、显示器缩略图、热插拔签名。
    真实窗口定位请勿使用本函数，改用 anchor_origin + Qt 逻辑工作区。
    """
    return anchor_origin(cfg, physical_rects(monitors), [m.scale for m in monitors],
                         clock_w, clock_h, index)


def clamp_to_screen(x: int, y: int, w: int, h: int,
                    monitors: list[Monitor],
                    rects: list[tuple[int, int, int, int]] | None = None) -> tuple[int, int]:
    """把窗口左上角钳制在虚拟桌面内。rects 可指定为 Qt 逻辑工作区。"""
    rs = physical_rects(monitors) if rects is None else rects
    if not rs:
        return (x, y)
    l = min(r[0] for r in rs)
    t = min(r[1] for r in rs)
    r = max(r[2] for r in rs)
    b = max(r[3] for r in rs)
    return (max(l, min(x, r - w)), max(t, min(y, b - h)))


def monitor_at(x: int, y: int, monitors: list[Monitor],
               rects: list[tuple[int, int, int, int]] | None = None) -> int:
    """点 (x, y) 落在哪块屏。rects 可指定为 Qt 逻辑工作区。"""
    rs = physical_rects(monitors) if rects is None else rects
    for i, (l, t, r, b) in enumerate(rs):
        if l <= x < r and t <= y < b:
            return i
    primary = next((m for m in monitors if m.primary), None)
    return primary.index if primary else 0
