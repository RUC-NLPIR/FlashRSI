from __future__ import annotations
import logging,uuid
from pathlib import Path
from typing import Optional
logger=logging.getLogger(__name__)
_ANTHROPIC_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


def unsupported_inline_image_media_type(url: str) -> Optional[str]:
    """``image/<subtype>`` of a ``data:image/...`` URL the inline-image wire paths reject
    (``image/jpg`` counts as JPEG); None for accepted rasters and for non-data URLs (the
    provider owns remote-URL validation)."""
    header = url.partition(",")[0].lower()
    if not header.startswith("data:image/"):
        return None
    subtype = header[len("data:image/"):].split(";", 1)[0].strip() or "unknown"
    media_type = "image/jpeg" if subtype == "jpg" else f"image/{subtype}"
    return None if media_type in _ANTHROPIC_SUPPORTED_MEDIA_TYPES else media_type


def _nonempty_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _rasterize_svg_to_png(svg_path: Path, out_path: Path) -> bool:
    """Best-effort SVG → PNG via cairosvg, svglib+reportlab, rsvg-convert, inkscape (all soft deps)."""
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=str(svg_path), write_to=str(out_path))
        return _nonempty_file(out_path)
    except Exception:
        pass
    try:
        from svglib.svglib import svg2rlg  # type: ignore
        from reportlab.graphics import renderPM  # type: ignore
        drawing = svg2rlg(str(svg_path))
        if drawing is not None:
            renderPM.drawToFile(drawing, str(out_path), fmt="PNG")
            return _nonempty_file(out_path)
    except Exception:
        pass
    import shutil
    import subprocess
    for cmd in (
        ["rsvg-convert", "-o", str(out_path), str(svg_path)],
        ["inkscape", str(svg_path), "--export-type=png", f"--export-filename={out_path}"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
                if _nonempty_file(out_path):
                    return True
            except Exception:
                continue
    return False


def rasterize_svg_data_url(url: str) -> Optional[str]:
    """``data:image/svg+xml[;base64],...`` → ``data:image/png;base64,...`` through the same
    soft-dependency rasterizers vision_analyze uses; None when the payload does not decode or no
    rasterizer is available. Request-path callers decide the fallback (Responses backends 400 on
    SVG source, so the caller must never forward the SVG itself)."""
    import base64
    from contextlib import suppress
    from urllib.parse import unquote
    header, _, payload = url.partition(",")
    try:
        raw = base64.b64decode(payload) if ";base64" in header.lower() else unquote(payload).encode()
    except Exception:
        return None
    from .boundaries import _secure_cache_dir, _write_private_bytes
    out_dir = _secure_cache_dir("cache/vision", "temp_vision_images")
    stem = out_dir / f"inline_{uuid.uuid4()}"
    svg_path, png_path = stem.with_suffix(".svg"), stem.with_suffix(".png")
    try:
        svg_path.write_bytes(raw)
        if not _rasterize_svg_to_png(svg_path, png_path):
            return None
        return "data:image/png;base64," + base64.b64encode(png_path.read_bytes()).decode("ascii")
    finally:
        for path in (svg_path, png_path):
            with suppress(OSError):
                path.unlink()

