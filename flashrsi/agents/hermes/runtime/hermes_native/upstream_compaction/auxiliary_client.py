from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


logger = logging.getLogger(__name__)


class AuxiliaryExplicitCancellation(BaseException):
    """Frozen signal that an auxiliary attempt was explicitly hard-cancelled. ``BaseException`` so broad
    ``except Exception`` retry/fallback code never treats a host stop as a transport failure; ``cause``
    is immutable class data so nothing re-queries a mutable host Event after the transport unwound."""
    cause = "explicit_host_cancel"

    def __init__(self) -> None:
        super().__init__("auxiliary request explicitly cancelled by host")


CODEX_STREAM_STALL_MARKER = "stream stalled"


def _coerce_llm_message(response):
    """Pull a message (dict, object, or str) out of a response-or-message value: dict-shaped
    responses/bare messages (compression, proxies) and ChatCompletion objects; MagicMock
    ``reasoning_*`` attrs are deliberately not strings."""
    if response is None or isinstance(response, str):
        return response
    if isinstance(response, dict):
        if "choices" not in response:
            return response
        choices = response.get("choices") or []
    else:
        choices = getattr(response, "choices", None)
        if not choices:
            return response
    return _message_field(choices[0], "message") if choices else None


def _message_field(msg, name):
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


def extract_content_or_reasoning(response, *, max_reasoning_chars: int | None = None) -> str:
    """Extract content from an LLM response, falling back to reasoning fields.
    Order: ``content`` (inline think blocks stripped) → ``reasoning``/``reasoning_content`` →
    ``reasoning_details`` (OpenRouter array). Accepts a response or bare message;
    ``max_reasoning_chars`` bounds a reasoning fallback so unbounded chain-of-thought can't
    become the compaction summary. Returns ``""`` if nothing found."""
    msg = _coerce_llm_message(response)
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg.strip()
    raw = _message_field(msg, "content")
    if not isinstance(raw, str):
        raw = str(raw) if raw else ""
    content = raw.strip()
    if content:
        # Same precompiled closed-pair patterns as strip_think_blocks.
        from .agent_runtime_helpers import _REASONING_BLOCK_PATTERNS
        cleaned = content
        for pattern in _REASONING_BLOCK_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            return cleaned
    # Content is empty or reasoning-only — try structured reasoning fields
    reasoning_parts: list[str] = []
    for field in ("reasoning", "reasoning_content"):
        val = _message_field(msg, field)
        if val and isinstance(val, str) and val.strip() and val not in reasoning_parts:
            reasoning_parts.append(val.strip())
    details = _message_field(msg, "reasoning_details")
    if details and isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                summary = detail.get("summary") or detail.get("content") or detail.get("text")
                if summary and summary not in reasoning_parts:
                    reasoning_parts.append(summary.strip() if isinstance(summary, str) else str(summary))
    if not reasoning_parts:
        return ""
    text = "\n\n".join(reasoning_parts)
    if max_reasoning_chars is not None and len(text) > max_reasoning_chars:
        logger.warning("fell back to reasoning fields (%d chars); truncating to %d",
                       len(text), max_reasoning_chars)
        return text[:max_reasoning_chars]
    return text

# Explicit callback replaces upstream provider discovery/client creation only.
from contextvars import ContextVar
callback = ContextVar('hermes_compression_sync_callback', default=None)
aux_interrupt_protection = contextlib.nullcontext

def call_llm(**kwargs):
    dispatch = callback.get()
    if dispatch is None:
        raise RuntimeError('No provider available for explicit compression runtime')
    return dispatch(**kwargs)

def _effective_aux_timeout(task, timeout):
    return max(300.0, float(timeout or 300.0))

def _is_connection_error(exc):
    if any(x in type(exc).__name__ for x in ('Connection', 'Timeout', 'DNS', 'SSL')):
        return True
    return any(x in str(exc).lower() for x in (
        'connection refused', 'name or service not known', 'no route to host',
        'network is unreachable', 'timed out', 'connection reset',
        'incomplete chunked read', 'peer closed connection', 'response ended prematurely',
        'unexpected eof', 'remoteprotocolerror', 'localprotocolerror'))
