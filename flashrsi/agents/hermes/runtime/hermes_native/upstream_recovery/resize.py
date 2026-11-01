from __future__ import annotations
import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional
from .image_prep import _determine_mime_type, _image_exceeds_dimension
logger=logging.getLogger(__name__)

logger = logging.getLogger(__name__)


def _image_to_base64_data_url(image_path: Path, mime_type: Optional[str] = None) -> str:
    """``data:<mime>;base64,...`` for a file (MIME from extension when not given)."""
    mime = mime_type or _determine_mime_type(image_path)
    return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"


_RESIZE_TARGET_BYTES = 5 * 1024 * 1024


def _import_pillow_for_resize():
    """Return ``PIL.Image`` or None (Pillow is a lazy-installable soft dependency). ``prompt=False``:
    a blocking input() deadlocks the CLI where prompt_toolkit owns stdin; the install is already
    gated by security.allow_lazy_installs."""
    try:
        from PIL import Image
    except ImportError:
        try:
            # pm-era wiring: never raise a blocking input() prompt mid-session. Under the
            # interactive CLI prompt_toolkit owns stdin, so a bare input() deadlocks the
            # terminal (#40490). The install is already gated by security.allow_lazy_installs,
            # so reaching here is opt-in.
            from .boundaries import ensure_import

            ensure_import("vision")
            from PIL import Image
        except Exception:
            return None
    return Image


def _resize_image_for_vision(image_path: Path, mime_type: Optional[str] = None,
                              max_base64_bytes: int = _RESIZE_TARGET_BYTES,
                              max_dimension: Optional[int] = None,
                              scale_out: Optional[dict] = None,
                              force_jpeg: bool = False) -> str:
    """Base64 data URL, progressively downscaled with Pillow while over budget.

    Halves dimensions (aspect-preserving, 64px floor) up to 4 times; JPEG also walks a
    quality ladder (85/70/50) per step. Without Pillow, or if it still doesn't fit, returns
    the best attempt (or raw bytes) and lets the caller apply the size check.
    ``max_dimension``: force a downscale above this long edge even when bytes fit
    (Anthropic's 8000px cap is independent of bytes). ``force_jpeg``: re-encode PNG as JPEG
    when resizing — halving PNG dimensions destroys text legibility on dense screenshots.

    Args: max_dimension: If set, images whose longest side exceeds this pixel count are forcibly downscaled
    even if they're under the byte budget. Anthropic enforces an 8000 px per-side cap independently of the 5
    MB byte cap. force_jpeg: Re-encode as JPEG even for PNG input when a resize is needed. History-reuse
    embeds (#92699) opt in so a text-heavy screenshot keeps its readable resolution and shrinks via JPEG
    quality instead. Images already under both caps are returned unchanged (still PNG).
    """
    file_size = image_path.stat().st_size
    estimated_b64 = (file_size * 4) // 3 + 100  # base64 ~4/3 + data URL header
    data_url = None
    if estimated_b64 <= max_base64_bytes and not (
        max_dimension is not None and _image_exceeds_dimension(image_path, max_dimension)
    ):
        data_url = _image_to_base64_data_url(image_path, mime_type=mime_type)
        if len(data_url) <= max_base64_bytes:
            return data_url

    def _raw() -> str:
        return data_url or _image_to_base64_data_url(image_path, mime_type=mime_type)
    Image = _import_pillow_for_resize()
    if Image is None:
        logger.info("Pillow not installed — cannot auto-resize oversized image")
        return _raw()  # caller will raise the size error
    logger.info("Image file is %.1f MB (estimated base64 %.1f MB, limit %.1f MB, max_dimension=%s), auto-resizing...",
                file_size / (1024 * 1024), estimated_b64 / (1024 * 1024),
                max_base64_bytes / (1024 * 1024), max_dimension)
    # JPEG for photos (smaller), PNG for transparency — unless force_jpeg.
    is_png = (mime_type or _determine_mime_type(image_path)) == "image/png" and not force_jpeg
    pil_format, out_mime = ("PNG", "image/png") if is_png else ("JPEG", "image/jpeg")
    try:
        img = Image.open(image_path)
    except Exception as exc:
        logger.info("Pillow cannot open image for resizing: %s", exc)
        return _raw()

    # JPEG cannot encode alpha/palette modes (force_jpeg routes PNGs here).
    if not is_png and img.mode not in {"RGB", "L"}:
        img = img.convert("RGB")
    quality_steps = (None,) if is_png else (85, 70, 50)
    orig_dims = prev_dims = (img.width, img.height)
    candidate = None

    def _record_scale(w: int, h: int) -> None:
        if scale_out is not None and (w, h) != orig_dims:
            scale_out.update(orig_width=orig_dims[0], orig_height=orig_dims[1], new_width=w, new_height=h)
    for attempt in range(5):
        if attempt > 0:
            # Halve, then re-derive from whichever axis hit the 64px floor so both shrink equally.
            new_w, new_h = max(int(img.width * 0.5), 64), max(int(img.height * 0.5), 64)
            if new_w == 64 and img.width > 0:
                new_h = max(int(img.height * (64 / img.width)), 64)
            elif new_h == 64 and img.height > 0:
                new_w = max(int(img.width * (64 / img.height)), 64)
            if (new_w, new_h) == prev_dims:
                break
            img = img.resize((new_w, new_h), Image.LANCZOS)
            prev_dims = (new_w, new_h)
            logger.info("Resized to %dx%d (attempt %d)", new_w, new_h, attempt)
        dims_ok = max_dimension is None or max(img.width, img.height) <= max_dimension
        for q in quality_steps:
            buf = BytesIO()
            img.save(buf, format=pil_format, **({} if q is None else {"quality": q}))
            candidate = f"data:{out_mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
            if len(candidate) <= max_base64_bytes and dims_ok:
                logger.info("Auto-resized image fits: %.1f MB (quality=%s, %dx%d)",
                            len(candidate) / (1024 * 1024), q, img.width, img.height)
                _record_scale(img.width, img.height)
                return candidate
    if candidate is None:
        return _raw()
    logger.warning("Auto-resize could not fit image under %.1f MB (best: %.1f MB)",
                   max_base64_bytes / (1024 * 1024), len(candidate) / (1024 * 1024))
    _record_scale(img.width, img.height)
    return candidate
