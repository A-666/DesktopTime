# -*- coding: utf-8 -*-
"""时间格式串解析与文本排版。不依赖 GUI。"""
from __future__ import annotations

import re
from datetime import datetime

WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
WEEKDAY_SHORT = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

FORMAT_PRESETS = (
    ("HH:mm:ss", "24 小时 · 时分秒"),
    ("HH:mm", "24 小时 · 时分"),
    ("hh:mm tt", "12 小时 · 上下午"),
    ("HH:mm:ss dddd", "带星期"),
    ("yyyy-MM-dd HH:mm:ss", "完整日期时间"),
)


def _tokens(now: datetime, hour12: bool = False) -> dict[str, str]:
    h24 = now.hour
    h12 = h24 % 12 or 12
    hour = h12 if hour12 else h24
    ampm = "AM" if h24 < 12 else "PM"
    return {
        "yyyy": f"{now.year:04d}",
        "yy": f"{now.year % 100:02d}",
        "MM": f"{now.month:02d}",
        "M": str(now.month),
        "dddd": WEEKDAY_CN[now.weekday()],
        "ddd": WEEKDAY_SHORT[now.weekday()],
        "dd": f"{now.day:02d}",
        "d": str(now.day),
        "HH": f"{hour:02d}",
        "H": str(hour),
        "hh": f"{h12:02d}",
        "h": str(h12),
        "mm": f"{now.minute:02d}",
        "m": str(now.minute),
        "ss": f"{now.second:02d}",
        "s": str(now.second),
        "tt": ampm,
        "AP": ampm,
    }


_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(_tokens(datetime(2000, 1, 1)), key=len, reverse=True))
)


def apply_format(fmt: str, now: datetime, hour12: bool = False) -> str:
    """按 token 长度降序一次性替换，避免 mm / m 之类前缀互相吞掉。"""
    tokens = _tokens(now, hour12)
    return _PATTERN.sub(lambda m: tokens[m.group()], fmt)


def _strip_seconds(fmt: str) -> str:
    for frag in (":ss", ":s", "ss", "s"):
        fmt = fmt.replace(frag, "")
    return fmt.rstrip(" :")


def build_lines(now: datetime, cfg: dict) -> tuple[str, str | None]:
    """返回 (主行, 副行)。副行由 showDate / showWeekday 生成。"""
    t = cfg.get("time", {})
    fmt = (t.get("custom") or t.get("format") or "HH:mm:ss").strip() or "HH:mm:ss"
    if not t.get("showSeconds", True):
        fmt = _strip_seconds(fmt) or "HH:mm"
    hour12 = bool(t.get("hour12", False))
    main = apply_format(fmt, now, hour12)
    if hour12 and "tt" not in fmt and "AP" not in fmt:
        main = f"{main} {'AM' if now.hour < 12 else 'PM'}"
    parts: list[str] = []
    if t.get("showDate"):
        parts.append(f"{now.year:04d}-{now.month:02d}-{now.day:02d}")
    if t.get("showWeekday"):
        parts.append(WEEKDAY_CN[now.weekday()])
    return main, ("  ".join(parts) if parts else None)
