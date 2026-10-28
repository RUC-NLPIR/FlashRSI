#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools==4.60.1", "Pillow==11.3.0"]
# ///
"""Render two original looping line covers inspired by React Bits.

References: https://reactbits.dev/backgrounds/threads
            https://reactbits.dev/backgrounds/floating-lines
The curves use periodic trigonometric motion for a seamless offline GIF;
no React Bits component or shader code is included.

    uv run --script scripts/render_readme_cover.py
    uv run --script scripts/render_readme_cover.py --style floating
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

WIDTH, HEIGHT, SCALE = 1600, 440, 2
BACKGROUND = "#080B10"
WHITE = "#F3F5F7"
BLUE = "#8AB8E8"
FRAMES, FRAME_MS = 100, 70
POSTER_PHASE = 0.24
ROOT = Path(__file__).resolve().parents[1]
BRAND_FONT = ROOT / "assets/fonts/SpaceGrotesk.ttf"


def wordmark():
    with TTFont(BRAND_FONT) as font:
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


def strands(style, phase):
    """Return geometry in cover coordinates, color, opacity, and line width."""
    angle = math.tau * phase
    samples = [index / 399 for index in range(400)]
    if style == "threads":
        for line in range(24):
            p = line / 23
            points = []
            for u in samples:
                spread = 6 + 125 * u**1.3
                envelope = max(0, min(1, (u - 0.08 - 0.20 * p) / 0.58))
                envelope = envelope**2 * (3 - 2 * envelope)
                wave = math.sin(5.5 * u + 1.7 * p + angle)
                wave += 0.28 * math.sin(9 * u - 2.1 * p - angle)
                y = 255 - 85 * u + (p - 0.5) * spread + envelope * wave * 62
                points.append((810 + 860 * u, y))
            color = tuple(
                round(start * (1 - p) + end * p)
                for start, end in zip((217, 231, 244), (105, 165, 220))
            )
            yield points, color, round(100 + 85 * (1 - p)), 2
    else:
        for bundle in (1, 0):
            for line in range(6):
                slot = line - 2.5
                points = []
                for u in samples:
                    if bundle == 0:
                        center = 184 + 49 * math.sin(2.2 * math.pi * u - angle)
                        center += 26 * math.sin(math.pi * u + angle)
                        spread = slot * (5.2 + 7.6 * math.sin(math.pi * u) ** 2)
                        spread *= math.cos(1.5 * math.pi * u - angle)
                        y = center + spread + 18 * (u - 0.5)
                    else:
                        center = 286 - 55 * math.sin(1.8 * math.pi * u + angle)
                        center += 13 * math.sin(2 * math.pi * u - angle)
                        spread = slot * (4.8 + 5 * math.sin(math.pi * u) ** 2)
                        spread *= math.cos(1.6 * math.pi * u + angle)
                        y = center + spread
                    points.append((797 + 820 * u, y))
                if bundle == 0:
                    mix = line / 5 * 0.48
                    color = tuple(
                        round(start * (1 - mix) + end * mix)
                        for start, end in zip((138, 184, 232), (215, 231, 246))
                    )
                    strength = 0.72 + 0.19 * math.sin(angle + line * 0.28) ** 2
                else:
                    color = tuple(
                        round(c * (0.75 + 0.25 * line / 5)) for c in (191, 145, 114)
                    )
                    strength = 0.38 + 0.12 * math.sin(angle + line * 0.25) ** 2
                yield points, color, round(255 * strength), 1.2


def render(style="threads", phase=POSTER_PHASE):
    paths = []
    for points, color, alpha, width in strands(style, phase):
        path = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points)
        rgb = "#" + "".join(f"{value:02x}" for value in color)
        paths.append(
            f'<path d="{path}" stroke="{rgb}" opacity="{alpha / 255:.3f}" stroke-width="{width}"/>'
        )
    artwork = "\n    ".join(paths)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="cover-title cover-desc">
  <title id="cover-title">FlashRSI — Improve the agent you already have.</title>
  <desc id="cover-desc">A white FlashRSI wordmark beside flowing blue-white strands. Static preview of the looping cover animation.</desc>
  <defs>
    <linearGradient id="flow-fade" gradientUnits="userSpaceOnUse" x1="805" x2="1588">
      <stop stop-color="white" stop-opacity="0"/>
      <stop offset=".166" stop-color="white"/>
      <stop offset=".853" stop-color="white"/>
      <stop offset="1" stop-color="white" stop-opacity="0"/>
    </linearGradient>
    <mask id="flow-mask"><rect width="1600" height="440" fill="url(#flow-fade)"/></mask>
  </defs>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>
  {wordmark()}
  <text x="124" y="289" fill="#929EAD" font-family="Arial, Helvetica, sans-serif" font-size="23">Improve the agent you already have.</text>
  <g fill="none" stroke-linejoin="round" mask="url(#flow-mask)">
    {artwork}
  </g>
</svg>
'''


class Cover:
    def __init__(self, style):
        self.style = style
        self.base = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), BACKGROUND)
        draw = ImageDraw.Draw(self.base)
        brand = ImageFont.truetype(str(BRAND_FONT), 104 * SCALE)
        brand.set_variation_by_axes([700])
        x = 118 * SCALE
        for character in "FlashRSI":
            draw.text((x, 237 * SCALE), character, font=brand, fill=WHITE, anchor="ls")
            x += brand.getlength(character) - 1.8 * SCALE
        body_font = next(
            path
            for path in (
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "C:/Windows/Fonts/arial.ttf",
            )
            if Path(path).exists()
        )
        draw.text(
            (124 * SCALE, 289 * SCALE),
            "Improve the agent you already have.",
            font=ImageFont.truetype(body_font, 23 * SCALE),
            fill="#929EAD",
            anchor="ls",
        )
        row = Image.new("L", (WIDTH * SCALE, 1))
        row.putdata(
            [
                round(
                    255
                    * max(0, min(1, (x / SCALE - 805) / 130))
                    * max(0, min(1, (1588 - x / SCALE) / 115))
                )
                for x in range(WIDTH * SCALE)
            ]
        )
        self.fade = row.resize(self.base.size)

    def frame(self, phase):
        layer = Image.new("RGBA", self.base.size)
        draw = ImageDraw.Draw(layer)
        for points, color, alpha, width in strands(self.style, phase):
            draw.line(
                [(x * SCALE, y * SCALE) for x, y in points],
                fill=(*color, alpha),
                width=round(width * SCALE),
                joint="curve",
            )
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), self.fade))
        image = Image.alpha_composite(self.base.convert("RGBA"), layer)
        return image.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", choices=("threads", "floating"), default="threads")
    parser.add_argument("--poster-only", action="store_true")
    args = parser.parse_args()
    name = "cover" if args.style == "threads" else "cover-floating"
    target = ROOT / "assets/readme" / name
    target.with_suffix(".svg").write_text(render(args.style), encoding="utf-8")
    cover = Cover(args.style)
    first = cover.frame(POSTER_PHASE)
    first.save(target.with_suffix(".png"), optimize=True)
    if args.poster_only:
        return
    palette = first.quantize(colors=112)
    palette.putpalette(
        palette.getpalette()[: 112 * 3]
        + [c for color in (WHITE, BACKGROUND, BLUE) for c in ImageColor.getrgb(color)]
    )
    frames = []
    for index in range(FRAMES):
        frame = cover.frame(POSTER_PHASE + index / FRAMES)
        frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
    destination = target.with_suffix(".gif")
    frames[0].save(
        destination,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=1,
        optimize=True,
    )
    print(
        f"{destination}: {FRAMES} frames, {FRAMES * FRAME_MS / 1000:.2f}s, {destination.stat().st_size:,} bytes"
    )


if __name__ == "__main__":
    main()
