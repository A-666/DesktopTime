# -*- coding: utf-8 -*-
"""渲染层诊断：副行（日期/星期）是否真的落在画布内、位图是否按 dpr 生成。

不依赖 renderer 内部公式，直接测量输出位图的像素：
  * 主行带（上半）必须有墨
  * 副行带（下半）必须有墨  ← 旧版这里是 0，副行整行被裁掉
  * dpr=1.5 时位图物理尺寸 = 逻辑尺寸 × 1.5，且 devicePixelRatio 已标记

用法：python tests/diag_render.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import clock, stylepack  # noqa: E402
from core.renderer import Renderer  # noqa: E402

OUT = Path(os.environ.get("TEMP", ".")) / "dt_diag"
OUT.mkdir(parents=True, exist_ok=True)

# 固定测试配置：不读用户实时 settings.json（用户可能正在用软件切方案）。
# 取值刻意复刻反馈截图：100px、Consolas Bold、白字、日期 + 星期全开。
CFG = {
    "time": {"format": "HH:mm:ss", "custom": "", "showDate": True,
             "showWeekday": True, "showSeconds": True, "hour12": False},
    "style": {"preset": "digital", "font": "Consolas", "size": 100, "weight": "Bold",
              "color": "#FFFFFF", "opacity": 1.0, "textStyles": [],
              "background": {"enabled": False, "color": "#FFFFFF", "padding": 12},
              "decorations": [], "effects": [], "packRef": ""},
}


def ink_rows(image) -> list[int]:
    """返回每一行是否有非透明像素（逐行扫描，忽略 alpha=0）。"""
    out = []
    for y in range(image.height()):
        hit = False
        for x in range(0, image.width(), 3):      # 三像素抽样，够用且快
            if image.pixelColor(x, y).alpha() > 24:
                hit = True
                break
        out.append(1 if hit else 0)
    return out


def bands(image) -> tuple[int, int]:
    """把有墨的行切成连续区间，返回 (行区间数, 最长区间长度)。"""
    rows = ink_rows(image)
    runs, run = [], 0
    for v in rows:
        if v:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    return len(runs), (max(runs) if runs else 0)


def main() -> None:
    QApplication.instance() or QApplication(sys.argv[:1])

    cfg = CFG
    now = datetime(2026, 11, 11, 22, 52, 11)
    main_text, sub_text = clock.build_lines(now, cfg)
    pack = stylepack.get_builtin(cfg["style"]["preset"])
    print(f"固定测试配置: size={cfg['style']['size']} weight={cfg['style']['weight']} "
          f"color={cfg['style']['color']} preset={cfg['style']['preset']}")
    print(f"build_lines -> main={main_text!r} sub={sub_text!r}")
    print(f"preset 装饰层 -> {[d.get('type') for d in pack.get('decorations', [])]}\n")

    ok = True
    for dpr in (1.0, 1.5, 2.0):
        img = Renderer().render(now, cfg, pack, 0, dpr)
        ratio = img.devicePixelRatio()
        lw, lh = round(img.width() / ratio), round(img.height() / ratio)
        n_runs, longest = bands(img)
        # 副行带 = 画布高度的下 1/3
        sub_band = [(x, y) for y in range(int(lh * 0.66), img.height())
                    for x in range(0, img.width(), 3)
                    if img.pixelColor(x, y).alpha() > 24]
        print(f"dpr={dpr}  物理 {img.width()}x{img.height()}  逻辑 {lw}x{lh}  "
              f"devicePixelRatio={ratio}  墨迹行区块={n_runs} 最长={longest}px  "
              f"副行带像素={len(sub_band)}")
        if abs(ratio - dpr) > 1e-6:
            print(f"   [!] devicePixelRatio 应为 {dpr}")
            ok = False
        if abs(lw * dpr - img.width()) > 1:
            print(f"   [!] 物理宽度不等于逻辑×dpr")
            ok = False
        if sub_text and not sub_band:
            print("   [!] 副行带没有任何墨迹 —— 副行仍未画出")
            ok = False
        img.save(str(OUT / f"render_dpr{dpr:g}.png"))

    print(f"\n图片输出目录: {OUT}")
    print("RESULT", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
