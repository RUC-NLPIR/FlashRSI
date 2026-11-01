from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


def drop_stale_api_content(msg: dict[str, Any]) -> None:
    """Drop the ``api_content`` sidecar from a message whose content was rewritten
    (replaying it would resend what the rewrite removed; cost is one cache miss)."""
    msg.pop("api_content", None)
