"""Explicit route metadata replacing upstream ambient profile/catalog state."""

from contextvars import ContextVar
from types import SimpleNamespace

from .reasoning_effort import clamp_effort

request_settings = ContextVar("hermes_chat_settings", default={})
GROK_AGGREGATOR_MODEL_PREFIXES = ("x-ai/grok-", "xai/grok-")


def get_affinity_scope():
    return request_settings.get().get("affinity_scope")


def get_conversation_context():
    return request_settings.get().get("conversation_context")


def is_fork_cache_scope(scope):
    return isinstance(scope, str) and "::" in scope


def openrouter_model_reasoning_capabilities(model):
    caps = request_settings.get().get("reasoning_capabilities")
    return caps.get(model) if isinstance(caps, dict) and model in caps else caps


def clamp_reasoning_effort_to_supported(effort, supported_efforts):
    return clamp_effort(effort, supported_efforts)


def get_version_info():
    return SimpleNamespace(base_version="0.22.5")


def nous_portal_tags(session_id=None):
    tags = ["product=hermes-agent", "client=hermes-client-v0.22.5"]
    effective = get_conversation_context() or session_id
    if effective:
        tags.append(f"conversation={effective}")
    return tags


def nous_model_reasoning_capabilities(model):
    caps = request_settings.get().get("nous_reasoning_capabilities")
    return caps.get(model) if isinstance(caps, dict) and model in caps else caps


def warm_nous_reasoning_caps_async():
    # Cold catalog follows the source profile's conservative omission path;
    # replay captures the subsequently discovered rows explicitly.
    return None


def github_model_reasoning_efforts(model):
    return (request_settings.get().get("github_reasoning_efforts") or {}).get(model)


def clamp_github_reasoning_effort(effort, supported):
    effort = str(effort or "medium").strip().lower()
    if effort not in supported:
        effort = clamp_effort(effort, supported)
        if effort not in supported:
            effort = "medium" if "medium" in supported else supported[0]
    return effort
