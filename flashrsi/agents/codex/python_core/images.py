"""Image preparation from core/src/image_preparation.rs and utils/image/src/lib.rs.

Pinned to Codex be6e8eac. PNG/JPEG/WebP within the native size and patch
budgets preserve their original bytes. Re-encoding and resizing require the
native encoder and Triangle filter to be ported; those branches reject rather
than silently change the pixels or encoded model input.
"""

from __future__ import annotations

import base64
import binascii
import io
import math

from PIL import Image, UnidentifiedImageError

_MAX_INPUT = 1024 * 1024 * 1024
_PROCESSING_ERROR = "image content omitted because it could not be processed"
_TOO_LARGE = "image content omitted because it exceeded the supported size limit; use a smaller image"
_LOW_DETAIL = "image content omitted because detail 'low' is not supported; use 'high', 'original', or 'auto'"
_REMOTE = "image content omitted because remote image URLs are not supported"


class UnsupportedImage(ValueError):
    """A valid image reaches an image-processing branch not yet ported."""


def decode_image_url(url):
    metadata, encoded = url[5:].split(",", 1)
    if "base64" not in (part.lower() for part in metadata.split(";")):
        raise ValueError("only base64 data URLs are supported")
    if len(encoded) > _MAX_INPUT:
        raise OverflowError("base64 payload exceeds supported size limit")
    data = base64.b64decode(encoded, validate=True)
    if len(data) > _MAX_INPUT:
        raise OverflowError("decoded image exceeds supported size limit")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return data, image.format, image.width, image.height


def output_dimensions(width, height, max_dimension, max_patches):
    """Native ResizeWithLimits dimension calculation, including positive f64 rounding."""
    width, height = max(1, width), max(1, height)

    def fits(w, h):
        return (
            max(w, h) <= max_dimension
            and ((w + 31) // 32) * ((h + 31) // 32) <= max_patches
        )

    if fits(width, height):
        return width, height
    scale = min(max_dimension / max(width, height), 1.0)
    width = max(1, math.floor(width * scale + 0.5))
    height = max(1, math.floor(height * scale + 0.5))
    if fits(width, height):
        return width, height
    scale = math.sqrt(32 * 32 * max_patches / width / height)
    wide, high = width * scale / 32, height * scale / 32
    scale *= min(math.floor(wide) / wide, math.floor(high) / high)
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def prepare_image(part):
    url = part["image_url"]
    scheme = url.split(":", 1)[0].lower()
    if scheme in {"http", "https"}:
        return {"type": "input_text", "text": _REMOTE}
    if scheme != "data":
        return part
    detail = part.get("detail")
    if detail == "low":
        return {"type": "input_text", "text": _LOW_DETAIL}
    try:
        data, format_name, width, height = decode_image_url(url)
    except OverflowError:
        return {"type": "input_text", "text": _TOO_LARGE}
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError):
        return {"type": "input_text", "text": _PROCESSING_ERROR}
    limits = (6000, 10000) if detail == "original" else (2048, 2500)
    target = output_dimensions(width, height, *limits)
    if target != (width, height):
        raise UnsupportedImage(
            "Codex Python core has not ported native Triangle image resizing "
            f"({width}x{height} to {target[0]}x{target[1]})"
        )
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
        format_name
    )
    if mime is None:
        raise UnsupportedImage(
            f"Codex Python core has not ported native {format_name} to PNG re-encoding"
        )
    return {
        **part,
        "image_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii"),
    }


def prepare_item(item):
    # Session::prepare_conversation_items_for_history prepares images before
    # truncation and token accounting, including tool image outputs.
    kind = item["type"]
    key = "content" if kind == "message" else "output"
    if kind not in {"message", "function_call_output", "custom_tool_call_output"}:
        return item
    content = item.get(key)
    if isinstance(content, list):
        item[key] = [
            prepare_image(part) if part.get("type") == "input_image" else part
            for part in content
        ]
    return item
