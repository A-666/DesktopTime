# -*- coding: utf-8 -*-
"""时间格式串解析与文本排版。不依赖 GUI。"""
from __future__ import annotations

import re
from datetime import datetime

WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
WEEKDAY_SHORT = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

FORMAT_PRESETS = (
    # 标签里不写「24 小时 / 12 小时」——那是下面那个开关的职责，写在这里会和
    # 开关打架：下拉说「24 小时」，开关却开着 12 小时制，用户不知道谁说了算
    ("HH:mm:ss", "时分秒"),
    ("HH:mm", "时分"),
    ("hh:mm tt", "时分 + 上下午"),
    ("HH:mm:ss dddd", "时分秒 + 星期"),
    ("yyyy-MM-dd HH:mm:ss", "完整日期时间"),
)


def _tokens(now: datetime, hour12: bool = False) -> dict[str, str]:
    """时间标记表。

    `hour12` 是总开关，打开时压过格式串里的标记选择：HH / H / hh / h 一律
    输出 12 小时值。这样拨开关必定有可见变化，不会出现「格式串写了 hh:mm tt
    就再也关不掉 12 小时」的僵局。

    关闭时不改写任何标记，尊重格式串本身的意图 —— `HH:mm` 是 24 小时、
    `hh:mm tt` 是 12 小时，那本来就是用户挑这个格式时想要的。

    12 小时制下小时一律不补前导零：`6:35` 而不是 `06:35`。中文用户日常看到的
    钟点就是这么写的，补零反而像是把 24 小时制的写法硬套过来。
    """
    h24 = now.hour
    h12 = h24 % 12 or 12
    if hour12:
        # 开关打开：四个小写/大写标记全部让位给 12 小时值，且不补前导零 ——
        # 12 小时制的钟点写作 6:35，不是 06:35
        big_fat = big_thin = small_fat = small_thin = str(h12)
    else:
        # 开关关闭：尊重格式串本身 —— HH / hh 补零，H / h 不补零
        big_fat, big_thin = f"{h24:02d}", str(h24)
        small_fat, small_thin = f"{h12:02d}", str(h12)
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
        "HH": big_fat,
        "H": big_thin,
        "hh": small_fat,
        "h": small_thin,
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
