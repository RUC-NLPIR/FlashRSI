"""Differential checks for the pure-Python Photon codec port."""

import base64
import json
from pathlib import Path

from flashrsi.agents.pi_agent.runtime.pi_native.photon_image import (
    decode_webp_lossy,
    encode_jpeg,
    encode_png,
    resize_rgba,
)

ROOT = Path(__file__).parent / "fixtures"


def test_photon_resampler_and_codecs_match_pinned_oracle():
    fixture = json.loads((ROOT / "pi_images_upstream.json").read_text())
    for case in fixture["cases"]:
        pixels = resize_rgba(
            base64.b64decode(case["pixels"]),
            case["width"],
            case["height"],
            case["new_width"],
            case["new_height"],
        )
        assert pixels == base64.b64decode(case["resized"]), case["name"]
        assert encode_png(
            pixels, case["new_width"], case["new_height"]
        ) == base64.b64decode(case["png"]), case["name"]
        for quality, encoded in case["jpeg"].items():
            assert encode_jpeg(
                pixels, case["new_width"], case["new_height"], int(quality)
            ) == base64.b64decode(encoded), (case["name"], quality)


def test_vp8_decoder_matches_photon_for_dimensions_and_qualities():
    fixture = json.loads((ROOT / "pi_image_decode_upstream.json").read_text())
    for case in fixture:
        if case.get("mime") != "image/webp" or "lossy" not in case["name"]:
            continue
        decoded = decode_webp_lossy(base64.b64decode(case["input"]))
        assert decoded is not None
        pixels, width, height = decoded
        assert (width, height) == (case["decoded"]["width"], case["decoded"]["height"])
        assert pixels == base64.b64decode(case["decoded"]["pixels"]), case["name"]


def test_webp_lossy_alpha_matches_photon():
    fixture = json.loads((ROOT / "pi_image_decode_upstream.json").read_text())
    case = next(case for case in fixture if case["name"] == "webp-alpha")
    decoded = decode_webp_lossy(base64.b64decode(case["input"]))
    assert decoded is not None
    pixels, width, height = decoded
    assert (width, height) == (case["decoded"]["width"], case["decoded"]["height"])
    assert pixels == base64.b64decode(case["decoded"]["pixels"])
