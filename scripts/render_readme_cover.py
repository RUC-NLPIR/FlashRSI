#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools==4.60.1"]
# ///
"""Generate the minimal, self-contained README cover SVG.

Run with uv run --script scripts/render_readme_cover.py. The cover.png file is a
separately rasterized preview of the same SVG.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

WIDTH, HEIGHT = 1600, 440
BACKGROUND = "#080B10"
WHITE = "#F3F5F7"
BLUE = "#8AB8E8"
ORANGE = "#DDA57B"


def wordmark():
    font_path = Path(__file__).resolve().parents[1] / "assets/fonts/SpaceGrotesk.ttf"
    with TTFont(font_path) as font:
        glyphs = font.getGlyphSet(location={"wght": 700})
        cmap = font.getBestCmap()
        pen = SVGPathPen(glyphs)
        cursor = 0
        for character in "FlashRSI":
            glyph = glyphs[cmap[ord(character)]]
            glyph.draw(TransformPen(pen, (1, 0, 0, 1, cursor, 0)))
            cursor += glyph.width - font["head"].unitsPerEm * 0.0173
        scale = 104 / font["head"].unitsPerEm
        return f'<path transform="translate(118 237) scale({scale} {-scale})" fill="{WHITE}" d="{pen.getCommands()}"/>'


def render():
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="cover-title cover-desc">
  <title id="cover-title">FlashRSI — Improve the agent you already have.</title>
  <desc id="cover-desc">A white FlashRSI wordmark and three paths that branch apart and converge into a new direction, on a plain dark background.</desc>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>
  {wordmark()}
  <g font-family="Arial, Helvetica, sans-serif">
    <text x="124" y="289" fill="#929EAD" font-size="23">Improve the agent you already have.</text>
  </g>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M1016 267 C1068 267 1064 132 1125 132 H1190 C1260 132 1256 183 1328 183" stroke="#526B88" stroke-width="3"/>
    <path d="M1016 267 C1050 267 1052 310 1100 310 H1190 C1270 310 1260 183 1328 183" stroke="#2D3A4B" stroke-width="3"/>
    <path d="M1016 267 C1064 267 1084 205 1136 205 H1208 C1258 205 1272 183 1328 183" stroke="{BLUE}" stroke-width="4.5"/>
    <path d="M1328 183 H1348" stroke="{ORANGE}" stroke-width="4.5"/>
  </g>
</svg>
'''


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "assets/readme/cover.svg"
    path.write_text(render(), encoding="utf-8")
    print(path)
