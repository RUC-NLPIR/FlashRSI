from __future__ import annotations
from contextvars import ContextVar
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


DEFAULT_IMAGE_TOKEN_COST = 1500


_image_cost_var: ContextVar[Optional[int]] = ContextVar("hermes_image_token_cost", default=None)


def current_image_token_cost() -> int:
    """Per-image cost bound for the running turn (see :func:`image_cost_context`), else the default."""
    bound = _image_cost_var.get()
    return bound if bound is not None else DEFAULT_IMAGE_TOKEN_COST
