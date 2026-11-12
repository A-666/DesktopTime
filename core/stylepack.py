# -*- coding: utf-8 -*-
""".dtstyle 开放样式接口：解析、校验、参数钳制、数量截断、失败回落。

纯数据格式：不执行脚本、不解析表达式、不加载远程 URL、不加载外部字体。
渲染层注册顺序：stack → text → outline → shadow / glow → backdrop → ring → border → effects
（实际绘制时 backdrop 作为底层先画，避免盖住文字；见 renderer.py 说明）
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SCHEMA = "desktoptime.style/v1"
MAX_DECORATIONS = 8
MAX_EFFECTS = 4
MAX_PACK_BYTES = 256 * 1024

DECORATION_TYPES = ("border", "outline", "glow", "shadow", "backdrop", "divider",
                    "ring", "stack", "bracket")
EFFECT_TYPES = ("breath", "fade", "pulse", "blink")
# 主行怎么画：text 字形轮廓 / segments 七段数码管 / analog 指针表盘
#            flip 翻页卡 / dots 点阵
RENDER_MODES = ("text", "segments", "analog", "flip", "dots")

DEC_LIMITS: dict[str, dict[str, tuple[float, float, float]]] = {
    "border":   {"width": (1, 4, 1), "padding": (0, 120, 8)},
    "outline":  {"width": (1, 6, 1)},
    "glow":     {"radius": (0, 24, 8), "opacity": (0, 0.6, 0.4)},
    "shadow":   {"blur": (0, 24, 8), "opacity": (0, 1.0, 0.35),
                 "offsetX": (-40, 40, 2), "offsetY": (-40, 40, 2)},
    "backdrop": {"opacity": (0, 0.95, 0.85), "padding": (0, 120, 14)},
    "divider":  {"width": (1, 3, 1), "length": (0, 2000, 0)},
    "ring":     {"width": (1, 8, 2), "size": (0, 600, 0), "gap": (0, 64, 4)},
    "stack":    {"gap": (0, 80, 6), "subSize": (8, 120, 16)},
    "bracket":  {"width": (1, 6, 2), "length": (4, 160, 18), "padding": (0, 120, 8)},
}
EFF_LIMITS: dict[str, dict[str, tuple[float, float, float]]] = {
    "breath": {"duration": (800, 6000, 2400), "minOpacity": (0.3, 1.0, 0.5)},
    "fade":   {"duration": (200, 6000, 1200), "from": (0, 1, 1), "to": (0, 1, 0.3)},
    "pulse":  {"duration": (200, 6000, 1200), "scale": (1.0, 1.15, 1.05)},
    "blink":  {"onMs": (100, 5000, 600), "offMs": (100, 5000, 400)},
}

# 8 套内置预设 = 内置 .dtstyle 的别名（附 F 基准）。
# 全部走浅色底：深色背景板在桌面上像一块补丁，用户明确要求不要。
# 极简保留为出厂默认；其余 7 套刻意做成「一眼能分辨」的风格。
BUILTIN: dict[str, dict[str, Any]] = {
    # 2026-11-11 起：**所有内置预设一律不画背景板**。
    # 用户在深色壁纸上实测到「一块半透明灰底」，明确要求只留时间文字。
    # 因此 bg.enabled 全为 False、不出现 backdrop 层；电子表/点阵的面板、
    # 指针的表盘面、翻页卡的填充也一并去掉，只保留墨迹与描边。
    "minimal": {
        "schema": SCHEMA, "name": "极简", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Consolas", "size": 60, "weight": "Regular", "color": "#F2F5F8"},
        "decorations": [], "effects": [], "bg": {"enabled": False},
    },
    "lcd": {
        # 电子表：无面板的段码 + 深色未点亮残影（在深壁纸上像凹槽）
        "schema": SCHEMA, "name": "电子表", "author": "Clear", "version": "1.0.0",
        "render": "segments",
        # 残影只在「有面板」时才成立：没有底色时深色残影会糊成一片 8 字，
        # 数字根本读不出来（实测）。能力保留在 .dtstyle 里，预设不用。
        "segmentGhost": "",
        "text": {"font": "Consolas", "size": 64, "weight": "Regular", "color": "#8AE99B"},
        "decorations": [], "effects": [], "bg": {"enabled": False},
    },
    "analog": {
        # 指针：不铺表盘面，只有外环 + 刻度 + 三针，压在壁纸上更像线描挂钟
        "schema": SCHEMA, "name": "指针", "author": "Clear", "version": "1.0.0",
        "render": "analog",
        "face": {"fill": "#FFFFFF", "opacity": 0.0},
        "text": {"font": "Segoe UI", "size": 72, "weight": "Regular", "color": "#F2F5F8"},
        "decorations": [], "effects": [], "bg": {"enabled": False},
    },
    "tech": {
        # 科技：纯线条 HUD —— 四角括号 + 底部扫描线，没有底色
        "schema": SCHEMA, "name": "科技", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Cascadia Code", "size": 58, "weight": "Medium", "color": "#22C7E8"},
        "decorations": [
            {"type": "bracket", "width": 2, "length": 20, "color": "auto", "padding": 10},
            {"type": "divider", "position": "bottom", "width": 1, "color": "auto"},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "neon": {
        # 炫彩：紫字 + 品红描边 + 红/青错位影子
        "schema": SCHEMA, "name": "炫彩", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Bahnschrift", "size": 60, "weight": "Bold", "color": "#A78BFA"},
        "decorations": [
            {"type": "shadow", "color": "#FF2D55", "opacity": 1.0, "offsetX": -4, "offsetY": 0},
            {"type": "shadow", "color": "#22D3EE", "opacity": 1.0, "offsetX": 4, "offsetY": 4},
            {"type": "outline", "width": 2, "color": "#FF2D95"},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "pop": {
        # 潮流：黄字 + 4px 硬描边 + 6px 硬投影，贴纸风
        "schema": SCHEMA, "name": "潮流", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Arial Black", "size": 56, "weight": "Bold", "color": "#FFC61A"},
        "decorations": [
            {"type": "shadow", "color": "#14161A", "opacity": 1.0, "offsetX": 6, "offsetY": 6},
            {"type": "outline", "width": 4, "color": "#14161A"},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "flip": {
        # 翻页：卡片只描边不填充，中缝切断数字；fill=none 由渲染层识别
        "schema": SCHEMA, "name": "翻页", "author": "Clear", "version": "1.0.0",
        "render": "flip",
        "card": {"fill": "none", "edge": "auto", "radius": 10},
        "text": {"font": "Segoe UI", "size": 60, "weight": "Bold", "color": "#F2F5F8"},
        "decorations": [], "effects": [], "bg": {"enabled": False},
    },
    "matrix": {
        # 点阵：无面板，只有圆点
        "schema": SCHEMA, "name": "点阵", "author": "Clear", "version": "1.0.0",
        "render": "dots",
        "text": {"font": "Segoe UI", "size": 64, "weight": "Bold", "color": "#5B8CFF"},
        "decorations": [], "effects": [], "bg": {"enabled": False},
    },
    "serif": {
        # 开源排版风：衬线数字 + 一条细下划线
        "schema": SCHEMA, "name": "衬线", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Georgia", "size": 60, "weight": "Regular", "color": "#F7F3EA"},
        "decorations": [{"type": "divider", "position": "bottom", "width": 1, "color": "auto"}],
        "effects": [], "bg": {"enabled": False},
    },
    "mono": {
        # 终端：绿色等宽字 + 2px 光标线
        "schema": SCHEMA, "name": "终端", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Consolas", "size": 58, "weight": "Regular", "color": "#7EE787"},
        "decorations": [{"type": "divider", "position": "bottom", "width": 2, "color": "auto"}],
        "effects": [], "bg": {"enabled": False},
    },
    "amber": {
        # 琥珀 CRT：琥珀字 + 一圈低强度荧光
        "schema": SCHEMA, "name": "琥珀", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Consolas", "size": 58, "weight": "Medium", "color": "#FFC178"},
        "decorations": [{"type": "glow", "color": "auto", "radius": 8, "opacity": 0.25}],
        "effects": [], "bg": {"enabled": False},
    },
    "glitch": {
        # 故障艺术：左右各错 4px 的红/青影子，主体仍是白字
        "schema": SCHEMA, "name": "故障", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Bahnschrift", "size": 58, "weight": "Bold", "color": "#FFFFFF"},
        "decorations": [
            {"type": "shadow", "color": "#FF2D55", "opacity": 1.0, "offsetX": -4, "offsetY": 0},
            {"type": "shadow", "color": "#00E5FF", "opacity": 1.0, "offsetX": 4, "offsetY": 0},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "caption": {
        # 字幕：白字 + 2px 黑描边 + 下投影，任何画面上都能读
        "schema": SCHEMA, "name": "字幕", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Segoe UI", "size": 56, "weight": "Medium", "color": "#FFFFFF"},
        "decorations": [
            {"type": "shadow", "color": "#000000", "opacity": 0.55, "offsetX": 0, "offsetY": 3},
            {"type": "outline", "width": 2, "color": "#000000"},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "float": {
        # 浮起：白字 + 一段柔和外投影，靠影子把自己从壁纸上「抬」起来
        "schema": SCHEMA, "name": "浮起", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Segoe UI", "size": 64, "weight": "Medium", "color": "#FFFFFF"},
        "decorations": [{"type": "shadow", "color": "#0B1220", "opacity": 0.5,
                         "offsetX": 0, "offsetY": 10}],
        "effects": [], "bg": {"enabled": False},
    },
    "ink": {
        # 反白（浅壁纸用）：深墨字 + 2px 白描边，白墙 / 文档截图上不糊
        "schema": SCHEMA, "name": "墨字", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Segoe UI", "size": 56, "weight": "Medium", "color": "#14181F"},
        "decorations": [{"type": "outline", "width": 2, "color": "#FFFFFF"}],
        "effects": [], "bg": {"enabled": False},
    },
    "ring": {
        # 计时环：右侧一圈秒进度
        "schema": SCHEMA, "name": "计时环", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Cascadia Code", "size": 54, "weight": "Medium", "color": "#7CE7FF"},
        "decorations": [{"type": "ring", "mode": "second", "width": 3,
                         "color": "auto", "trackColor": "auto"}],
        "effects": [], "bg": {"enabled": False},
    },
    "frame": {
        # 取景：只留四个长角括号
        "schema": SCHEMA, "name": "取景", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Consolas", "size": 54, "weight": "Regular", "color": "#FFFFFF"},
        "decorations": [{"type": "bracket", "width": 2, "length": 44,
                         "color": "auto", "padding": 4}],
        "effects": [], "bg": {"enabled": False},
    },
    "dash": {
        # 虚线：1px 虚线细框，像草图纸上的辅助线
        "schema": SCHEMA, "name": "虚线", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Consolas", "size": 56, "weight": "Regular", "color": "#E6EDF3"},
        "decorations": [{"type": "border", "style": "dashed", "width": 1,
                         "color": "auto", "padding": 14}],
        "effects": [], "bg": {"enabled": False},
    },
    "twin": {
        # 双线：上下各一条细线夹住时间
        "schema": SCHEMA, "name": "双线", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Bahnschrift", "size": 56, "weight": "Medium", "color": "#FFFFFF"},
        "decorations": [
            {"type": "divider", "position": "top", "width": 1, "color": "auto"},
            {"type": "divider", "position": "bottom", "width": 1, "color": "auto"},
        ],
        "effects": [], "bg": {"enabled": False},
    },
    "thin": {
        # 细体：Light 大字 + 1px 细描边，低干扰
        "schema": SCHEMA, "name": "细体", "author": "Clear", "version": "1.0.0",
        "render": "text",
        "text": {"font": "Segoe UI Light", "size": 72, "weight": "Light", "color": "#F2F5F8"},
        "decorations": [{"type": "outline", "width": 1, "color": "#8A97A6"}],
        "effects": [], "bg": {"enabled": False},
    },
}

PRESET_LABELS = {
    "minimal": "极简 · 无装饰",
    "lcd": "电子表 · 七段码 + 残影",
    "analog": "指针 · 线描表盘",
    "tech": "科技 · 括号 + 扫描线",
    "neon": "炫彩 · 紫字红青错位",
    "pop": "潮流 · 贴纸描边",
    "flip": "翻页 · 线框翻页卡",
    "matrix": "点阵 · LED 圆点",
    "serif": "衬线 · 细下划线",
    "mono": "终端 · 绿色光标线",
    "amber": "琥珀 · CRT 荧光",
    "glitch": "故障 · RGB 错位",
    "caption": "字幕 · 黑描边投影",
    "float": "浮起 · 柔和投影",
    "ink": "墨字 · 白描边",
    "ring": "计时环 · 秒进度",
    "frame": "取景 · 长四角括号",
    "dash": "虚线 · 细虚线框",
    "twin": "双线 · 上下夹线",
    "thin": "细体 · Light 细字",
}


def _hex(v: Any, fallback: str) -> str:
    if isinstance(v, str) and v.startswith("#") and len(v) == 7:
        try:
            int(v[1:], 16)
            return v.upper()
        except ValueError:
            pass
    return fallback


def _ink(v: Any, fallback: str) -> str:
    """装饰层颜色：允许 "auto"（跟随文字颜色），其余必须收敛成 #RRGGBB。

    预设里把边框 / 括号 / 分割线 / 进度环写成 `auto`，用户改文字颜色时
    这些线一起变，不会出现「白字配青框」。
    """
    if isinstance(v, str) and v.strip().lower() in ("auto", "text"):
        return "auto"
    return _hex(v, fallback)


def _num(v: Any, lo: float, hi: float, fb: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return fb
    return min(hi, max(lo, n))


def _clean_layer(layer: Any, kind: str, warnings: list[str]) -> dict | None:
    if not isinstance(layer, dict):
        warnings.append(f"{kind}: 非对象条目已丢弃")
        return None
    typ = layer.get("type")
    allowed = DECORATION_TYPES if kind == "decoration" else EFFECT_TYPES
    if typ not in allowed:
        warnings.append(f"{kind}: 未知类型 {typ!r} 已丢弃")
        return None
    out = dict(layer)
    limits = (DEC_LIMITS if kind == "decoration" else EFF_LIMITS).get(typ, {})
    for key, (lo, hi, fb) in limits.items():
        if key in out:
            out[key] = _num(out[key], lo, hi, fb)
        elif fb:
            out[key] = fb
    for key in ("color", "trackColor", "subColor"):
        if key in out:
            out[key] = _ink(out[key], "#2F6DF6")
    if typ == "border":
        out["style"] = out.get("style") if out.get("style") in ("solid", "dashed", "dotted") else "solid"
    if typ == "ring":
        out["mode"] = out.get("mode") if out.get("mode") in ("progress", "second", "minute") else "second"
    if typ == "divider":
        out["position"] = out.get("position") if out.get("position") in ("top", "bottom", "left", "right") else "bottom"
    return out


def validate_pack(raw: Any) -> tuple[dict, list[str]]:
    """把任意输入收敛成安全的 pack。绝不抛异常到渲染层。"""
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return copy.deepcopy(BUILTIN["minimal"]), ["样式包根节点不是对象，回落「极简」"]
    schema = raw.get("schema")
    if schema and schema != SCHEMA:
        warnings.append(f"schema {schema!r} 与 {SCHEMA} 不符，按兼容模式加载")
    base = copy.deepcopy(BUILTIN["minimal"])
    render = raw.get("render")
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "name": str(raw.get("name") or "未命名样式")[:60],
        "author": str(raw.get("author") or "community")[:60],
        "version": str(raw.get("version") or "1.0.0")[:20],
        "render": render if render in RENDER_MODES else "text",
        "text": dict(base["text"]),
        "decorations": [], "effects": [], "bg": dict(base["bg"]),
    }
    txt = raw.get("text")
    if isinstance(txt, dict):
        for k in ("font", "weight"):
            if isinstance(txt.get(k), str):
                out["text"][k] = txt[k][:60]
        if "size" in txt:
            out["text"]["size"] = int(_num(txt["size"], 12, 200, 48))
        if "color" in txt:
            out["text"]["color"] = _hex(txt["color"], "#1F2328")
    bg = raw.get("bg")
    if isinstance(bg, dict):
        out["bg"]["enabled"] = bool(bg.get("enabled", False))
        out["bg"]["color"] = _hex(bg.get("color", "#FFFFFF"), "#FFFFFF")
        out["bg"]["padding"] = int(_num(bg.get("padding", 12), 0, 120, 12))

    # analog 模式的表盘填充；opacity=0 表示只画一圈表盘线、不铺面
    face = raw.get("face")
    if isinstance(face, dict):
        out["face"] = {"fill": _hex(face.get("fill", "#FFFFFF"), "#FFFFFF"),
                       "opacity": _num(face.get("opacity", 0.88), 0.0, 1.0, 0.88)}
    else:
        out["face"] = {"fill": "#FFFFFF", "opacity": 0.0}

    # flip 模式的卡片配色（填充 / 描边 / 圆角）。fill 允许 "none" = 只描边不填充，
    # 「只允许时间文字」时翻页卡就退化成线框，不再有实心块。
    card = raw.get("card")
    if isinstance(card, dict):
        fill_raw = card.get("fill", "#FFFFFF")
        fill = ("none" if str(fill_raw).lower() in ("none", "transparent", "")
                else _hex(fill_raw, "#FFFFFF"))
        out["card"] = {"fill": fill,
                       "edge": _ink(card.get("edge", "#D8DEE4"), "#D8DEE4"),
                       "radius": _num(card.get("radius", 8), 0, 40, 8)}
    else:
        out["card"] = {"fill": "#FFFFFF", "edge": "#D8DEE4", "radius": 8}

    # segments 模式的「未点亮段」残影色；空串 = 不画残影
    ghost = raw.get("segmentGhost")
    out["segmentGhost"] = _hex(ghost, "") if isinstance(ghost, str) and ghost else ""

    decs = raw.get("decorations", [])
    if not isinstance(decs, list):
        warnings.append("decorations 不是数组，按空处理")
        decs = []
    if len(decs) > MAX_DECORATIONS:
        warnings.append(f"装饰层 {len(decs)} 个超过上限 {MAX_DECORATIONS}，已截断")
    for layer in decs[:MAX_DECORATIONS]:
        cleaned = _clean_layer(layer, "decoration", warnings)
        if cleaned:
            out["decorations"].append(cleaned)

    effs = raw.get("effects", [])
    if not isinstance(effs, list):
        warnings.append("effects 不是数组，按空处理（无动画）")
        effs = []
    if len(effs) > MAX_EFFECTS:
        warnings.append(f"特效 {len(effs)} 个超过上限 {MAX_EFFECTS}，已截断")
    for layer in effs[:MAX_EFFECTS]:
        cleaned = _clean_layer(layer, "effect", warnings)
        if cleaned:
            out["effects"].append(cleaned)
    return out, warnings


def load_pack(path: Path) -> tuple[dict, list[str]]:
    if path.stat().st_size > MAX_PACK_BYTES:
        raise ValueError(f"样式包超过 {MAX_PACK_BYTES // 1024} KB 上限")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return validate_pack(raw)


def get_builtin(name: str) -> dict:
    return copy.deepcopy(BUILTIN.get(name, BUILTIN["minimal"]))


def resolve(settings_data: dict, styles_dir: Path, builtin_dir: Path) -> tuple[dict, list[str], str | None]:
    """决定最终生效的 pack。返回 (pack, warnings, 提示文案)。

    优先级：settings 中用户手写的装饰层 > packRef 指定样式包 > 内置预设 > 极简。
    """
    style = settings_data.get("style", {})
    warnings: list[str] = []
    notice: str | None = None
    pack = get_builtin(style.get("preset", "digital"))
    pack_ref = (style.get("packRef") or "").strip()

    if pack_ref:
        if "/" in pack_ref or "\\" in pack_ref or ".." in pack_ref:
            notice = f"样式包路径不合法（{pack_ref}），已回落到内置「极简」"
            warnings.append(notice)
            pack = get_builtin("minimal")
        else:
            candidates = [styles_dir / pack_ref, builtin_dir / pack_ref]
            found = next((p for p in candidates if p.is_file()), None)
            if found is None:
                notice = f"样式包 {pack_ref} 不存在，已回落到内置「极简」"
                warnings.append(notice)
                pack = get_builtin("minimal")
            else:
                try:
                    pack, warns = load_pack(found)
                    warnings.extend(warns)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    notice = f"样式包 {pack_ref} 加载失败（{exc}），已回落到内置「极简」"
                    warnings.append(notice)
                    pack = get_builtin("minimal")

    user_decs = style.get("decorations") or []
    user_effs = style.get("effects") or []
    if user_decs or user_effs:
        cleaned_pack, warns = validate_pack({
            "name": "用户自定义", "render": pack.get("render", "text"),
            "face": pack.get("face"), "card": pack.get("card"),
            "segmentGhost": pack.get("segmentGhost"),
            "text": pack.get("text", {}),
            "decorations": user_decs, "effects": user_effs, "bg": pack.get("bg", {}),
        })
        warnings.extend(warns)
        pack = cleaned_pack
    return pack, warnings, notice


def export_builtin_files(target: Path) -> None:
    """把 8 套内置预设写成真实 .dtstyle 文件，作为社区格式示例。

    每次启动重写：这些文件是内置预设的投影，必须跟着 BUILTIN 走，
    否则目录里会残留旧版预设（例如已下线的蓝色边框）。
    """
    target.mkdir(parents=True, exist_ok=True)
    for key, data in BUILTIN.items():
        path = target / f"{key}.dtstyle"
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # 只读安装目录下不做硬失败，内存里的 BUILTIN 仍然生效
