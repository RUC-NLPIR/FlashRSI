"""Safe wrapper around the base web browse + LLM extraction pipeline."""

from __future__ import annotations

import types


async def call(args, ctx) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    url = url.strip()
    focus = args.get("focus")
    if not isinstance(focus, str) or not focus.strip():
        focus = "general relevance"
    focus = focus.strip()

    try:
        from runtime import reader

        page = await reader.read_url_with_raw(
            url, focus, ctx.workspace.extract_prompt
        )
        extracted = page["extracted"]
        raw = page.get("raw", "")
    except Exception as e:
        _record_read(ctx, url, focus, "", False)
        return (
            f"[read_page] read failed for {url}: {type(e).__name__}: {e}. "
            "Try a different URL or run search_web again."
        )

    success = not (
        extracted.startswith("[reader] fetch failed")
        or extracted.startswith("[reader] extract error")
        or extracted.startswith("[reader] no relevant content")
    )
    _record_read(ctx, url, focus, extracted, success, raw)
    return extracted


def _record_read(ctx, url: str, focus: str, extracted: str, success: bool, raw: str = "") -> None:
    """Mirror the built-in read_url tracing for workspace-provided read_page."""
    try:
        read_calls = getattr(ctx, "read_calls", 0) + 1
        setattr(ctx, "read_calls", read_calls)
        trace = getattr(ctx, "trace", None)
        if trace is not None:
            try:
                trace.save_page(url, focus, extracted, raw_text=raw)
            except Exception:
                pass
        reads = getattr(ctx, "reads", None)
        if reads is not None:
            reads.append(types.SimpleNamespace(url=url, success=success))
    except Exception:
        pass
