from __future__ import annotations
from typing import Any

_EPHEMERAL_SCAFFOLDING_FLAGS = (
    "_empty_recovery_synthetic",
    "_empty_terminal_sentinel",
    "_thinking_prefill",
    "_verification_stop_synthetic",  # verify-on-stop nudge; the assistant candidate itself is NOT synthetic
    "_pre_verify_synthetic",
    "_kanban_stop_synthetic",  # kanban worker stop-guard
    "_dropped_toolcall_nudge",  # internal retry instruction; must not replay as user context
)


def _is_ephemeral_scaffolding(msg: Any) -> bool:
    """True when ``msg`` is internal recovery scaffolding that must never reach the durable transcript."""
    return isinstance(msg, dict) and any(msg.get(flag) for flag in _EPHEMERAL_SCAFFOLDING_FLAGS)
