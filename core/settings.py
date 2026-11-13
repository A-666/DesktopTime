# -*- coding: utf-8 -*-
"""DesktopTime 配置单一真源。

职责：默认值定义、缺项补齐、未知字段忽略、类型 / 范围 / 枚举校验。
不依赖任何 GUI 库，可独立测试。

约定：所有落盘坐标（offsetX / offsetY）为物理像素；position.margin 为逻辑像素。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

SCHEMA = "desktoptime.config/v1"
APP_VERSION = "1.1.0"

POSITION_PRESETS = (
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
)
STYLE_PRESETS = ("minimal", "lcd", "analog", "tech", "neon", "pop", "flip", "matrix",
                 "serif", "mono", "amber", "glitch", "caption", "float", "ink",
                 "ring", "frame", "dash", "twin", "thin")
CLOSE_ACTIONS = ("minimize", "exit", "ask")
TEXT_STYLES = ("bold", "italic", "underline", "outline", "shadow")

# 九宫格锚点显式映射。禁止用 preset.split("-") 猜锚点：
# top / left / right / bottom / center 都不含连字符，会被误判成居中。
PRESET_ANCHOR = {
    "top-left": ("left", "top"),
    "top": ("center", "top"),
    "top-right": ("right", "top"),
    "left": ("left", "middle"),
    "center": ("center", "middle"),
    "right": ("right", "middle"),
    "bottom-left": ("left", "bottom"),
    "bottom": ("center", "bottom"),
    "bottom-right": ("right", "bottom"),
}

DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "appVersion": APP_VERSION,
    "updatedAt": "",
    "name": "当前配置",
    "note": "",
    "display": {
        "index": 0,
        "all": False,
        "autoRefresh": True,
        "identifyOnSelect": True,
        "layout": [],
        # 03 / 04 页正在编辑哪一台显示器（序号 = display.index 同一套主键）
        "editIndex": 0,
    },
    "time": {
        "format": "HH:mm:ss",
        "custom": "",
        "showDate": False,
        "showWeekday": False,
        "showSeconds": True,
        "hour12": False,
    },
    "style": {
        "preset": "minimal",
        "font": "Consolas",
        "size": 60,
        "weight": "Medium",
        "color": "#1F2328",
        "textStyles": [],
        "recentColors": [],
        "opacity": 1.0,
        "background": {"enabled": False, "color": "#FFFFFF", "padding": 12},
        "packRef": "",
        "decorations": [],
        "effects": [],
        "packVersion": "desktoptime.style/v1",
    },
    "position": {
        # 九宫格锚点：**永久固定**，永远相对于桌面，不吃任何偏移量
        "preset": "top-right",
        # preset = 严格按锚点摆放；custom = 用 custom.x/y 的自由落点
        "mode": "preset",
        # 自定义落点：逻辑像素，相对「该显示器工作区左上角」
        "custom": {"x": 0, "y": 0},
        "margin": 24,
        "dragEnabled": True,
        "snapGuides": True,
        "lockPosition": False,
    },
    "app": {"autoStart": False},
    "tray": {"enabled": True, "onClose": "ask"},
    "window": {"alwaysOnTop": False, "clickThrough": True, "autoRelocate": True},
    # 每台显示器的独立样式 / 位置：{"<index>": {"style": {...}, "position": {...}}}
    # 只在该屏被单独设置过之后才有键；没有键 = 跟随上面这份全局配置。
    "perMonitor": {},
}

# perMonitor 里允许出现的字段（其余全局项如时间格式、窗口行为仍然全局共享）
MONITOR_SECTIONS = ("style", "position")
MAX_MONITORS = 16

# (min, max, fallback)
LIMITS: dict[str, tuple[float, float, float]] = {
    "style.size": (12, 200, 48),
    "style.opacity": (0.2, 1.0, 1.0),
    "position.margin": (0, 200, 24),
    "position.custom.x": (-20000, 20000, 0),
    "position.custom.y": (-20000, 20000, 0),
    "display.index": (0, 15, 0),
    "style.background.padding": (0, 120, 12),
}

ENUMS: dict[str, tuple[str, ...]] = {
    "style.preset": STYLE_PRESETS,
    "position.preset": POSITION_PRESETS,
    "position.mode": ("preset", "custom"),
    "tray.onClose": CLOSE_ACTIONS,
}


def now_iso() -> str:
    """本地时间 ISO 8601，带时区偏移。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def defaults() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def _merge(dv: Any, rv: Any, path: str, warnings: list[str]) -> Any:
    if isinstance(dv, dict):
        if not isinstance(rv, dict):
            if rv is not None:
                warnings.append(f"{path}: 期望 object，已补默认值")
            return copy.deepcopy(dv)
        out: dict[str, Any] = {}
        for k, sub in dv.items():
            out[k] = _merge(sub, rv[k], f"{path}.{k}", warnings) if k in rv else copy.deepcopy(sub)
        # 未知字段一律忽略
        return out
    if isinstance(dv, list):
        if not isinstance(rv, list):
            warnings.append(f"{path}: 期望 array，已补默认值")
            return copy.deepcopy(dv)
        return list(rv)[:32]
    if isinstance(dv, bool):
        if not isinstance(rv, bool):
            warnings.append(f"{path}: 期望 bool，已补默认值")
            return dv
        return rv
    if isinstance(dv, int):
        if isinstance(rv, bool) or not isinstance(rv, int):
            warnings.append(f"{path}: 期望 int，已补默认值")
            return dv
        return rv
    if isinstance(dv, float):
        if isinstance(rv, bool) or not isinstance(rv, (int, float)):
            warnings.append(f"{path}: 期望 number，已补默认值")
            return dv
        return float(rv)
    if isinstance(dv, str):
        if not isinstance(rv, str):
            warnings.append(f"{path}: 期望 string，已补默认值")
            return dv
        return rv
    return copy.deepcopy(dv)


def clamp(data: dict[str, Any]) -> list[str]:
    """范围 / 枚举 / 颜色 / 列表长度归一。返回告警列表。"""
    warnings: list[str] = []

    for path, (lo, hi, fb) in LIMITS.items():
        node, key = _parent(data, path)
        if node is None:
            continue
        val = node.get(key, fb)
        try:
            num = float(val)
        except (TypeError, ValueError):
            num = float(fb)
            warnings.append(f"{path}: 非数值，回落 {fb}")
        if not (lo <= num <= hi):
            num = min(hi, max(lo, num))
            warnings.append(f"{path}: 超出 [{lo},{hi}]，已钳制为 {num}")
        node[key] = int(num) if isinstance(fb, int) else round(num, 2)

    for path, allowed in ENUMS.items():
        node, key = _parent(data, path)
        if node is None:
            continue
        if node.get(key) not in allowed:
            warnings.append(f"{path}: 非法枚举 {node.get(key)!r}，回落 {allowed[0]}")
            node[key] = allowed[0]

    st = data.get("style", {})
    # 颜色必须是 #RRGGBB
    for key in ("color",):
        v = st.get(key, "")
        if not _is_hex(v):
            warnings.append(f"style.{key}: 非法颜色，回落 #1F2328")
            st[key] = "#1F2328"
    bg = st.get("background", {})
    if isinstance(bg, dict) and not _is_hex(bg.get("color", "")):
        bg["color"] = "#FFFFFF"

    st["textStyles"] = [x for x in st.get("textStyles", []) if x in TEXT_STYLES][:len(TEXT_STYLES)]
    seen: list[str] = []
    for c in st.get("recentColors", [])[:16]:
        if _is_hex(c) and c not in seen:
            seen.append(c)
    st["recentColors"] = seen[:4]
    st["decorations"] = list(st.get("decorations", []))[:8]
    st["effects"] = list(st.get("effects", []))[:4]
    data["display"]["layout"] = list(data.get("display", {}).get("layout", []))[:16]
    return warnings


def clamp_scope(style: dict, position: dict) -> list[str]:
    """只校验 style / position 两块（perMonitor 的条目用）。

    直接复用主 clamp：临时拼一个「最小完整配置」给它，规则就永远只有一份，
    不会出现「全局改了范围、每屏配置没跟上」的漂移。
    """
    ctx = {"style": style, "position": position, "display": {"layout": []}}
    return clamp(ctx)


def normalize_monitor_entry(entry: Any, path: str = "perMonitor") -> tuple[dict | None, list[str]]:
    """把「某台显示器的一份覆盖配置」收敛成完整的 style + position。"""
    if not isinstance(entry, dict):
        return None, [f"{path}: 期望 object，已丢弃"]
    warnings: list[str] = []
    merged = _merge({"style": copy.deepcopy(DEFAULTS["style"]),
                     "position": copy.deepcopy(DEFAULTS["position"])},
                    entry, path, warnings)
    warnings.extend(clamp_scope(merged["style"], merged["position"]))
    return {"style": merged["style"], "position": merged["position"]}, warnings


def normalize_per_monitor(raw: Any, warnings: list[str]) -> dict[str, dict]:
    """键 = 显示器序号（与 01 页序号一致，就是唯一主键），值 = 该屏的覆盖配置。"""
    out: dict[str, dict] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        warnings.append("perMonitor: 期望 object，已清空")
        return out
    for key, entry in raw.items():
        try:
            idx = int(str(key))
        except (TypeError, ValueError):
            warnings.append(f"perMonitor.{key}: 键不是显示器序号，已忽略")
            continue
        if not (0 <= idx < MAX_MONITORS):
            warnings.append(f"perMonitor.{key}: 序号越界，已忽略")
            continue
        normalized, warns = normalize_monitor_entry(entry, f"perMonitor.{idx}")
        warnings.extend(warns)
        if normalized is not None:
            out[str(idx)] = normalized
    return out


def _is_hex(v: Any) -> bool:
    if not isinstance(v, str) or not v.startswith("#") or len(v) != 7:
        return False
    try:
        int(v[1:], 16)
        return True
    except ValueError:
        return False


def _parent(data: dict, path: str):
    parts = path.split(".")
    node: Any = data
    for p in parts[:-1]:
        if not isinstance(node, dict):
            return None, None
        node = node.get(p)
    return (node, parts[-1]) if isinstance(node, dict) else (None, None)


def coerce(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """把任意输入（含损坏 / 旧版 / 残缺 JSON）收敛成完整配置。"""
    warnings: list[str] = []
    # perMonitor 的键是动态的，_merge 会按 DEFAULTS 的固定键「未知字段一律忽略」，
    # 所以先摘出来单独归一，再塞回去。
    per_raw: Any = None
    if isinstance(raw, dict) and "perMonitor" in raw:
        raw = dict(raw)
        per_raw = raw.pop("perMonitor")
    data = _merge(DEFAULTS, raw, "", warnings)
    data["schema"] = SCHEMA
    data["appVersion"] = APP_VERSION
    if not data.get("updatedAt"):
        data["updatedAt"] = now_iso()
    data["perMonitor"] = normalize_per_monitor(per_raw, warnings)
    warnings.extend(clamp(data))
    return data, warnings


class Settings:
    """内存中的唯一真源。所有页面不得持有自己的配置副本。"""

    def __init__(self, data: Any = None):
        self.data, self.warnings = coerce(data)

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, path: str, value: Any) -> None:
        keys = path.split(".")
        node: Any = self.data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        clamp(self.data)
        self.data["updatedAt"] = now_iso()

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    def replace(self, raw: Any) -> list[str]:
        self.data, self.warnings = coerce(raw)
        return self.warnings
