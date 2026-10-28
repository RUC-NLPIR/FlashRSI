#!/usr/bin/env python3
"""Generate the minimal, self-contained README cover SVG.

Run with Python 3.11+. The particle motif is deterministic; cover.png is a
separately rasterized preview of the same SVG.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

WIDTH, HEIGHT = 1600, 440
BACKGROUND = "#080B10"
WHITE = "#F3F5F7"
BLUE = "#8AB8E8"
ORANGE = "#DDA57B"


def render():
    rng = random.Random(20261028)
    stars = []
    for _ in range(300):
        distance = rng.random()
        radius = 18 + 177 * distance
        angle = 5.7 * distance + rng.choice((0, math.pi))
        angle += rng.gauss(0, 0.15)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle) * 0.62
        tilt = -0.4
        px = 1162 + x * math.cos(tilt) - y * math.sin(tilt)
        py = 221 + x * math.sin(tilt) + y * math.cos(tilt)
        size = rng.uniform(0.65, 1.3)
        color = rng.choices((WHITE, BLUE, ORANGE), weights=(0.70, 0.26, 0.04))[0]
        opacity = rng.uniform(0.22, 0.8)
        stars.append(
            f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{size:.2f}" '
            f'fill="{color}" opacity="{opacity:.2f}"/>'
        )
    particles = "\n    ".join(stars)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="cover-title cover-desc">
  <title id="cover-title">FlashRSI — Improve the agent you already have.</title>
  <desc id="cover-desc">A white FlashRSI wordmark and a small, quiet spiral of blue-white points on a plain dark background.</desc>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>
  <g font-family="Arial, Helvetica, sans-serif">
    <text x="118" y="237" fill="{WHITE}" font-size="104" font-weight="400" letter-spacing="-4">FlashRSI</text>
    <text x="124" y="289" fill="#929EAD" font-size="23">Improve the agent you already have.</text>
  </g>
  <g>
    {particles}
  </g>
</svg>
'''


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "assets/readme/cover.svg"
    path.write_text(render(), encoding="utf-8")
    print(path)
