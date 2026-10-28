#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow==11.3.0"]
# ///
"""Render the README hero with Pillow, without browser or external assets.

Run with uv (or install Pillow and use Python directly):
    uv run --script scripts/render_readme_hero.py

The default fonts use macOS SF Pro/Arial or Linux DejaVu Sans. Pass --font
and --bold-font to reproduce the same typography on another machine.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont

WIDTH, HEIGHT, SCALE = 1360, 790, 2
FRAME_MS = 80
HOLD_MS = 1500
ROLL_MS = 1200
SETTLE_MS = 160
CHART_MS = 2800
PLAYBACK_SPEED = 2.028
CHART_WIDTH, CHART_STEP = 291, 313
INK = "#242521"
MUTED = "#807E76"
ACCENT = "#EA6039"
PAPER = "#F8F7F3"
FONT_PATHS = (
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
BOLD_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
REELS = (
    ("BENCHMARK", ("SearchQA", "HotpotQA", "Terminal-Bench", "τ³ Banking")),
    (
        "RSI ALGORITHM",
        (
            "OPRO",
            "EvoPrompt",
            "GEPA",
            "SkillOpt",
            "AHE",
            "ACE",
            "ADAS",
            "DarwinX",
            "Meta-Harness",
            "ModularRSI",
            "Evo-Harness",
            "RRSI",
        ),
    ),
    ("HARNESS", ("MiniAgent", "Claude Code", "Codex", "OpenHands", "Pi", "Hermes")),
)
# All three columns advance exactly one item at each transition.
# The README identifies the planned harness integrations.
COMBINATIONS = tuple(
    (phase % 4, (3 + phase) % 12, (2 + phase) % 6) for phase in range(12)
)
CHARTS = (
    ("Training", "#647B96", "#EFF2F7"),
    ("Held-out", "#EA6039", "#FEF2EB"),
    ("Near-domain", "#B98A35", "#FAF5E8"),
    ("OOD-domain", "#71847B", "#EFF3EF"),
)
# Synthetic shapes, deliberately including OOD plateaus and regressions.
# These values are never shown as measurements or percentage scores.
CURVE_PROFILES = (
    (
        (0.20, 0.34, 0.48, 0.61, 0.70, 0.79, 0.87, 0.92, 0.95),
        (0.22, 0.28, 0.39, 0.44, 0.57, 0.64, 0.70, 0.80, 0.87),
        (0.42, 0.46, 0.45, 0.50, 0.49, 0.55, 0.56, 0.59, 0.61),
        (0.57, 0.61, 0.64, 0.63, 0.59, 0.56, 0.52, 0.49, 0.45),
    ),
    (
        (0.25, 0.38, 0.51, 0.64, 0.74, 0.83, 0.88, 0.93, 0.96),
        (0.27, 0.32, 0.41, 0.50, 0.54, 0.63, 0.71, 0.76, 0.82),
        (0.45, 0.46, 0.50, 0.49, 0.54, 0.53, 0.56, 0.57, 0.60),
        (0.48, 0.53, 0.57, 0.60, 0.61, 0.60, 0.61, 0.60, 0.60),
    ),
    (
        (0.18, 0.35, 0.49, 0.62, 0.73, 0.82, 0.89, 0.94, 0.97),
        (0.20, 0.30, 0.34, 0.45, 0.53, 0.61, 0.69, 0.79, 0.88),
        (0.40, 0.44, 0.46, 0.45, 0.50, 0.54, 0.53, 0.56, 0.58),
        (0.61, 0.61, 0.60, 0.56, 0.57, 0.52, 0.51, 0.47, 0.48),
    ),
)


def font_path(explicit, candidates):
    if explicit:
        return str(Path(explicit).expanduser())
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("No suitable font found; pass --font and --bold-font.")


class Hero:
    def __init__(self, regular, bold):
        self.regular, self.bold = regular, bold
        self.fonts = {}
        self.base = self.background()

    def font(self, size, bold=False):
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(
                self.bold if bold else self.regular, round(size * SCALE)
            )
        return self.fonts[key]

    def text(self, draw, xy, value, size, fill=INK, *, bold=False, anchor="lt"):
        draw.text(
            tuple(round(v * SCALE) for v in xy),
            value,
            font=self.font(size, bold),
            fill=fill,
            anchor=anchor,
        )

    def tracked(self, draw, xy, value, size, fill=MUTED, spacing=2):
        x, y = xy
        font = self.font(size)
        for character in value:
            self.text(draw, (x, y), character, size, fill)
            x += font.getlength(character) / SCALE + spacing

    @staticmethod
    def box(draw, xy, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(
            tuple(round(v * SCALE) for v in xy),
            radius=round(radius * SCALE),
            fill=fill,
            outline=outline,
            width=round(width * SCALE),
        )

    def background(self):
        image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PAPER)
        draw = ImageDraw.Draw(image)
        self.box(draw, (1, 1, WIDTH - 2, HEIGHT - 2), 25, PAPER, "#E7E3DA")
        bolt = ((89, 44), (63, 77), (80, 77), (72, 100), (103, 63), (85, 63))
        draw.polygon([(x * SCALE, y * SCALE) for x, y in bolt], fill=ACCENT)
        self.text(draw, (117, 46), "FlashRSI", 48, bold=True)
        self.text(draw, (65, 116), "Choose. Improve. Evaluate.", 23, "#62625B")
        draw.line(
            (65 * SCALE, 160 * SCALE, 1295 * SCALE, 160 * SCALE),
            fill="#E3DFD6",
            width=SCALE,
        )
        for column, (label, _) in enumerate(REELS):
            x = 65 + 420 * column
            self.tracked(draw, (x + 2, 185), label, 12, spacing=1.9)
            self.box(draw, (x, 222, x + 390, 402), 19, "#ECE8E0")
            self.box(draw, (x, 218, x + 390, 397), 19, "#FFFFFF", "#DCD8CF")
            self.box(draw, (x + 10, 276, x + 380, 338), 10, "#FFF5EC")
            self.box(draw, (x + 11, 288, x + 14, 325), 1, ACCENT)
        for x in (470, 890):
            self.text(draw, (x, 309), "×", 26, "#B7B3AA", anchor="mm")
        draw.line(
            (65 * SCALE, 444 * SCALE, 1295 * SCALE, 444 * SCALE),
            fill="#E3DFD6",
            width=SCALE,
        )
        self.text(
            draw,
            (65, 472),
            "Training & evaluation · Illustrative curves",
            18,
            "#77766D",
        )
        for column, (title, color, _) in enumerate(CHARTS):
            x = 65 + CHART_STEP * column
            self.box(draw, (x, 510, x + CHART_WIDTH, 751), 16, "#FFFFFF", "#E2DED5")
            self.text(draw, (x + 19, 530), title, 18, bold=True)
            draw.ellipse(
                (
                    (x + CHART_WIDTH - 27) * SCALE,
                    533 * SCALE,
                    (x + CHART_WIDTH - 21) * SCALE,
                    539 * SCALE,
                ),
                fill=color,
            )
            self.text(draw, (x + 19, 568), "Score", 11, MUTED)
            for grid_y in (586, 626, 666, 706):
                draw.line(
                    (
                        (x + 36) * SCALE,
                        grid_y * SCALE,
                        (x + CHART_WIDTH - 19) * SCALE,
                        grid_y * SCALE,
                    ),
                    fill="#EFECE6",
                    width=SCALE,
                )
            self.text(
                draw,
                (x + (CHART_WIDTH + 17) / 2, 729),
                "Evolution",
                12,
                MUTED,
                anchor="mm",
            )
        return image

    def reel(self, image, column, position):
        names = REELS[column][1]
        x, y, width, height = 65 + 420 * column, 219, 390, 177
        layer = Image.new("RGBA", (width * SCALE, height * SCALE))
        draw = ImageDraw.Draw(layer)
        center, pitch = 88, 61
        first = math.floor(position)
        for index in range(first - 2, first + 4):
            offset = (index - position) * pitch
            distance = abs(offset)
            alpha = round(255 * max(0.0, 1 - (distance / 115) ** 1.5))
            selected = distance < 28
            name = names[index % len(names)]
            size = 31 if column == 0 else 33
            measured = self.font(size, selected).getlength(name)
            size = min(size, math.floor(size * (width - 54) * SCALE / measured))
            self.text(
                draw,
                (width / 2 + 4, center + offset),
                name,
                size,
                (36, 37, 33, alpha),
                bold=selected,
                anchor="mm",
            )
        # Clipped, fading neighboring labels make the vertical reel visible.
        alpha = layer.getchannel("A")
        fade = Image.new("L", alpha.size)
        rows = ImageDraw.Draw(fade)
        for row in range(height * SCALE):
            edge = min(row / SCALE, height - row / SCALE)
            rows.line((0, row, width * SCALE, row), fill=round(255 * min(1, edge / 25)))
        layer.putalpha(ImageChops.multiply(alpha, fade))
        image.paste(layer, (x * SCALE, y * SCALE), layer)

    def curve(self, draw, column, phase, progress):
        if progress <= 0:
            return
        x = 65 + CHART_STEP * column
        left, top, width, height = x + 36, 586, CHART_WIDTH - 55, 120
        values = CURVE_PROFILES[phase % len(CURVE_PROFILES)][column]
        color, tint = CHARTS[column][1:]
        points = []
        count = 120
        for sample in range(math.floor(progress * count) + 1):
            fraction = min(progress, sample / count)
            interval = fraction * (len(values) - 1)
            index = min(len(values) - 2, math.floor(interval))
            local = interval - index
            ease = (1 - math.cos(math.pi * local)) / 2
            value = values[index] + (values[index + 1] - values[index]) * ease
            points.append(
                (
                    (left + width * fraction) * SCALE,
                    (top + height * (1 - value)) * SCALE,
                )
            )
        if len(points) < 2:
            return
        draw.polygon(
            [
                (points[0][0], (top + height) * SCALE),
                *points,
                (points[-1][0], (top + height) * SCALE),
            ],
            fill=tint,
        )
        draw.line(points, fill=color, width=3 * SCALE, joint="curve")
        for index, value in enumerate(values):
            fraction = index / (len(values) - 1)
            if fraction > progress:
                break
            dot_x, dot_y = left + width * fraction, top + height * (1 - value)
            draw.ellipse(
                (
                    (dot_x - 2.3) * SCALE,
                    (dot_y - 2.3) * SCALE,
                    (dot_x + 2.3) * SCALE,
                    (dot_y + 2.3) * SCALE,
                ),
                fill="#FFFFFF",
                outline=color,
                width=SCALE,
            )
        dot_x, dot_y = points[-1]
        draw.ellipse(
            (
                dot_x - 3 * SCALE,
                dot_y - 3 * SCALE,
                dot_x + 3 * SCALE,
                dot_y + 3 * SCALE,
            ),
            fill=color,
        )

    def render(self, positions, phase=0, *, moving=(), curves=(1, 1, 1, 1)):
        image = self.base.copy()
        for column, position in enumerate(positions):
            self.reel(image, column, position)
        draw = ImageDraw.Draw(image)
        for column in range(3):
            x = 440 + 420 * column
            color = ACCENT if column in moving else "#B9B6AD"
            draw.ellipse(
                (x * SCALE, 187 * SCALE, (x + 6) * SCALE, 193 * SCALE), fill=color
            )
        for column, progress in enumerate(curves):
            self.curve(draw, column, phase, progress)
        return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

    def frames(self):
        stops = (0.88, 1.04, 1.20)
        chart_offsets = (0, 600, 1200, 1800)
        for phase, start in enumerate(COMBINATIONS):
            target_phase = (phase + 1) % len(COMBINATIONS)
            target = COMBINATIONS[target_phase]
            yield (
                self.render(start, phase),
                HOLD_MS,
                f"{phase + 1:02} · {REELS[1][1][start[1]]}",
            )
            for tick in range(1, ROLL_MS // FRAME_MS + 1):
                time = tick * FRAME_MS / 1000
                positions, moving = [], []
                for column in range(3):
                    progress = min(1, time / stops[column])
                    ease = progress**3 * (progress * (6 * progress - 15) + 10)
                    positions.append(start[column] + ease)
                    if progress < 1:
                        moving.append(column)
                label = "Single-step selection" if phase == 0 and tick == 7 else None
                yield (
                    self.render(
                        positions,
                        target_phase,
                        moving=moving,
                        curves=(0, 0, 0, 0),
                    ),
                    FRAME_MS,
                    label,
                )
            yield (
                self.render(target, target_phase, curves=(0, 0, 0, 0)),
                SETTLE_MS,
                "Selection settled · empty plots" if phase == 0 else None,
            )
            for tick in range(1, CHART_MS // FRAME_MS + 1):
                elapsed = tick * FRAME_MS
                progress = tuple(
                    max(0, min(1, (elapsed - offset) / 1000))
                    for offset in chart_offsets
                )
                label = (
                    {
                        5: "Training drawing",
                        13: "Held-out drawing",
                        21: "Near-domain drawing",
                        31: "OOD-domain drawing",
                    }.get(tick)
                    if phase == 0
                    else None
                )
                yield (
                    self.render(target, target_phase, curves=progress),
                    FRAME_MS,
                    label,
                )


def contact_sheet(frames, previews, destination, font):
    columns, thumb_width = 3, 480
    thumb_height = round(HEIGHT * thumb_width / WIDTH)
    cell_height = thumb_height + 26
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, math.ceil(len(previews) / columns) * cell_height),
        PAPER,
    )
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(font, 14)
    for index, (frame_index, label) in enumerate(previews):
        x, y = (index % columns) * thumb_width, (index // columns) * cell_height
        draw.text((x + 10, y + 5), label, font=label_font, fill=INK)
        frame = frames[frame_index].convert("RGB")
        sheet.paste(
            frame.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS),
            (x, y + 26),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "readme",
    )
    parser.add_argument("--font")
    parser.add_argument("--bold-font")
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument("--poster-only", action="store_true")
    args = parser.parse_args()
    hero = Hero(font_path(args.font, FONT_PATHS), font_path(args.bold_font, BOLD_PATHS))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    poster = args.output_dir / "poster.png"
    gif = args.output_dir / "slot-machine.gif"
    first = hero.render(COMBINATIONS[0])
    first.save(poster, optimize=True)
    if args.poster_only:
        print(poster)
        return
    palette = first.quantize(colors=112)
    # Keep chart colors distinct in the shared GIF palette.
    colors = (
        INK,
        MUTED,
        ACCENT,
        PAPER,
        *(color for chart in CHARTS for color in chart[1:]),
    )
    palette.putpalette(
        palette.getpalette()[: 112 * 3]
        + [channel for color in colors for channel in ImageColor.getrgb(color)]
    )
    encoded, durations, previews = [], [], []
    elapsed, playback_elapsed = 0, 0
    for frame, duration, label in hero.frames():
        encoded.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
        elapsed += duration
        # GIF delays use 10ms units; cumulative rounding preserves playback speed.
        playback_boundary = round(elapsed / PLAYBACK_SPEED / 10) * 10
        durations.append(playback_boundary - playback_elapsed)
        playback_elapsed = playback_boundary
        if label:
            previews.append((len(encoded) - 1, label))
    encoded[0].save(
        gif,
        save_all=True,
        append_images=encoded[1:],
        duration=durations,
        loop=0,
        disposal=1,
        optimize=True,
    )
    if args.contact_sheet:
        contact_sheet(encoded, previews, args.contact_sheet, hero.regular)
    print(
        f"{gif}: {WIDTH}×{HEIGHT}, {sum(durations) / 1000:.2f}s, {gif.stat().st_size:,} bytes"
    )
    print(poster)


if __name__ == "__main__":
    main()
