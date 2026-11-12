# -*- coding: utf-8 -*-
"""离屏 QImage 渲染管线：文字 + 8 类装饰 + 4 类特效。

层顺序（附 D）：stack → text → outline → shadow/glow → backdrop → ring → border → effects
实现说明：规格给的是「层的注册 / 叠放顺序」，其中 backdrop 是背景板，
实际绘制必须先画它，否则会盖住文字。因此绘制顺序调整为：
    backdrop(底) → shadow/glow → outline → text → divider → ring → border(顶)
数组内的同类先后仍严格保留，后写盖上层。
校验集中在 stylepack.load()，本模块不解析、不抛异常；单层失败跳过并记日志。

坐标系与像素密度
----------------
render() 的所有排版计算都发生在**逻辑像素 (DIP)** 里，但位图按目标屏的
devicePixelRatio 生成物理像素，再由 Qt 以 1:1 映射回屏幕。
1x 位图在 150% 屏上会被 Qt 放大 1.5 倍 —— 那是文字边缘发毛、锯齿的根因。
调用方传入 dpr，本模块负责：画布 = 逻辑尺寸 × dpr、painter 缩放 dpr、
结束前 setDevicePixelRatio(dpr)，这样 widget.resize(逻辑尺寸) 与位图严格对齐。
"""
from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetrics,
                           QImage, QPainter, QPainterPath, QPen)

from . import clock, store, stylepack

_WEIGHTS = {
    "Light": QFont.Weight.Light,
    "Regular": QFont.Weight.Normal,
    "Medium": QFont.Weight.Medium,
    "Bold": QFont.Weight.Bold,
}
_LINE_STYLES = {"solid": Qt.PenStyle.SolidLine, "dashed": Qt.PenStyle.DashLine,
                "dotted": Qt.PenStyle.DotLine}


def _safe_int(value, fallback: int) -> int:
    """渲染层不许抛异常：坏参数一律退回落差值。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _qcolor(value: str, alpha: float = 1.0) -> QColor:
    c = QColor(value or "#1F2328")
    if not c.isValid():
        c = QColor("#1F2328")
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _ink(raw, text_color: str, fallback: str = "#1F2328") -> str:
    """装饰取色：`auto` / `text` 表示跟随文字颜色，其余按字面色。

    预设把边框 / 括号 / 分割线 / 进度环写成 auto，用户改文字颜色时线一起变，
    不再出现「白字配青框」。
    """
    s = str(raw if raw is not None else fallback).strip()
    return text_color if s.lower() in ("auto", "text", "") else s


def _pick_font(family: str) -> str:
    if family and QFontDatabase.hasFamily(family):
        return family
    for fallback in ("Consolas", "Microsoft YaHei", "Segoe UI"):
        if QFontDatabase.hasFamily(fallback):
            return fallback
    return "Arial"


# ---------------------------------------------------------------------------
# 七段数码管（电子表风格）
#
# 本机没有 7-segment 字体，靠字体模拟只会得到「等宽字体 + 深色底」，名不副实。
# 这里直接按段绘制：数字 → 7 段中的若干段，画成带 45° 切角的条块，
# 输出仍然是 QPainterPath，因此描边 / 发光 / 阴影 / 背景板全部沿用原管线。
# ---------------------------------------------------------------------------
_SEG_MAP = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g", "_": "d", " ": "",
}
# 段相对字高的比例（照抄常见 LCD 版式：字宽 0.58H、笔厚 0.14H、字距 0.16H）
_SEG_W, _SEG_T, _SEG_GAP = 0.58, 0.14, 0.16
_SEG_COLON, _SEG_DOT = 0.20, 0.14


def _hseg(x0: float, x1: float, y: float, t: float) -> QPainterPath:
    """横段：两端 45° 切角的条块。"""
    h, c = t / 2.0, t / 2.0
    p = QPainterPath()
    p.moveTo(x0 + c, y - h)
    p.lineTo(x1 - c, y - h)
    p.lineTo(x1, y)
    p.lineTo(x1 - c, y + h)
    p.lineTo(x0 + c, y + h)
    p.lineTo(x0, y)
    p.closeSubpath()
    return p


def _vseg(x: float, y0: float, y1: float, t: float) -> QPainterPath:
    """竖段：两端 45° 切角的条块。"""
    h, c = t / 2.0, t / 2.0
    p = QPainterPath()
    p.moveTo(x - c, y0 + h)
    p.lineTo(x, y0)
    p.lineTo(x + c, y0 + h)
    p.lineTo(x + c, y1 - h)
    p.lineTo(x, y1)
    p.lineTo(x - c, y1 - h)
    p.closeSubpath()
    return p


def segment_layout(text: str, height: int) -> tuple[float, list[tuple[str, float, float]]]:
    """返回 (总宽, [(类型, x 起点, 宽度)])，供绘制与画布测宽共用。"""
    h = float(max(12, height))
    units: list[tuple[str, float]] = []
    for ch in text:
        if ch in _SEG_MAP:
            units.append(("digit", h * _SEG_W))
        elif ch == ":":
            units.append(("colon", h * _SEG_COLON))
        elif ch == ".":
            units.append(("dot", h * _SEG_DOT))
        else:
            units.append(("blank", h * _SEG_W * 0.5))
    total = sum(w for _, w in units) + h * _SEG_GAP * max(0, len(units) - 1)
    out, x = [], 0.0
    for kind, w in units:
        out.append((kind, x, w))
        x += w + h * _SEG_GAP
    return total, out


def segment_path(text: str, height: int, force_full: bool = False) -> QPainterPath:
    """把整串文字画成数码管：基线对齐到数字底边。

    force_full=True 时忽略亮灭状态、七个段全部画出来，用于 LCD 的「未点亮段」
    残影 —— 真实计算器屏上没亮的段也在，这层半透明底纹是电子表像不像的关键。
    """
    h = float(max(12, height))
    t = h * _SEG_T
    path = QPainterPath()
    _, cells = segment_layout(text, height)
    digits = [c for c in text if c in _SEG_MAP]
    idx = 0
    for kind, x0, w in cells:
        if kind == "digit":
            ch = digits[idx] if idx < len(digits) else " "
            idx += 1
            lit = "abcdefg" if force_full else _SEG_MAP.get(ch, "")
            y0, y1 = 0.0, h
            mid = y1 / 2.0
            inset = t * 0.55
            segs = {
                "a": _hseg(x0 + inset, x0 + w - inset, t * 0.5, t),
                "d": _hseg(x0 + inset, x0 + w - inset, y1 - t * 0.5, t),
                "g": _hseg(x0 + inset, x0 + w - inset, mid, t),
                "f": _vseg(x0 + t * 0.5, y0 + t * 0.8, mid - t * 0.3, t),
                "b": _vseg(x0 + w - t * 0.5, y0 + t * 0.8, mid - t * 0.3, t),
                "e": _vseg(x0 + t * 0.5, mid + t * 0.3, y1 - t * 0.8, t),
                "c": _vseg(x0 + w - t * 0.5, mid + t * 0.3, y1 - t * 0.8, t),
            }
            for name in lit:
                path.addPath(segs[name])
        elif kind == "colon":
            dot = max(2.0, h * 0.11)
            for cy in (h * 0.33, h * 0.70):
                path.addRect(x0 + (w - dot) / 2.0, cy - dot / 2.0, dot, dot)
        elif kind == "dot":
            dot = max(2.0, h * 0.11)
            path.addRect(x0, h - dot, dot, dot)
    return path


# ---------------------------------------------------------------------------
# 翻页钟（flip clock）
#
# 开源翻页钟（flipclock.js / Fliqlo 一类）的形态：每个数字一张圆角卡片，
# 中间一道横向缝隙 + 两侧铰链，数字被缝隙切断。这里直接按卡片排版，
# 卡片与数字都走 QPainterPath，描边 / 投影仍沿用原管线。
# ---------------------------------------------------------------------------
_FLIP_PAD_X, _FLIP_PAD_Y = 0.16, 0.13
_FLIP_RADIUS, _FLIP_GAP = 0.08, 0.07


def flip_layout(text: str, size: int, digit_w: float
                ) -> tuple[float, list[tuple[str, str, float, float]]]:
    """返回 (总宽, [(类型, 字符, x, 卡片宽)])。数字卡片等宽，冒号占窄列。"""
    card_w = digit_w + size * _FLIP_PAD_X * 2
    gap = size * _FLIP_GAP
    units: list[tuple[str, str, float]] = []
    for ch in text:
        if ch.isdigit() or ch in "-_":
            units.append(("card", ch, card_w))
        elif ch == ":":
            units.append(("colon", ch, card_w * 0.44))
        elif ch == ".":
            units.append(("dot", ch, card_w * 0.32))
        else:
            units.append(("blank", ch, card_w * 0.5))
    total = sum(w for _, _, w in units) + gap * max(0, len(units) - 1)
    out: list[tuple[str, str, float, float]] = []
    x = 0.0
    for kind, ch, w in units:
        out.append((kind, ch, x, w))
        x += w + gap
    return total, out


def flip_paths(text: str, size: int, font: QFont, fm: QFontMetrics,
               digit_w: float) -> tuple[QPainterPath, list[tuple[float, float, float]]]:
    """返回 (数字墨迹路径, [(x, 宽, 类型索引)])；卡片几何由调用方按同一份布局画。"""
    _, cells = flip_layout(text, size, digit_w)
    pad_y = size * _FLIP_PAD_Y
    path = QPainterPath()
    boxes: list[tuple[float, float, float]] = []
    for kind, ch, x, w in cells:
        boxes.append((x, w, 1.0 if kind in ("card", "colon", "dot") else 0.0))
        if kind == "card":
            adv = fm.horizontalAdvance(ch)
            path.addText(QPointF(x + (w - adv) / 2.0, pad_y + fm.ascent()), font, ch)
        elif kind == "colon":
            dot = max(2.0, size * 0.10)
            for cy in (pad_y + fm.ascent() * 0.42, pad_y + fm.ascent() * 1.12):
                path.addEllipse(QPointF(x + w / 2.0, cy), dot / 2.0, dot / 2.0)
        elif kind == "dot":
            dot = max(2.0, size * 0.10)
            path.addEllipse(QPointF(x + w / 2.0, pad_y + fm.ascent() + size * 0.06),
                            dot / 2.0, dot / 2.0)
    return path, boxes


def paint_flip_cards(p: QPainter, boxes: list[tuple[float, float, float]],
                     height: float, size: int, card: dict, ink: str = "") -> None:
    """先画卡片底与铰链，再把缝隙盖在数字上方（由 paint_flip_seams 完成）。

    card.fill == "none" 时只描边不填充 —— 内置「翻页」预设就是线框版，
    这样桌面上只有时间文字与线框，没有实心色块。
    """
    fill_raw = str(card.get("fill", "#FFFFFF"))
    edge = _qcolor(_ink(card.get("edge"), ink, "#D8DEE4"), 1.0)
    radius = float(card.get("radius", max(2.0, size * _FLIP_RADIUS)))
    brush = Qt.BrushStyle.NoBrush if fill_raw.lower() == "none" else QBrush(_qcolor(fill_raw))
    for x, w, vis in boxes:
        if vis < 0.5:
            continue
        p.setPen(QPen(edge, 1.0))
        p.setBrush(brush)
        p.drawRoundedRect(QRectF(x + 0.5, 0.5, w - 1.0, height - 1.0), radius, radius)


def paint_flip_seams(p: QPainter, boxes: list[tuple[float, float, float]],
                     height: float, card: dict, ink: str = "") -> None:
    """卡片中缝 + 两侧铰链，压在数字上，翻页的「断字」手感就来自这一道缝。

    缝隙不能太淡：只画 1px 描边色会看成分隔线，而不是上下两片卡片。
    这里用「1px 白高光 + 3px 加深缝隙」做出两片叠压的层次。
    """
    edge = _qcolor(_ink(card.get("edge"), ink, "#D8DEE4"), 1.0)
    gap_brush = QBrush(edge.darker(115))
    hi_brush = QBrush(_qcolor("#FFFFFF", 0.92))
    mid = height / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    for x, w, vis in boxes:
        if vis < 0.5:
            continue
        # PySide6 的 fillRect 不接受只有一个矩形参数的默认画刷，必须显式传 brush
        p.fillRect(QRectF(x + 1.0, mid - 1.5, max(0.0, w - 2.0), 3.0), gap_brush)
        p.fillRect(QRectF(x + 1.0, mid - 2.5, max(0.0, w - 2.0), 1.0), hi_brush)
        # 铰链块必须留在卡片内沿，越界会把相邻卡片的中缝连成一条直线
        p.fillRect(QRectF(x + 1.0, mid - 3.5, 2.0, 8.0), gap_brush)
        p.fillRect(QRectF(x + w - 3.0, mid - 3.5, 2.0, 8.0), gap_brush)


# ---------------------------------------------------------------------------
# 点阵（dot matrix）
#
# 先把文字按「点距」的倒数缩绘成一张小位图，再逐格取样生成圆点路径。
# 这样任意字体都能转成点阵，不必内置点阵字库；输出仍是 QPainterPath，
# 描边 / 发光 / 投影照旧。
# ---------------------------------------------------------------------------
_DOT_RATIO = 0.045      # 点距 / 字号：约 22 行点铺满字高，笔画才不会断线
_DOT_RADIUS = 0.40      # 点半径 / 点距：太大糊成一片，太小像断线
_DOT_ALPHA = 40         # 取样阈值：低于它的格子不点亮


def dot_matrix_path(text: str, font: QFont, fm: QFontMetrics, size: int
                    ) -> tuple[QPainterPath, float, float]:
    """返回 (圆点路径, 宽, 高)；点距由字号决定，一列点约等于半个笔画宽。"""
    pitch = max(3.0, size * _DOT_RATIO)
    text_w = max(1, fm.horizontalAdvance(text))
    cols = max(1, int(math.ceil(text_w / pitch)))
    rows = max(1, int(math.ceil(fm.height() / pitch)))

    mask = QImage(cols, rows, QImage.Format_ARGB32_Premultiplied)
    mask.fill(0)
    mp = QPainter(mask)
    mp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    mp.scale(1.0 / pitch, 1.0 / pitch)
    mp.setPen(Qt.PenStyle.NoPen)
    mp.setBrush(QBrush(QColor("#000000")))
    glyph = QPainterPath()
    glyph.addText(QPointF(0.0, float(fm.ascent())), font, text)
    mp.drawPath(glyph)
    mp.end()

    out = QPainterPath()
    radius = pitch * _DOT_RADIUS
    for row in range(rows):
        for col in range(cols):
            if mask.pixelColor(col, row).alpha() >= _DOT_ALPHA:
                out.addEllipse(QPointF((col + 0.5) * pitch, (row + 0.5) * pitch),
                               radius, radius)
    return out, cols * pitch, rows * pitch


def paint_analog(p: QPainter, cx: float, cy: float, radius: float,
                 now: datetime, color: str, face: dict | None = None) -> None:
    """传统指针表盘：可选白色表盘 + 外环 + 12 刻度 + 时分秒三针。"""
    ink = _qcolor(color)
    r = float(radius)
    face = face or {}
    face_alpha = float(face.get("opacity", 0.0) or 0.0)
    if face_alpha > 0.001:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_qcolor(str(face.get("fill", "#FFFFFF")), face_alpha)))
        p.drawEllipse(QPointF(cx, cy), r, r)

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ink, max(1.0, r * 0.028)))
    p.drawEllipse(QPointF(cx, cy), r, r)
    for i in range(12):
        a = math.radians(i * 30.0)
        long_tick = i % 3 == 0
        inner = r * (0.74 if long_tick else 0.85)
        p.setPen(QPen(ink, max(1.0, r * (0.055 if long_tick else 0.022))))
        p.drawLine(QPointF(cx + math.sin(a) * inner, cy - math.cos(a) * inner),
                   QPointF(cx + math.sin(a) * r * 0.94, cy - math.cos(a) * r * 0.94))

    second = now.second + now.microsecond / 1_000_000.0
    minute = now.minute + second / 60.0
    hour = (now.hour % 12) + minute / 60.0

    def hand(angle_deg: float, length: float, width: float) -> None:
        a = math.radians(angle_deg)
        p.setPen(QPen(ink, max(1.0, width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(a) * length, cy - math.cos(a) * length))

    hand(hour * 30.0, r * 0.50, r * 0.075)
    hand(minute * 6.0, r * 0.76, r * 0.050)
    hand(second * 6.0, r * 0.84, r * 0.022)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ink)
    p.drawEllipse(QPointF(cx, cy), max(1.5, r * 0.045), max(1.5, r * 0.045))


RENDER_MODES = stylepack.RENDER_MODES


class Renderer:
    def __init__(self) -> None:
        self._cached_key: tuple | None = None
        self._cached_image: QImage | None = None

    def render(self, now: datetime, cfg: dict, pack: dict, now_ms: int,
               dpr: float = 1.0) -> QImage:
        style = cfg.get("style", {})
        main_text, sub_text = clock.build_lines(now, cfg)
        pack_text = pack.get("text", {}) if isinstance(pack, dict) else {}
        decs = [d for d in pack.get("decorations", []) if isinstance(d, dict)]
        effs = [e for e in pack.get("effects", []) if isinstance(e, dict)]

        family = _pick_font(str(style.get("font") or pack_text.get("font") or ""))
        size = int(style.get("size") or pack_text.get("size") or 48)
        weight = _WEIGHTS.get(str(style.get("weight") or pack_text.get("weight") or "Medium"),
                              QFont.Weight.Medium)
        text_styles = set(style.get("textStyles") or [])
        color = str(style.get("color") or pack_text.get("color") or "#1F2328")
        opacity = float(style.get("opacity", 1.0))
        bg = style.get("background", {}) or {}

        font = QFont(family)
        font.setPixelSize(size)
        font.setWeight(weight)
        font.setBold("bold" in text_styles or weight >= QFont.Weight.Bold)
        font.setItalic("italic" in text_styles)
        font.setUnderline("underline" in text_styles)
        fm = QFontMetrics(font)
        sub_font = QFont(family)
        sub_font.setPixelSize(max(10, int(size * 0.36)))
        sub_font.setWeight(QFont.Weight.Normal)
        sub_fm = QFontMetrics(sub_font)

        # 五种绘制模式：text 字形 / segments 七段码 / analog 指针 / flip 翻页卡 / dots 点阵
        mode = str(pack.get("render") or "text")
        if mode not in RENDER_MODES:
            mode = "text"
        card = pack.get("card") if isinstance(pack.get("card"), dict) else {}
        flip_boxes: list[tuple[float, float, float]] = []

        if mode == "analog":
            face = int(max(56, min(360, size * 2.4)))
            main_w = main_h = face
            # 表盘不显示数字，尺寸由表盘直径决定
            main_text = ""
        elif mode == "segments":
            main_h = int(max(16, size))
            main_w = int(round(segment_layout(main_text, main_h)[0]))
        elif mode == "flip":
            digit_w = max(fm.horizontalAdvance(d) for d in "0123456789")
            main_w = int(math.ceil(flip_layout(main_text, size, digit_w)[0]))
            main_h = int(math.ceil(fm.height() + size * _FLIP_PAD_Y * 2))
        elif mode == "dots":
            pitch = max(3.0, size * _DOT_RATIO)
            cols = max(1, int(math.ceil(max(1, fm.horizontalAdvance(main_text)) / pitch)))
            rows = max(1, int(math.ceil(fm.height() / pitch)))
            main_w, main_h = int(math.ceil(cols * pitch)), int(math.ceil(rows * pitch))
        else:
            main_w = max(1, fm.horizontalAdvance(main_text))
            main_h = fm.height()

        sub_w = sub_fm.horizontalAdvance(sub_text) if sub_text else 0
        text_w = max(main_w, sub_w)
        sub_h = sub_fm.height() if sub_text else 0
        stack_gap = 6
        for d in decs:
            if d.get("type") == "stack":
                stack_gap = _safe_int(d.get("gap", stack_gap), stack_gap)
        text_h = main_h + (sub_h + stack_gap if sub_text else 0)

        # 留白要吃掉「会画到字框外」的图层，否则发光/描边/投影会被画布切边
        pad = 10
        for d in decs:
            if d.get("type") == "backdrop":
                pad = max(pad, _safe_int(d.get("padding", 10), 10))
            elif d.get("type") == "border":
                # 边框是「套在字框外」的，padding 是它到字框的间距；留白要再吃掉线宽
                # 和半像素，否则描边会压在画布边缘被切掉一半（虚线预设实测踩坑）
                pad = max(pad, _safe_int(d.get("padding", 10), 10)
                          + max(1, _safe_int(d.get("width", 1), 1)) + 2)
            elif d.get("type") == "bracket":
                # 括号是往内画的，但它自己的 padding 决定离边距离，留白要跟它对齐
                pad = max(pad, _safe_int(d.get("padding", 8), 8)
                          + _safe_int(d.get("width", 2), 2) + 2)
            elif d.get("type") == "outline":
                pad = max(pad, _safe_int(d.get("width", 1), 1) + 6)
            elif d.get("type") == "glow":
                pad = max(pad, _safe_int(d.get("radius", 8), 8) + 6)
            elif d.get("type") == "shadow":
                pad = max(pad, max(abs(_safe_int(d.get("offsetX", 2), 2)),
                                   abs(_safe_int(d.get("offsetY", 2), 2))) + 6)
        if bg.get("enabled"):
            pad = max(pad, _safe_int(bg.get("padding", 12), 12))
        ring = next((d for d in decs if d.get("type") == "ring"), None)
        ring_size = 0
        text_w_full = text_w + pad * 2
        h = max(24, text_h + pad * 2)
        if ring:
            # 环半径必须服从画布高度：早期按 text_h*1.6 取，圆环比画布还高，
            # 上下两端被裁掉，看起来像个缺口圆弧。
            ring_size = int(ring.get("size") or text_h)
            ring_size = max(20, min(ring_size, 400, h - 10))
        w = max(40, text_w_full + (ring_size + 8 if ring else 0))

        dpr = max(1.0, min(4.0, float(dpr or 1.0)))
        pw, ph = max(1, int(round(w * dpr))), max(1, int(round(h * dpr)))

        # 无动画且文本未变时复用上一帧，避免每秒重建 QImage。
        # analog 模式不产生文字，主行文本恒为空，必须把「当前秒」编进缓存键，
        # 否则秒针会停在第一帧不动。
        time_key = (now.hour, now.minute, now.second) if mode == "analog" else None
        cache_key = (mode, main_text, sub_text, time_key, w, h, round(dpr, 3), family, size,
                     str(weight), color, tuple(style.get("textStyles") or []), opacity,
                     repr(decs), repr(effs), bool(effs and now_ms // 33))
        if not effs and cache_key == self._cached_key and self._cached_image is not None:
            return self._cached_image

        image = QImage(pw, ph, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # 之后全部用逻辑坐标绘制，物理像素由这一次缩放承担
        p.scale(dpr, dpr)

        tx = float(pad)
        ty = float(pad + fm.ascent())
        # 主副两行都在 text_w 范围内居中：日期/星期必须压在时间正中。
        # 旧写法只给指针 / 翻页居中，文本模式一律左对齐，日期就贴到左边去了。
        main_x = tx + (text_w - main_w) / 2.0
        main_path = QPainterPath()
        ghost_path = None
        if mode == "segments":
            main_path = segment_path(main_text, main_h)
            ghost_ink = str(pack.get("segmentGhost") or "")
            if ghost_ink:
                # 未点亮的段先铺一层淡色，再压亮段，才有真实 LCD 的底纹感
                ghost_path = segment_path(main_text, main_h, force_full=True)
            if main_path.elementCount():
                main_path.translate(main_x, float(pad))
            if ghost_path is not None:
                ghost_path.translate(main_x, float(pad))
        elif mode == "flip":
            main_path, flip_boxes = flip_paths(main_text, size, font, fm, digit_w)
            main_path.translate(main_x, float(pad))
        elif mode == "dots":
            main_path, _, _ = dot_matrix_path(main_text, font, fm, size)
            main_path.translate(main_x, float(pad))
        elif mode == "text":
            main_path.addText(QPointF(main_x, ty), font, main_text)
        # analog 模式不产生主路径，表盘单独绘制（见下方 4) text）
        sub_path = None
        if sub_text:
            # 副行基线 = 主行字框下沿 + 行间距 + 副行 ascent。
            # 旧写法在 ty（已含一次 fm.ascent()）之上又加了一次 line_h - descent，
            # 等于多叠了一个 ascent，基线整体落到画布下方 90px，副行 100% 被裁掉。
            # 指针 / 翻页的主行都是「块面」，日期行居中压在下面才不歪。
            sub_x = tx + (text_w - sub_w) / 2.0
            sub_path = QPainterPath()
            sub_path.addText(QPointF(sub_x, float(pad + main_h + stack_gap + sub_fm.ascent())),
                             sub_font, sub_text)

        # 1) backdrop —— 底层背景板
        if bg.get("enabled"):
            p.fillRect(QRectF(0, 0, w, h), _qcolor(str(bg.get("color", "#FFFFFF")), 0.9))
        for d in decs:
            if d.get("type") != "backdrop":
                continue
            try:
                p.fillRect(QRectF(0, 0, w, h),
                           _qcolor(str(d.get("color", "#1F2328")), float(d.get("opacity", 0.85))))
            except Exception as exc:
                store.log(f"backdrop 图层跳过: {exc}", "WARN")

        # 1.5) 卡片底板 / LCD 未点亮段残影 —— 必须压在文字下方
        if mode == "flip" and flip_boxes:
            try:
                p.save()
                p.translate(main_x, float(pad))
                paint_flip_cards(p, flip_boxes, float(main_h), size, card, color)
                p.restore()
            except Exception as exc:
                store.log(f"flip 卡片跳过: {exc}", "WARN")
        if ghost_path is not None:
            try:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_qcolor(str(pack.get("segmentGhost") or "#C8D6BE"), 1.0)))
                p.drawPath(ghost_path)
            except Exception as exc:
                store.log(f"segments 残影跳过: {exc}", "WARN")

        # 2) shadow / glow —— 文字下方
        for d in decs:
            try:
                if d.get("type") == "shadow":
                    p.save()
                    p.translate(float(d.get("offsetX", 2)), float(d.get("offsetY", 2)))
                    p.fillPath(main_path, _qcolor(_ink(d.get("color"), color, "#000000"),
                                                  float(d.get("opacity", 0.35))))
                    p.restore()
                elif d.get("type") == "glow":
                    radius = max(1, int(d.get("radius", 8)))
                    for r in range(radius, 0, -3):
                        pen = QPen(_qcolor(str(d.get("color", "#2F6DF6")),
                                           float(d.get("opacity", 0.4)) * 0.16), r * 2)
                        p.setPen(pen)
                        p.drawPath(main_path)
            except Exception as exc:
                store.log(f"{d.get('type')} 图层跳过: {exc}", "WARN")

        # 3) outline（文字样式 + 装饰层）
        outline_width = 0
        outline_color = color
        if "outline" in text_styles:
            outline_width, outline_color = 1, "#FFFFFF" if bg.get("enabled") else "#1F2328"
        for d in decs:
            if d.get("type") == "outline":
                outline_width = int(d.get("width", 1))
                outline_color = _ink(d.get("color"), color, outline_color)
        if outline_width:
            p.setPen(QPen(_qcolor(outline_color), outline_width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(main_path)

        # 4) text
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_qcolor(color)))
        if mode == "analog":
            radius = main_h / 2.0 - max(1.0, main_h * 0.02)
            paint_analog(p, tx + main_w / 2.0, pad + main_h / 2.0, radius, now, color,
                         pack.get("face"))
        else:
            p.drawPath(main_path)
        if sub_path is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qcolor(color)))
            p.drawPath(sub_path)

        # 4.5) 翻页中缝 —— 必须压在数字上，否则断字效果出不来
        if mode == "flip" and flip_boxes:
            try:
                p.save()
                p.translate(main_x, float(pad))
                paint_flip_seams(p, flip_boxes, float(main_h), card, color)
                p.restore()
            except Exception as exc:
                store.log(f"flip 中缝跳过: {exc}", "WARN")

        # 5) divider
        for d in decs:
            if d.get("type") != "divider":
                continue
            try:
                ln = int(d.get("length") or text_w)
                pen = QPen(_qcolor(_ink(d.get("color"), color, "#D6DCE5")), int(d.get("width", 1)))
                p.setPen(pen)
                pos = d.get("position", "bottom")
                y = h - pad / 2 if pos == "bottom" else pad / 2
                if pos in ("left", "right"):
                    x = pad / 2 if pos == "left" else w - pad / 2
                    p.drawLine(QPointF(x, pad), QPointF(x, h - pad))
                else:
                    p.drawLine(QPointF(tx, y), QPointF(tx + min(ln, w - pad * 2), y))
            except Exception as exc:
                store.log(f"divider 图层跳过: {exc}", "WARN")

        # 6) ring —— 右侧进度环
        if ring:
            try:
                fraction = self._ring_fraction(ring, now)
                width = max(1, int(ring.get("width", 2)))
                rect = QRectF(w - ring_size - 6, (h - ring_size) / 2, ring_size, ring_size)
                rect.adjust(width, width, -width, -width)
                # 轨与弧颜色支持 auto：跟随文字颜色时，轨自动取同色低透明度
                tr_raw = str(ring.get("trackColor", "#E3E8EF"))
                tr_auto = tr_raw.strip().lower() in ("auto", "text")
                track_col = _ink(tr_raw, color, "#E3E8EF")
                track = QPen(_qcolor(track_col, 0.28 if tr_auto else 1.0), width)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(track)
                p.drawEllipse(rect)
                p.setPen(QPen(_qcolor(_ink(ring.get("color"), color, "#2F6DF6")), width,
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(rect, 90 * 16, -int(fraction * 360 * 16))
            except Exception as exc:
                store.log(f"ring 图层跳过: {exc}", "WARN")

        # 7) border —— 最外框，零圆角。padding = 框到字框的间距，不是画布边距
        for d in decs:
            if d.get("type") != "border":
                continue
            try:
                bw = max(1, int(d.get("width", 1)))
                gap = _safe_int(d.get("padding", 10), 10)
                ins = max(bw / 2, pad - gap - bw / 2)     # 框外沿离画布边缘的净距
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(_qcolor(_ink(d.get("color"), color, "#2F6DF6")), bw,
                              _LINE_STYLES.get(str(d.get("style", "solid")), Qt.PenStyle.SolidLine)))
                p.drawRect(QRectF(ins, ins, w - ins * 2, h - ins * 2))
            except Exception as exc:
                store.log(f"border 图层跳过: {exc}", "WARN")

        # 7.5) bracket —— 四角括号（HUD / 取景框），浅色底上做「科技」比深底辉光克制
        for d in decs:
            if d.get("type") != "bracket":
                continue
            try:
                bp = float(_safe_int(d.get("padding", 8), 8))
                ln = float(_safe_int(d.get("length", 18), 18))
                bw = float(max(1, _safe_int(d.get("width", 2), 2)))
                pen = QPen(_qcolor(_ink(d.get("color"), color, "#2F6DF6"),
                                   float(d.get("opacity", 1.0))), bw,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(pen)
                for cx, cy, dx, dy in ((bp, bp, 1, 1), (w - bp, bp, -1, 1),
                                       (bp, h - bp, 1, -1), (w - bp, h - bp, -1, -1)):
                    corner = QPainterPath()
                    corner.moveTo(cx + dx * ln, cy)
                    corner.lineTo(cx, cy)
                    corner.lineTo(cx, cy + dy * ln)
                    p.drawPath(corner)
            except Exception as exc:
                store.log(f"bracket 图层跳过: {exc}", "WARN")
        p.end()

        # 8) effects —— 整体相位（≤30fps 由调用方定时器保证）
        alpha, scale = self._effect_phase(effs, now_ms)
        final_alpha = max(0.0, min(1.0, opacity * alpha))
        if final_alpha >= 0.999 and abs(scale - 1.0) < 0.001:
            result = image
        else:
            # 此时 image 尚未标记 dpr，全部按物理像素合成，避免又被缩放一次
            result = QImage(pw, ph, QImage.Format_ARGB32_Premultiplied)
            result.fill(0)
            p2 = QPainter(result)
            p2.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p2.setOpacity(final_alpha)
            if abs(scale - 1.0) >= 0.001:
                p2.translate(pw / 2, ph / 2)
                p2.scale(scale, scale)
                p2.translate(-pw / 2, -ph / 2)
            p2.drawImage(0, 0, image)
            p2.end()

        # 位图物理尺寸 = 逻辑尺寸 × dpr；标记后 Qt 按逻辑尺寸 1:1 贴屏，不再二次放大
        result.setDevicePixelRatio(dpr)
        if not effs:
            self._cached_key, self._cached_image = cache_key, result
        return result

    @staticmethod
    def _ring_fraction(ring: dict, now: datetime) -> float:
        mode = ring.get("mode", "second")
        if mode == "minute":
            return now.minute / 60.0 + now.second / 3600.0
        if mode == "progress":
            return (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
        return now.second / 60.0

    @staticmethod
    def _effect_phase(effects: list[dict], now_ms: int) -> tuple[float, float]:
        alpha, scale = 1.0, 1.0
        for e in effects:
            typ = e.get("type")
            try:
                if typ == "blink":
                    on, off = float(e.get("onMs", 600)), float(e.get("offMs", 400))
                    alpha *= 1.0 if (now_ms % (on + off)) < on else 0.0
                elif typ == "breath":
                    dur = float(e.get("duration", 2400))
                    lo = float(e.get("minOpacity", 0.5))
                    ph = (now_ms % dur) / dur
                    alpha *= lo + (1 - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
                elif typ == "fade":
                    dur = float(e.get("duration", 1200))
                    a, b = float(e.get("from", 1.0)), float(e.get("to", 0.3))
                    ph = (now_ms % dur) / dur
                    tri = 1 - abs(2 * ph - 1)
                    alpha *= a + (b - a) * tri
                elif typ == "pulse":
                    dur = float(e.get("duration", 1200))
                    amp = float(e.get("scale", 1.05)) - 1.0
                    ph = (now_ms % dur) / dur
                    scale *= 1 + amp * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                store.log(f"effect {typ} 相位跳过: {exc}", "WARN")
        return max(0.0, min(1.0, alpha)), max(0.5, min(1.5, scale))
