from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)
from ..policy import strip_think_blocks, _REASONING_BLOCK_PATTERNS
from .message_sanitization import tool_call_id_variants, tool_result_id_variants


def _classify_tool_call_orphans(messages: list[dict[str, Any]]):
    """Classify orphaned tool-call / tool-result pairs; single source of truth for GLOBAL orphan
    detection. Returns ``(surviving_call_ids, result_call_ids, orphaned_results, missing_tool_calls)``;
    every id variant of a tool_call is registered so a result matching any alias survives, and
    ``orphaned_results`` are the actual dicts (filter by ``id(msg)``). ``sanitize_api_messages``
    pairs positionally instead but shares the ``*_id_variants`` alias policy."""
    assistant_call_variants = [
        (tc, variants)
        for msg in messages if msg.get("role") == "assistant"
        for tc in msg.get("tool_calls") or []
        if (variants := tool_call_id_variants(tc))
    ]
    surviving_call_ids: set[str] = set().union(*(v for _, v in assistant_call_variants))
    result_entries = [
        (msg, tool_result_id_variants(msg.get("tool_call_id"))) for msg in messages if msg.get("role") == "tool"
    ]
    result_call_ids: set[str] = set().union(*(v for _, v in result_entries))
    orphaned_results = [msg for msg, v in result_entries if v and not (v & surviving_call_ids)]
    # Orphan result variants are disjoint from every declared call, so they
    # cannot contribute a match. Reuse the union instead of scanning each result.
    missing_tool_calls = [
        tc for tc, v in assistant_call_variants if not (v & result_call_ids)
    ]
    return surviving_call_ids, result_call_ids, orphaned_results, missing_tool_calls
