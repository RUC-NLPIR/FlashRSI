"""Explicit I/O boundaries for the pinned Chat/Responses recovery policies.

OAuth/credential pools, account entitlement discovery, Bedrock,
catalogue refresh and lazy dependency installation are outside this runtime.
These gates do not replace any supported payload-recovery policy.
"""

import copy

from ..upstream_compaction.anthropic_thinking_replay import (
    remember_rejected_thinking,
    tracks_rejected_thinking,
)
from .fast_mode import fast_mode_unprovisioned, mark_fast_mode_unavailable

REASONING_FLOOR_EFFORT = "low"
DB_ROW_SNAPSHOT = "_db_row_snapshot"
_DB_PERSISTED_MARKER = "_db_persisted"
_clone_message_for_send = copy.deepcopy


def drop_stale_api_content(message):
    message.pop("api_content", None)


def _recover_welcome_tier(*args, **kwargs):
    return False


def _pool_error_context(agent, classified, context):
    return context


def _try_refresh_nous_paid_entitlement_credentials(*args, **kwargs):
    return False


def _refresh_credentials_after_401(*args, **kwargs):
    return False


def _is_nous_inference_route(*args, **kwargs):
    return False


def refresh_reasoning_caps_async(*args, **kwargs):
    return None


def ensure_import(*args, **kwargs):
    raise ImportError("Snapshot dependencies must be installed explicitly")


def unset_reasoning_default(agent):
    # Chat's original profile resolution has already run in chat_transport;
    # the passed config is the resolved profile default or explicit config.
    return None
