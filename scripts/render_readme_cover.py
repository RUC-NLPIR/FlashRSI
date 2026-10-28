#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow==11.3.0"]
# ///
"""Encode frames captured from the actual React Bits ElectricLogo component.

Start the preview in scripts/readme-cover, click Record, then run:
    uv run --script scripts/render_readme_cover.py /path/shown/by/the/preview

Forward and reverse playback closes the loop without replacing the shader's
nonperiodic noise or its random arcs. See assets/readme/cover-design.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/readme")
    args = parser.parse_args()
    metadata = json.loads((args.capture_dir / "capture.json").read_text())
    sources = [
        args.capture_dir / f"frame-{index:03}.png" for index in range(metadata["count"])
    ]
    if len(sources) < 2:
        parser.error("Capture at least two frames.")
    frames = []
    for path in sources:
        with Image.open(path) as image:
            frame = image.convert("RGB")
        if frame.size == (3200, 880):
            frame = frame.resize((1600, 440), Image.Resampling.LANCZOS)
        elif frame.size != (1600, 440):
            parser.error(f"Unexpected frame size in {path.name}: {frame.size}")
        frames.append(frame)
    left = frames[0].crop((0, 0, 800, 440))
    if any(
        ImageChops.difference(left, frame.crop((0, 0, 800, 440))).getbbox()
        for frame in frames[1:]
    ):
        parser.error("The static wordmark changed during capture.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    poster = frames[len(frames) // 2]
    poster.save(args.output_dir / "cover.png", optimize=True)
    palette = poster.quantize(colors=224)
    encoded = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames
    ]
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
