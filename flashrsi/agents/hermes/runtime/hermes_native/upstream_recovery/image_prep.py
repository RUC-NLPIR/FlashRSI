from __future__ import annotations
from pathlib import Path

_EXTENSION_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _determine_mime_type(image_path: Path) -> str:
    """MIME type from file extension (defaults to image/jpeg)."""
    return _EXTENSION_MIME_TYPES.get(image_path.suffix.lower(), "image/jpeg")


def _image_exceeds_dimension(image_path: Path, max_dimension: int) -> bool:
    """True if the longest side exceeds ``max_dimension`` px (Anthropic's 8000px per-side cap is
    independent of bytes). False without Pillow or on unreadable files — a missing soft
    dependency must never break the embed path."""
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(image_path) as _img:
            return max(_img.size) > max_dimension
    except Exception:
        return False
