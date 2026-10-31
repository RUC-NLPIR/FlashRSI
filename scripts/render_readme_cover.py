#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow==11.3.0", "resvg-py==0.5.0"]
# ///
"""Encode frames captured from the bundled electric-logo component.

Start the preview in scripts/readme-cover, click Record, then run:
    uv run --script scripts/render_readme_cover.py /path/shown/by/the/preview

Forward and reverse playback closes the loop without replacing the shader's
nonperiodic noise or its random arcs. See assets/readme/cover-design.md.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import resvg_py
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1600, 360)
WORDMARK_BOX = (438, 0, 1600, 360)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/readme")
    parser.add_argument(
        "--reframe-original",
        action="store_true",
        help="Reuse frames from the original 1600 x 440 cover.",
    )
    args = parser.parse_args()
    metadata = json.loads((args.capture_dir / "capture.json").read_text())
    sources = [
        args.capture_dir / f"frame-{index:03}.png" for index in range(metadata["count"])
    ]
    if len(sources) < 2:
        parser.error("Capture at least two frames.")
    if args.reframe_original:
        base = Image.open(
            io.BytesIO(
                resvg_py.svg_to_bytes(
                    svg_path=str(ROOT / "scripts/readme-cover/base.svg"),
                    width=3200,
                    height=720,
                )
            )
        ).convert("RGB")
    frames = []
    for path in sources:
        with Image.open(path) as image:
            frame = image.convert("RGB")
        if args.reframe_original:
            if frame.size not in ((1600, 440), (3200, 880)):
                parser.error(f"Expected an original cover frame in {path.name}.")
            dpr = frame.width / 1600
            zoom = (0.72 * 360) / (0.52 * 440)
            # Match the component's centered fit at the new size and scale.
            effect = frame.transform(
                (800, 720),
                Image.Transform.AFFINE,
                (
                    dpr / (2 * zoom),
                    0,
                    dpr * (1200 - 200 / zoom),
                    0,
                    dpr / (2 * zoom),
                    dpr * (220 - 180 / zoom),
                ),
                Image.Resampling.BICUBIC,
            )
            frame = base.copy()
            # Keep the effect inside the logo column, clear of the wordmark.
            frame.paste(effect.crop((0, 0, 700, 720)), (140, 0))
        if frame.size == (3200, 720):
            frame = frame.resize(SIZE, Image.Resampling.LANCZOS)
        elif frame.size != SIZE:
            parser.error(f"Unexpected frame size in {path.name}: {frame.size}")
        frames.append(frame)
    if args.reframe_original:
        wordmark = frames[0].crop(WORDMARK_BOX)
        if any(
            ImageChops.difference(wordmark, frame.crop(WORDMARK_BOX)).getbbox()
            for frame in frames[1:]
        ):
            parser.error("The static wordmark changed during legacy reframing.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    poster = frames[len(frames) // 2]
    poster.save(args.output_dir / "cover.png", optimize=True)
    # Sample every frame so transient blue arcs also contribute to the palette.
    # Nearest-neighbor sampling keeps their actual colors instead of blending
    # thin electric strokes into the background before quantization.
    sample_size = (SIZE[0] // 2, SIZE[1] // 2)
    palette_source = Image.new("RGB", (sample_size[0], sample_size[1] * len(frames)))
    for index, frame in enumerate(frames):
        palette_source.paste(
            frame.resize(sample_size, Image.Resampling.NEAREST),
            (0, index * sample_size[1]),
        )
    palette = palette_source.quantize(colors=254)
    # Reserve exact brand colors alongside the shared animation colors.
    colors = palette.getpalette()[: 254 * 3] + [8, 11, 16, 243, 245, 247]
    palette.putpalette(colors)
    encoded = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames
    ]
    if not args.reframe_original:
        # Reuse pixels with small glow fluctuations so GIF delta frames compress
        # well. Compare against the encoded frame so gradual changes accumulate.
        for index in range(1, len(encoded)):
            red, green, blue = ImageChops.difference(
                encoded[index].convert("RGB"), encoded[index - 1].convert("RGB")
            ).split()
            changed = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
                lambda value: 255 if value > 8 else 0
            )
            encoded[index] = Image.composite(
                encoded[index], encoded[index - 1], changed
            )
    loop = encoded + encoded[-2:0:-1]
    destination = args.output_dir / "cover.gif"
    loop[0].save(
        destination,
        save_all=True,
        append_images=loop[1:],
        duration=metadata["frameMs"],
        loop=0,
        disposal=1,
        optimize=True,
    )
    print(
        f"{destination}: {len(loop)} frames, {len(loop) * metadata['frameMs'] / 1000:.2f}s, {destination.stat().st_size:,} bytes"
    )


if __name__ == "__main__":
    main()
