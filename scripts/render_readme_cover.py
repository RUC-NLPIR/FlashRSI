#!/usr/bin/env python3
"""Build the deterministic, self-contained particle-galaxy README cover.

Run from any directory with Python 3.11+. The SVG is the editable source;
cover.png is a separately rasterized preview of the same artwork.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

WIDTH, HEIGHT = 1600, 520
BACKGROUND = "#03080D"
WHITE = "#F5FAFF"
BLUE = "#76CFFF"
ORANGE = "#F2A16B"


def render():
    rng = random.Random(20261028)
    stars = []
    lights = []

    def star(x, y, radius, color, opacity, luminous=False):
        if not (-12 < x < WIDTH + 12 and -12 < y < HEIGHT + 12):
            return
        if luminous:
            lights.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius * 5.8:.2f}" '
                f'fill="url(#{"warm" if color == ORANGE else "cold"}-halo)" '
                f'opacity="{opacity:.2f}"/>'
            )
        stars.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
            f'fill="{color}" opacity="{opacity:.2f}"/>'
        )

    def project(x, y):
        # Tilt the disk to give the arms depth while retaining broad open space.
        angle = -0.28
        return (
            1070 + x * math.cos(angle) - y * 0.68 * math.sin(angle),
            278 + x * math.sin(angle) + y * 0.68 * math.cos(angle),
        )

    for _ in range(260):
        x, y = rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT)
        star(
            x,
            y,
            rng.uniform(0.35, 0.85),
            rng.choice((BLUE, WHITE, ORANGE)),
            rng.uniform(0.12, 0.45),
        )

    # Uneven arm density and a broad diffuse population keep the disk organic.
    for _ in range(5200):
        u = rng.random() ** 0.78
        radius = 24 + 555 * u
        angle = 0.9 + 7.8 * u + rng.choice((0, math.tau / 3, 2 * math.tau / 3))
        spread = 6 + 25 * u
        x = radius * math.cos(angle) + rng.gauss(0, spread)
        y = radius * math.sin(angle) + rng.gauss(0, spread)
        px, py = project(x, y)
        size = rng.uniform(0.40, 1.08)
        color = rng.choices((BLUE, WHITE, ORANGE), weights=(0.50, 0.27, 0.23))[0]
        opacity = rng.uniform(0.40, 0.94)
        if rng.random() < 0.030:
            size = rng.uniform(1.4, 2.7)
            opacity = rng.uniform(0.78, 1)
            color = rng.choices((WHITE, BLUE, ORANGE), weights=(0.65, 0.18, 0.17))[0]
        star(px, py, size, color, opacity, luminous=size > 1.2)

    for _ in range(900):
        radius = min(540, abs(rng.gauss(0, 225)))
        angle = rng.uniform(0, math.tau)
        px, py = project(radius * math.cos(angle), radius * math.sin(angle))
        star(
            px,
            py,
            rng.uniform(0.28, 0.75),
            rng.choice((BLUE, WHITE, ORANGE)),
            rng.uniform(0.15, 0.50),
        )

    for _ in range(230):
        px, py = project(rng.gauss(0, 22), rng.gauss(0, 16))
        size = rng.uniform(0.55, 2.05)
        star(px, py, size, WHITE, rng.uniform(0.45, 1), luminous=size > 1.15)

    light_markup = "\n    ".join(lights)
    star_markup = "\n    ".join(stars)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="cover-title cover-desc">
  <title id="cover-title">FlashRSI — Improve the agent you already have.</title>
  <desc id="cover-desc">A spiral galaxy of blue, white, and orange stars surrounds a luminous stellar core. Minimal white FlashRSI lettering sits against deep black space.</desc>
  <defs>
    <radialGradient id="cold-halo">
      <stop stop-color="#F5FAFF" stop-opacity=".68"/>
      <stop offset=".16" stop-color="#A8DFFF" stop-opacity=".34"/>
      <stop offset=".5" stop-color="#76CFFF" stop-opacity=".09"/>
      <stop offset="1" stop-color="#76CFFF" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="warm-halo">
      <stop stop-color="#FFF5EB" stop-opacity=".65"/>
      <stop offset=".16" stop-color="#F2A16B" stop-opacity=".32"/>
      <stop offset=".5" stop-color="#F2A16B" stop-opacity=".08"/>
      <stop offset="1" stop-color="#F2A16B" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="core-haze">
      <stop stop-color="#F5FAFF" stop-opacity=".28"/>
      <stop offset=".15" stop-color="#D6EBFA" stop-opacity=".19"/>
      <stop offset=".4" stop-color="#7BB1D0" stop-opacity=".06"/>
      <stop offset="1" stop-color="#76CFFF" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="text-space">
      <stop stop-color="{BACKGROUND}"/>
      <stop offset=".42" stop-color="{BACKGROUND}" stop-opacity=".98"/>
      <stop offset=".74" stop-color="{BACKGROUND}" stop-opacity=".42"/>
      <stop offset="1" stop-color="{BACKGROUND}" stop-opacity="0"/>
    </linearGradient>
    <style>
      .stellar-light {{animation: shimmer 7s ease-in-out infinite alternate;}}
      @keyframes shimmer {{from {{opacity: .72;}} to {{opacity: 1;}}}}
      @media (prefers-reduced-motion: reduce) {{.stellar-light {{animation: none;}}}}
    </style>
  </defs>
  <rect width="1600" height="520" fill="{BACKGROUND}"/>
  <ellipse cx="1070" cy="278" rx="350" ry="210" fill="url(#core-haze)" transform="rotate(-16 1070 278)"/>
  <g class="stellar-light">
    {light_markup}
  </g>
  <g>
    {star_markup}
  </g>
  <rect width="810" height="520" fill="url(#text-space)"/>
  <g font-family="Arial, Helvetica, sans-serif" fill="{WHITE}">
    <text x="94" y="254" font-size="86" font-weight="400" letter-spacing="-3">FlashRSI</text>
    <text x="99" y="302" font-size="23" fill="#B8C6D2" letter-spacing=".1">Improve the agent you already have.</text>
  </g>
</svg>
'''


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "assets/readme/cover.svg"
    path.write_text(render(), encoding="utf-8")
    print(path)
