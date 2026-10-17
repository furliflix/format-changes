# -*- coding: utf-8 -*-
"""生成 Format Changes 的应用图标。

风格（--style）：
    arrows（默认）：双向箭头 ⇄      —— 小尺寸下最清晰
    cycle         ：循环箭头 ⟳

配色（--scheme）：
    dark（默认）：黑底白箭头（黑白版）
    light        ：白底黑箭头（黑白版）
    blue         ：蓝紫渐变底白箭头（彩色版）

绘制采用 4 倍超采样（先画 4096，再缩小到 1024），边缘平滑无锯齿。

产出：
    assets/icon_1024.png / icon_256.png / AppIcon.ico
    packaging/AppIcon.iconset/*.png   （macOS 打包脚本用 iconutil 转成 .icns）

想用自己（Affinity）画的图标：
    把 1024x1024、四周留 ~96px 空白的透明 PNG 覆盖 assets/icon_1024.png，
    然后运行：python packaging/make_icon.py --from assets/icon_1024.png

用法：
    python packaging/make_icon.py                      # 默认：黑白箭头
    python packaging/make_icon.py --scheme light       # 白底黑箭头
    python packaging/make_icon.py --scheme blue        # 蓝紫渐变色
    python packaging/make_icon.py --style cycle        # 环形风格
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICONSET = ROOT / "packaging" / "AppIcon.iconset"

SIZE = 1024
SS = 4                   # 超采样倍数
PAD = 96                 # 四周留白（macOS 图标规范）
RADIUS = 200

# 配色方案：底色渐变（上 -> 下）与图形颜色
SCHEMES = {
    "dark":  {"c1": (46, 46, 48), "c2": (10, 10, 12), "fg": (255, 255, 255)},
    "light": {"c1": (252, 252, 252), "c2": (226, 228, 232), "fg": (24, 24, 26)},
    "blue":  {"c1": (46, 107, 230), "c2": (124, 58, 237), "fg": (255, 255, 255)},
}


# ---------------------------------------------------------------- 背景

def _gradient(size: int, c1: tuple, c2: tuple) -> Image.Image:
    strip = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        strip.putpixel((0, y), (
            round(c1[0] + (c2[0] - c1[0]) * t),
            round(c1[1] + (c2[1] - c1[1]) * t),
            round(c1[2] + (c2[2] - c1[2]) * t),
        ))
    return strip.resize((size, size))


def _rounded_mask(size: int, pad: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, size - 1 - pad, size - 1 - pad], radius=radius, fill=255)
    return mask


# ---------------------------------------------------------------- 风格一：⇄

def _draw_arrows(draw: ImageDraw.ImageDraw, k: float, fg: tuple) -> None:
    def box(x0, y0, x1, y1):
        return [x0 * k, y0 * k, x1 * k, y1 * k]

    def pts(*xy):
        return [(x * k, y * k) for x, y in xy]

    # 上面的箭头：向右 →
    draw.rounded_rectangle(box(252, 371, 700, 435), radius=32 * k, fill=fg)
    draw.polygon(pts((688, 306), (840, 403), (688, 500)), fill=fg)
    # 下面的箭头：向左 ←
    draw.rounded_rectangle(box(324, 589, 772, 653), radius=32 * k, fill=fg)
    draw.polygon(pts((336, 524), (184, 621), (336, 718)), fill=fg)


# ---------------------------------------------------------------- 风格二：⟳

def _arc_arrow(draw, k, fg, cx, cy, r, start, end, width, head_len, head_w) -> None:
    """一段圆弧 + 结束处的切线箭头 + 开始处的圆头端点。"""
    cx_k, cy_k, r_k = cx * k, cy * k, r * k
    w_k = width * k
    draw.arc(
        [cx_k - r_k, cy_k - r_k, cx_k + r_k, cy_k + r_k],
        start, end, fill=fg, width=round(w_k),
    )

    def point(angle):
        th = math.radians(angle)
        return cx_k + r_k * math.cos(th), cy_k + r_k * math.sin(th)

    # 结束角度：箭头
    px, py = point(end)
    th = math.radians(end)
    dx, dy = -math.sin(th), math.cos(th)          # 切线方向（角度增大方向）
    nx, ny = math.cos(th), math.sin(th)           # 径向
    hl, hw = head_len * k, head_w * k
    draw.polygon([
        (px + dx * hl, py + dy * hl),
        (px + nx * hw / 2, py + ny * hw / 2),
        (px - nx * hw / 2, py - ny * hw / 2),
    ], fill=fg)

    # 开始角度：圆头端点
    sx, sy = point(start)
    draw.ellipse([sx - w_k / 2, sy - w_k / 2, sx + w_k / 2, sy + w_k / 2], fill=fg)


def _draw_cycle(draw: ImageDraw.ImageDraw, k: float, fg: tuple) -> None:
    cx = cy = 512
    r = 252
    width = 76
    head_len = 100
    head_w = 172
    _arc_arrow(draw, k, fg, cx, cy, r, 205, 335, width, head_len, head_w)   # 上半圈：左 → 右
    _arc_arrow(draw, k, fg, cx, cy, r, 25, 155, width, head_len, head_w)    # 下半圈：右 → 左


STYLES = {"arrows": _draw_arrows, "cycle": _draw_cycle}


# ---------------------------------------------------------------- 生成

def _render(style: str, scheme: str) -> Image.Image:
    """4 倍超采样绘制，缩小到 1024 得到平滑边缘。"""
    colors = SCHEMES[scheme]
    s = SIZE * SS
    base = _gradient(s, colors["c1"], colors["c2"]).convert("RGBA")
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    STYLES[style](ImageDraw.Draw(layer), float(SS), colors["fg"])
    base.alpha_composite(layer)

    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    icon.paste(base, (0, 0), _rounded_mask(s, PAD * SS, RADIUS * SS))
    return icon.resize((SIZE, SIZE), Image.LANCZOS)


def _load_source(source: Path) -> Image.Image:
    img = Image.open(str(source)).convert("RGBA")
    if img.size != (SIZE, SIZE):
        img = img.resize((SIZE, SIZE), Image.LANCZOS)
    return img


def build(style: str = "arrows", scheme: str = "dark", source: Path | None = None) -> None:
    icon = _load_source(source) if source is not None else _render(style, scheme)

    ASSETS.mkdir(exist_ok=True)
    icon.save(ASSETS / "icon_1024.png")
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon_256.png")
    icon.save(ASSETS / "AppIcon.ico",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])

    ICONSET.mkdir(parents=True, exist_ok=True)
    specs = [
        ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
    ]
    for name, px in specs:
        icon.resize((px, px), Image.LANCZOS).save(ICONSET / name)

    print(f"图标已生成（{scheme} / {style}）：")
    print(f"  {ASSETS / 'icon_1024.png'}")
    print(f"  {ASSETS / 'icon_256.png'}")
    print(f"  {ASSETS / 'AppIcon.ico'}")
    print(f"  {ICONSET}  （10 个尺寸，供 macOS iconutil 使用）")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Format Changes 的应用图标")
    ap.add_argument("--style", choices=sorted(STYLES), default="arrows",
                    help="图形风格（默认 arrows 双向箭头）")
    ap.add_argument("--scheme", choices=sorted(SCHEMES), default="dark",
                    help="配色（默认 dark 黑底白箭头）")
    ap.add_argument("--from", dest="source", type=Path, default=None,
                    help="用一张 1024x1024 的现成 PNG 生成全部尺寸（比如 Affinity 导出的）")
    args = ap.parse_args()
    build(style=args.style, scheme=args.scheme, source=args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
