from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


_THINKING_TYPES = frozenset(("thinking", "redacted_thinking"))


_CACHEABLE_TYPES = frozenset(("text", "tool_use"))


_EMPTY_TEXT_PLACEHOLDER = "(empty)"


def _block_type(b: Any) -> Any:
    """``type`` of a dict block, None for non-dicts."""
    return b.get("type") if isinstance(b, dict) else None


def _has_block_type(blocks: list[Any], types) -> bool:
    return any(_block_type(b) in types for b in blocks)


def _is_blank_text_block(b: Any) -> bool:
    """A text block whose ``text`` is not a non-whitespace string (None/int/blank all count) —
    Anthropic 400s on them ("text content blocks must contain non-whitespace text")."""
    return _block_type(b) == "text" and not (isinstance(b.get("text"), str) and b["text"].strip())


def _cache_control_of(b: Any) -> Optional[dict[str, Any]]:
    cc = b.get("cache_control") if isinstance(b, dict) else None
    return cc if isinstance(cc, dict) else None


def _text_block(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _text_block_with_citations(text: Any, cits: Any) -> dict[str, Any]:
    """Text block carrying ``citations`` only when it is a non-empty list (the only input-valid shape)."""
    block: dict[str, Any] = _text_block(text)
    if isinstance(cits, list) and cits:
        block["citations"] = cits
    return block


def _parse_tool_args(raw: Any) -> Any:
    """JSON-decode a tool_call ``arguments`` string; non-strings pass through, bad JSON -> {}."""
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, ValueError):
        return {}


def _carry_cache_control(out: dict[str, Any], b: Any, *, copy: bool = False) -> dict[str, Any]:
    """Carry a dict-valued ``cache_control`` marker from ``b`` onto ``out`` (returned); ``copy``
    shallow-copies it so the caller's dict is never shared with the wire payload."""
    cc = _cache_control_of(b)
    if cc is not None:
        out["cache_control"] = dict(cc) if copy else cc
    return out


def _sanitize_tool_id(tool_id: str) -> str:
    """Anthropic requires ids matching [a-zA-Z0-9_-]; replace the rest, never empty."""
    return (re.sub(r"[^a-zA-Z0-9_-]", "_", tool_id) if tool_id else "") or "tool_0"


def _tool_use_block(tool_id: Any, name: Any, tool_input: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": _sanitize_tool_id(tool_id), "name": name, "input": tool_input}


def _extract_preserved_thinking_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Deep-copied thinking/redacted_thinking blocks from ``reasoning_details``."""
    raw_details = message.get("reasoning_details")
    if not isinstance(raw_details, list):
        return []
    return [
        copy.deepcopy(d)
        for d in raw_details
        if isinstance(d, dict) and str(d.get("type", "") or "").strip().lower() in _THINKING_TYPES
    ]


def _replay_text(b: dict[str, Any]) -> Optional[dict[str, Any]]:
    # Drop blank blocks rather than coerce in place: the caller relocates any cache_control and
    # falls back to a placeholder only when nothing survives, so "(empty)" never sits as
    # model-visible noise next to real blocks.
    if _is_blank_text_block(b):
        return None
    return _carry_cache_control(_text_block_with_citations(b["text"], b.get("citations")), b)


def _replay_thinking(b: dict[str, Any]) -> dict[str, Any]:
    out = {"type": "thinking", "thinking": b.get("thinking", "")}
    return {**out, "signature": b["signature"]} if b.get("signature") else out


def _replay_redacted_thinking(b: dict[str, Any]) -> Optional[dict[str, Any]]:
    return {"type": "redacted_thinking", "data": b["data"]} if b.get("data") else None


def _replay_tool_use(b: dict[str, Any]) -> dict[str, Any]:
    return _carry_cache_control(_tool_use_block(b.get("id", ""), b.get("name", ""), b.get("input", {})), b)


def _replay_image(b: dict[str, Any]) -> Optional[dict[str, Any]]:
    src = b.get("source")
    return {"type": "image", "source": src} if isinstance(src, dict) else None


_REPLAY_SANITIZERS = {
    "text": _replay_text, "thinking": _replay_thinking, "redacted_thinking": _replay_redacted_thinking,
    "tool_use": _replay_tool_use, "image": _replay_image,
}


def _sanitize_replay_block(b: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Whitelist a stored Anthropic block so it is valid as REQUEST input. SDK response blocks carry
    output-only fields the INPUT schema forbids ("Extra inputs are not permitted": ``parsed_output``,
    ``caller``, ``citations=None``), and ``_to_plain_data`` captured them verbatim. Whitelist per
    type (not blacklist) so future SDK fields can't reintroduce the bug; unknown types are dropped.
    Returns a clean block or None."""
    if not isinstance(b, dict):
        return None
    sanitizer = _REPLAY_SANITIZERS.get(b.get("type"))
    return sanitizer(b) if sanitizer else None


def _apply_assistant_cache_control_to_last_cacheable_block(blocks: list[dict[str, Any]], cache_control: Any) -> None:
    if not isinstance(cache_control, dict):
        return
    for block in reversed(blocks):
        if _block_type(block) in _CACHEABLE_TYPES:
            block.setdefault("cache_control", dict(cache_control))
            break


def _replay_ordered_blocks(m: dict[str, Any], ordered_blocks: list[Any]) -> Optional[list[dict[str, Any]]]:
    """Interleaved-thinking replay: rebuild the assistant turn from the verbatim block list
    normalize_response stored (only for turns interleaving SIGNED thinking with tool_use).
    Preserves block ORDER; returns None if nothing survives. tool_use ``input`` is re-sourced from
    ``tool_calls`` (redacted at storage time) rather than the captured block (raw API response, NOT
    redacted), so a secret the model inlined into a tool call never goes back on the wire."""
    redacted_input_by_id = {
        _sanitize_tool_id(tc.get("id", "")): _parse_tool_args((tc.get("function", {}) or {}).get("arguments", "{}"))
        for tc in m.get("tool_calls", []) or []
        if isinstance(tc, dict)
    }
    replayed: list[dict[str, Any]] = []
    relocated_cc = None
    dropped_blank_text = False
    for b in ordered_blocks:
        clean = _sanitize_replay_block(b)
        if clean is None:
            dropped_blank_text = dropped_blank_text or _block_type(b) == "text"
            if (cc := _cache_control_of(b)) is not None:  # relocate a dropped block's breakpoint
                relocated_cc = cc
            continue
        if clean.get("type") == "tool_use" and (redacted := redacted_input_by_id.get(clean.get("id", ""))) is not None:
            clean["input"] = redacted
        replayed.append(clean)
    # Nothing cacheable survived (e.g. signed thinking + blank text): emit the placeholder so the
    # turn stays schema-valid and a relocated marker has a carrier.
    if not _has_block_type(replayed, _CACHEABLE_TYPES) and (dropped_blank_text or relocated_cc is not None):
        replayed.append(_text_block(_EMPTY_TEXT_PLACEHOLDER))
    if not replayed:
        return None
    _apply_assistant_cache_control_to_last_cacheable_block(replayed, relocated_cc)
    _apply_assistant_cache_control_to_last_cacheable_block(replayed, m.get("cache_control"))
    # prompt_caching marks an assistant turn with text by writing cache_control INTO ``content``
    # (not top-level). This path never reads ``content``, so carry that marker over or the
    # breakpoint is burned rather than relocated.
    msg_content = m.get("content")
    if isinstance(msg_content, list):
        inline_cc = next((cc for cc in map(_cache_control_of, msg_content) if cc is not None), None)
        _apply_assistant_cache_control_to_last_cacheable_block(replayed, inline_cc)
    return replayed


def assistant_replay_carrier(m: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """``(ordered, blocks)``: the sanitized ordered sidecar when any block survives it (the whole turn
    then replays from it), else the ``reasoning_details`` thinking blocks. Single owner of carrier
    precedence for conversion, accounting and rejected-signature mirrors."""
    ordered_blocks = m.get("anthropic_content_blocks")
    if isinstance(ordered_blocks, list) and ordered_blocks:
        replayed = _replay_ordered_blocks(m, ordered_blocks)
        if replayed:
            return True, replayed
    return False, _extract_preserved_thinking_blocks(m)
