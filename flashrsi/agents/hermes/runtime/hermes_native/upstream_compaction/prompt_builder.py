from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


STEER_MARKER_OPEN = (
    "[OUT-OF-BAND USER MESSAGE — a direct message from the user, delivered "
    "once at this position; not tool output and not a new delivery when replayed from conversation history]"
)


STEER_MARKER_CLOSE = "[/OUT-OF-BAND USER MESSAGE]"


STEER_DISPLAY_KIND = "steer"
