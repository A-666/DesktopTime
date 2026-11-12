# -*- coding: utf-8 -*-
"""生成 DesktopTime 应用图标与 QSS 所需的小箭头贴图。

风格：黑白 IDE 风（零圆角、纯色平涂、无渐变/发光），
蓝色只作为中心一点的强调，面积 < 5%。

产物：
  resources/icons/desktoptime.ico   多尺寸（16~256）应用图标
  resources/icons/desktoptime.png   256×256 预览
  resources/icons/spin_up.png       QSpinBox 上箭头
  resources/icons/spin_down.png     QSpinBox 下箭头

仅构建期需要 Pillow；运行时读现成 PNG / ICO，不依赖 Pillow。
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

SS = 4  # 超采样
INK = "#1f2328"
PAPER = "#ffffff"
EDGE = "#3d444d"
BRAND = "#0969da"
FG_DIM = "#57606a"

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICO_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
             (64, 64), (128, 128), (256, 256)]


def _clock(size: int) -> Image.Image:
    """深色方底 + 白色表盘 + 深色指针 + 蓝色轴心，10:10 定格。"""
    s = size * SS
    img = Image.new("RGBA", (s, s), INK + "FF")
    d = ImageDraw.Draw(img)
    # 1px（最终尺寸）细边，避免深色图标贴在深色任务栏上糊成一团
    edge = max(1, round(s / size))
    d.rectangle([0, 0, s - 1, s - 1], outline=EDGE + "FF", width=edge)

    cx = cy = s / 2
    r = s * 0.345
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PAPER + "FF")

    # 四个整点刻度：让 10:10 的「V」形指针一眼读成时钟，而不是对勾
    tick_w = max(1, round(s * 0.022))
    for ang in (-90, 0, 90, 180):
        a = math.radians(ang)
        x0, y0 = cx + r * 0.78 * math.cos(a), cy + r * 0.78 * math.sin(a)
        x1, y1 = cx + r * 0.92 * math.cos(a), cy + r * 0.92 * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=INK + "FF", width=tick_w)

    def hand(angle_deg: float, length: float, width: float):
        a = math.radians(angle_deg)
        d.line([(cx, cy), (cx + r * length * math.cos(a),
                           cy + r * length * math.sin(a))],
               fill=INK + "FF", width=max(1, int(s * width)))

    hand(-150, 0.52, 0.055)   # 时针 → 10 点方向
    hand(-30, 0.70, 0.045)    # 分针 → 2 点方向
    dot = max(1, s * 0.045)
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=BRAND + "FF")
    return img.resize((size, size), Image.LANCZOS)


def _arrow(up: bool) -> Image.Image:
    """9×5 三角箭头，透明底，供 QSpinBox::up-arrow / ::down-arrow 使用。"""
    w, h = 9, 5
    s = SS
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if up:
        pts = [(w * s / 2, 0), (w * s, h * s), (0, h * s)]
    else:
        pts = [(0, 0), (w * s, 0), (w * s / 2, h * s)]
    d.polygon(pts, fill=FG_DIM + "FF")
    return img.resize((w, h), Image.LANCZOS)


def _check() -> Image.Image:
    """12×12 勾选标记，供 QCheckBox::indicator:checked 使用。"""
    n, s = 12, SS
    img = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(1.5 * s, 6.5 * s), (4.5 * s, 9.5 * s), (10.5 * s, 2.5 * s)]
    d.line(pts, fill="#0550ae" + "FF", width=max(2, round(1.8 * s)), joint="curve")
    return img.resize((n, n), Image.LANCZOS)


def _chevron() -> Image.Image:
    """9×6 下拉箭头，供 QComboBox::down-arrow 使用。

    theme.py 里给 QComboBox 定制过 ::drop-down / ::down-arrow 之后，
    原生三角就不再绘制；不给图片的话所有下拉框看起来都像纯输入框。
    """
    w, h, s = 9, 6, SS
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(1 * s, 1.5 * s), (4.5 * s, 4.5 * s), (8 * s, 1.5 * s)],
           fill="#57606a" + "FF", width=max(2, round(1.4 * s)), joint="curve")
    return img.resize((w, h), Image.LANCZOS)


def main() -> None:
    big = _clock(256)
    big.save(OUT / "desktoptime.png")
    # ICO 用 Pillow 写出 BMP 格式条目 —— PyInstaller 的 ICO 解析器只认这种，
    # PNG 压缩条目在打包阶段会失败。
    big.save(OUT / "desktoptime.ico", format="ICO", sizes=ICO_SIZES)
    _arrow(True).save(OUT / "spin_up.png")
    _arrow(False).save(OUT / "spin_down.png")
    _check().save(OUT / "check.png")
    _chevron().save(OUT / "combo_down.png")

    ico = OUT / "desktoptime.ico"
    print(f"ICO  {ico}  {ico.stat().st_size} bytes  sizes={[s[0] for s in ICO_SIZES]}")
    print(f"PNG  {OUT / 'desktoptime.png'}")
    for name in ("spin_up.png", "spin_down.png", "check.png", "combo_down.png"):
        print(f"ASSET {OUT / name}")


if __name__ == "__main__":
    main()
