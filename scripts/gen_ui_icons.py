#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 UI 用到的小图标（可复现，避免仓库里出现来路不明的二进制）。

目前生成：
    ui/img/icons/combo_arrow_white.png —— 下拉框的白色向下箭头

为什么需要它：QSS 的 ``QComboBox::down-arrow`` 默认使用系统原生箭头，
在深色背景的下拉框上呈暗色、几乎看不见。QSS 也无法像网页 CSS 那样
用 border 画三角形（Qt 不支持该技巧），因此用一张白色箭头图片。

用法：
    python scripts/gen_ui_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ICON_DIR = REPO / "ui" / "img" / "icons"

#: 超采样倍数：先大尺寸绘制再缩小，得到平滑边缘
_SUPERSAMPLE = 4
#: 最终尺寸（QSS 里按 12x12 使用，这里给大一点以适配 HiDPI）
_SIZE = 20


def make_chevron(path: Path, size: int = _SIZE, color: str = "#FFFFFF",
                 thickness: float = 0.19) -> None:
    """画一个向下的人字形箭头（chevron），透明背景。

    注意：人字形要**尽量占满画布**。之前留白太多（只在中间画一小块），
    在 QSS 里缩到 12x12 后只剩 7x4 像素，又细又淡、照样看不清。
    """
    from PIL import Image, ImageDraw

    s = size * _SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    w = max(3, int(s * thickness))
    # 左右顶点贴近边缘、中点在下方，使箭头在画布内尽可能大
    left = (s * 0.13, s * 0.28)
    mid = (s * 0.50, s * 0.72)
    right = (s * 0.87, s * 0.28)

    d.line([left, mid, right], fill=color, width=w, joint="curve")
    # 两端补圆点，避免线宽造成的方角
    r = w / 2
    for (x, y) in (left, right):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)

    img = img.resize((size, size), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"  已生成 {path.relative_to(REPO)}  ({size}x{size})")


def main() -> int:
    print("生成 UI 图标...")
    make_chevron(ICON_DIR / "combo_arrow_white.png")
    make_chevron(ICON_DIR / "combo_arrow_dim.png", color="#C8CDD8")
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
