"""Upstream output limits bound to explicit per-invocation configuration.

Each call binds its owner's settings, including concurrent worker threads;
there is no process-wide profile or host configuration discovery.
"""

from contextvars import ContextVar

DEFAULT_MAX_BYTES = 50_000
DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_LINE_LENGTH = 2000
_limits: ContextVar[dict | None] = ContextVar("hermes_tool_output_limits", default=None)


def _coerce_int(value, default, minimum):
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return default
    return default if iv < minimum else iv


def resolve_limits(settings):
    section = settings.get("tool_output") if isinstance(settings, dict) else None
    if not isinstance(section, dict):
        section = {}
    return {
        name: _coerce_int(section.get(name), default, 1)
        for name, default in (
            ("max_bytes", DEFAULT_MAX_BYTES),
            ("max_lines", DEFAULT_MAX_LINES),
            ("max_line_length", DEFAULT_MAX_LINE_LENGTH),
        )
    }


def get_max_bytes():
    return (_limits.get() or {}).get("max_bytes", DEFAULT_MAX_BYTES)


def get_max_lines():
    return (_limits.get() or {}).get("max_lines", DEFAULT_MAX_LINES)


def get_max_line_length():
    return (_limits.get() or {}).get("max_line_length", DEFAULT_MAX_LINE_LENGTH)
