# -*- coding: utf-8 -*-
"""Qt 逻辑坐标系 ↔ Win32 物理坐标系 的显示器映射。

实测根因（2026-11-11，双屏 1920×1080 @100% + 1920×1080 @150%）
----------------------------------------------------------------
ctypes EnumDisplayMonitors / GetMonitorInfoW（物理像素）
    #0 work=(0,0)-(1920,1032)  scale=1.0  primary
    #1 work=(1920,0)-(3840,1008) scale=1.5
QScreen.availableGeometry()（Qt 逻辑 DIP）
    #0 avail=(0,0,1920,1032)     dpr=1.0
    #1 avail=(1920,0,1280,672)   dpr=1.5
QWidget.move() 只收逻辑坐标，Qt 再按目标屏 dpr 映射到物理：
    physical = geom.left + (logical - geom.left) * dpr
旧实现把 compute_origin() 的物理结果 (2764, 466) 直接给 move()，
Qt 解释成 (1920 + 844*1.5, 466*1.5) = (3186, 699)，偏 (422, 233)，
窗口 231×76 也被放大成 347×114 —— 这就是「居中选择后没有居中」。

修复：本模块把 ctypes 的 Monitor 逐块匹配到 QScreen，输出 Qt 逻辑工作区
与 dpr；所有九宫格、偏移、钳制、拖动一律在逻辑坐标系完成，不再混用。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QGuiApplication

from core import store
from core.monitors import anchor_origin, clamp_to_screen, monitor_at


@dataclass
class ScreenInfo:
    index: int                          # 对应 ctypes Monitor.index
    work: tuple[int, int, int, int]     # Qt 逻辑工作区 (l, t, r, b)
    dpr: float                          # devicePixelRatio
    name: str


class ScreenMap:
    """一次枚举的 Qt 逻辑屏幕视图；按 index 与 controller.monitors 对齐。"""

    def __init__(self, infos: list[ScreenInfo], fallback: bool = False):
        self.infos = infos
        self.fallback = fallback
        self.rects = [i.work for i in infos]
        self.scales = [1.0] * len(infos)                 # margin 落盘即逻辑像素
        self.divisors = [i.dpr or 1.0 for i in infos]   # 物理偏移 ÷ dpr → 逻辑

    def dpr(self, index: int) -> float:
        if not self.infos:
            return 1.0
        i = max(0, min(int(index), len(self.infos) - 1))
        return self.infos[i].dpr or 1.0

    def origin(self, cfg: dict, w: int, h: int, index: int | None = None) -> tuple[int, int]:
        return anchor_origin(cfg, self.rects, self.scales, w, h, index, self.divisors)

    def clamp(self, x: int, y: int, w: int, h: int, monitors) -> tuple[int, int]:
        return clamp_to_screen(x, y, w, h, monitors, self.rects)

    def which(self, x: int, y: int, monitors) -> int:
        return monitor_at(x, y, monitors, self.rects)


def _fallback(monitors) -> ScreenMap:
    """无 QGuiApplication / Qt 未就绪时的降级：单屏 100% 下与物理坐标等价。"""
    infos = [ScreenInfo(m.index,
                        (int(m.wl / m.scale), int(m.wt / m.scale),
                         int(m.wr / m.scale), int(m.wb / m.scale)),
                        m.scale, m.name) for m in monitors]
    store.log("Qt 屏幕映射不可用，已降级为物理/缩放近似换算", "WARN")
    return ScreenMap(infos, fallback=True)


def build_screen_map(monitors) -> ScreenMap:
    """把 QScreen 按「dpr + 物理尺寸 + 主屏标记」最小代价匹配到 ctypes Monitor。

    不依赖 screen.name()：Qt 在 Windows 上返回的是显示器友好名（如 "HDMI"），
    而 ctypes 的 szDevice 是 "\\\\.\\DISPLAY1"，两者无法直接比对。
    """
    app = QGuiApplication.instance()
    if app is None or not monitors:
        return _fallback(monitors)
    screens = list(QGuiApplication.screens())
    if not screens:
        return _fallback(monitors)

    primary = QGuiApplication.primaryScreen()
    costs: list[tuple[float, int, int]] = []
    for i, m in enumerate(monitors):
        for j, s in enumerate(screens):
            dpr = float(s.devicePixelRatio()) or 1.0
            g = s.geometry()
            # QScreen.geometry() 为逻辑尺寸，乘 dpr 才是物理尺寸
            pw, ph = round(g.width() * dpr), round(g.height() * dpr)
            cost = (abs(dpr - m.scale) * 10000      # 缩放倍率是最强判据
                    + abs(pw - m.width) + abs(ph - m.height))
            if (s is primary) != bool(m.primary):
                cost += 40
            costs.append((cost, i, j))

    pair: dict[int, int] = {}
    used: set[int] = set()
    for _cost, i, j in sorted(costs):
        if i in pair or j in used:
            continue
        pair[i], used = j, used | {j}

    # 热插拔瞬间 Qt 与 ctypes 屏数可能短暂不一致：缺失项退回物理换算
    infos: list[ScreenInfo] = []
    for i, m in enumerate(monitors):
        j = pair.get(i)
        if j is None:
            infos.append(ScreenInfo(m.index,
                                    (int(m.wl / m.scale), int(m.wt / m.scale),
                                     int(m.wr / m.scale), int(m.wb / m.scale)),
                                    m.scale, m.name))
            continue
        s = screens[j]
        a = s.availableGeometry()
        infos.append(ScreenInfo(m.index,
                                (a.x(), a.y(), a.x() + a.width(), a.y() + a.height()),
                                float(s.devicePixelRatio()) or 1.0, s.name()))
    if len(screens) != len(monitors):
        store.log(f"屏幕数不一致 ctypes={len(monitors)} Qt={len(screens)}，已按最优配对", "WARN")
    return ScreenMap(infos)
