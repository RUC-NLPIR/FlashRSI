from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)
from .auxiliary_client import AuxiliaryExplicitCancellation
from .conversation_compression_deadline import resolve_context_compression_timeouts


_COMPRESSOR_ATTEMPT_LOCK = threading.Lock()


_COMPRESSOR_ATTEMPT_GENERATION: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "hermes_compressor_attempt_generation", default=None
)


def _raise_if_stale_attempt(compressor: Any) -> None:
    """Unwind the CALLING attempt (its generation rides the ContextVar) as a cancellation when a newer
    attempt has since begun summary work on *compressor*, so none of the shared-state writes that
    follow the call site can land."""
    if not _caller_attempt_is_current(compressor):
        raise AuxiliaryExplicitCancellation()


def _caller_attempt_is_current(compressor: Any) -> bool:
    """Working-attempt check for the calling attempt's own generation (ContextVar; None → unguarded)."""
    return _working_attempt_is_current(compressor, _COMPRESSOR_ATTEMPT_GENERATION.get())


def _working_attempt_is_current(compressor: Any, generation: Any) -> bool:
    """True when *generation* is still the last attempt that began summary work.

    Without a published marker (attribute-less compressor, or the attempt never reached
    dispatch) supersession falls back to the entry-generation ownership check; a compressor
    that no attempt has ever claimed cannot have been superseded."""
    if not generation:
        return True
    with _COMPRESSOR_ATTEMPT_LOCK:
        marker = getattr(compressor, "_compression_working_attempt_generation", None)
        if marker is None:
            entry_generation = int(getattr(compressor, "_compression_attempt_generation", 0) or 0)
            return not entry_generation or entry_generation == generation
        return int(marker) == int(generation)


_SYNTHETIC_USER_PREFIXES = (
    "[System: Your previous response was truncated", "[System: The previous response was cut off",
    "[System: Your previous tool call", "[Your active task list was preserved across context compression]",
    "[IMPORTANT: Background process ",
)


def _message_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or part.get("content") or "") for part in content if isinstance(part, dict)
        )
    return ""


_SYNTHETIC_USER_FLAGS = (
    "_todo_snapshot_synthetic", "_empty_recovery_synthetic", "_verification_stop_synthetic", "_pre_verify_synthetic",
    "_dropped_toolcall_nudge",
)


def _is_real_user_message(message: Any) -> bool:
    """Distinguish human intent from user-role runtime scaffolding.
    A compaction summary flipped to ``role="user"`` for alternation is scaffolding and must not short-circuit
    anchor restoration."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    if any(message.get(flag) for flag in _SYNTHETIC_USER_FLAGS):
        return False
    text = _message_text(message).strip()
    if not text or text.startswith(_SYNTHETIC_USER_PREFIXES):
        return False
    from .context_compressor import ContextCompressor
    return not ContextCompressor._is_synthetic_compression_user_turn(message)


_PRUNED_SKILL_RELOAD_NOTICE_HEADER = "[Skills pruned during compression — reload before acting on these tasks]"

from .conversation_compression_watermark import held_archive_watermark
