from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


DEFAULT_CONTEXT_TIMEOUT_SECONDS = 120.0


DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS = 600.0


def resolve_context_compression_timeouts(compression_cfg: Optional[dict] = None) -> tuple[float, float]:
    """Return ``(idle_timeout_seconds, total_ceiling_seconds)``.
    ``idle_timeout_seconds <= 0`` disables the progress-aware wrapper. The ceiling is clamped to at least one
    idle window when the idle budget is positive."""
    idle = DEFAULT_CONTEXT_TIMEOUT_SECONDS
    ceiling = DEFAULT_CONTEXT_TOTAL_CEILING_SECONDS
    from .host_boundaries import compression_config
    cfg = compression_cfg if compression_cfg is not None else compression_config.get()
    if isinstance(cfg, dict):
        # Explicit 0/negative idle disables; a non-positive ceiling is ignored.
        with contextlib.suppress(TypeError, ValueError):
            if cfg.get("context_timeout_seconds") is not None:
                idle = float(cfg["context_timeout_seconds"])
        with contextlib.suppress(TypeError, ValueError):
            if cfg.get("context_total_ceiling_seconds") is not None and float(cfg["context_total_ceiling_seconds"]) > 0:
                ceiling = float(cfg["context_total_ceiling_seconds"])
    if idle > 0:
        ceiling = max(ceiling, idle)
        # #114594: the aux summary attempt legitimately needs up to its own budget (floor 300s), while the
        # host idle watchdog defaults to 120s. Clamp the idle window up to at least the effective aux
        # compression timeout so prep/chunking work with no streamed tokens yet is not cut off. Only raises:
        # an explicit cfg value above the aux budget is kept, and idle never exceeds the ceiling.
        from .auxiliary_client import _effective_aux_timeout
        _aux_budget = float(_effective_aux_timeout("compression", None))
        if _aux_budget > 0:
            ceiling = max(ceiling, _aux_budget)
            idle = max(idle, min(_aux_budget, ceiling))
    return idle, ceiling
