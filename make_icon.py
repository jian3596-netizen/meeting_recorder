"""把 icon.svg 渲染为多尺寸 icon.ico。

依赖（dev）：svglib + reportlab + rlPyCairo + pycairo（pycairo 的 Windows
wheel 自带 cairo，无需额外安装系统库）。

用法：
    uv run python make_icon.py
"""

from __future__ import annotations

import io

from PIL import Image
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

SVG = "icon.svg"
ICO = "icon.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    drawing = svg2rlg(SVG)
    scale = 256.0 / drawing.width
    drawing.scale(scale, scale)
    drawing.width *= scale
    drawing.height *= scale

    png_bytes = renderPM.drawToString(drawing, fmt="PNG")
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    img.save(ICO, sizes=SIZES)
    print(f"已生成 {ICO}（尺寸 {[s[0] for s in SIZES]}）")


if __name__ == "__main__":
    main()
