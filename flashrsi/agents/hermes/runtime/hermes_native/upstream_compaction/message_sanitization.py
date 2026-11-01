from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)
RC, R, RD = "reasoning_content", "reasoning", "reasoning_details"


def _tc_field(tc: Any, key: str) -> Any:
    """Read ``key`` from a tool-call entry that may be a dict or an SDK object."""
    return tc.get(key) if isinstance(tc, dict) else getattr(tc, key, None)


def _expand_tool_id_variants(values: tuple[Any, ...]) -> frozenset[str]:
    """Every wire spelling of one tool-call identifier: Responses bridges may expose the pairing
    id and response-item id separately or as ``call_id|response_item_id``; all alias ONE call."""
    variants: set[str] = set()
    for raw in values:
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            variants.add(value)
            variants.update(p for p in (part.strip() for part in value.split("|")) if p)
    return frozenset(variants)


def tool_call_id_variants(tc: Any) -> frozenset[str]:
    """Return all pairing-id variants carried by a tool-call entry."""
    return _expand_tool_id_variants(tuple(_tc_field(tc, k) for k in ("call_id", "id", "response_item_id")))


def tool_result_id_variants(tool_call_id: Any) -> frozenset[str]:
    """Return all matching variants for a role=tool ``tool_call_id``."""
    return _expand_tool_id_variants((tool_call_id,))


_REASONING_ECHO_RULES: tuple = (
    # (family, exact providers (raw), exact providers (lowered), model substrings (lowered), hosts)
    ("kimi", frozenset({"kimi-coding", "kimi-coding-cn"}), frozenset(), (), ("api.kimi.com", "moonshot.ai", "moonshot.cn")),
    ("deepseek", frozenset(), frozenset({"deepseek"}), ("deepseek",), ("api.deepseek.com",)),
    ("mimo", frozenset(), frozenset({"xiaomi"}), ("mimo",), ("api.xiaomimimo.com", "xiaomimimo.com")),
    # Portal stealth model that 400s on a tool-call turn without reasoning_content (f86276d2ebc).
    ("missingno", frozenset(), frozenset(), ("stealth/missingno",), ()),
)


_REASONING_ECHO_RULE_BY_FAMILY = {rule[0]: rule for rule in _REASONING_ECHO_RULES}


REASONING_CARRIERS = (RC, R, RD)


_ALL_CARRIERS = frozenset(REASONING_CARRIERS)


_DEFAULT_CARRIERS = frozenset({RC})


_LOCAL_CARRIERS = frozenset({RC, R})  # llama.cpp/SGLang read reasoning_content, vLLM/Ollama read reasoning


_REASONING_CARRIER_ROUTES: tuple = (
    # (carriers, providers (lowered), hosts) — evidence per row in the PR body / FINDINGS.
    (frozenset(), frozenset({"mistral", "groq", "cerebras", "sambanova"}),
     ("mistral.ai", "groq.com", "cerebras.ai", "sambanova.ai", "hunyuan.cloud.tencent.com")),
    # Fireworks' ChatMessage schema is additionalProperties:false with reasoning_content only.
    (frozenset({RC}), frozenset({"fireworks"}), ("fireworks.ai",)),
    # OpenRouter-format gateways read the unified array, the string and the alias.
    (_ALL_CARRIERS, frozenset({"openrouter", "kilocode", "ai-gateway", "nous"}),
     ("openrouter.ai", "kilo.ai", "ai-gateway.vercel.sh", "nousresearch.com")),
    # Vendors that document reasoning_details replay next to reasoning_content.
    (frozenset({RC, RD}), frozenset({"novita", "tencent-tokenhub", "minimax", "minimax-cn"}),
     ("novita.ai", "tokenhub.tencentmaas.com", "tokenhub-intl.tencentcloudmaas.com", "minimax.io", "minimaxi.com")),
    (_LOCAL_CARRIERS, frozenset({"ollama-cloud", "custom", "lmstudio", "upstage"}), ("ollama.com", "upstage.ai")),
)


class ReasoningReplayRoute(NamedTuple):
    """``pad``: must-echo tier (missing reasoning_content -> " "). ``carriers``: the reasoning
    keys an assistant wire copy carries; ``None`` outside chat_completions, where the native
    adapters own reasoning replay (only the must-echo pad is applied, details are untouched)."""

    pad: bool
    carriers: frozenset | None


def matches_reasoning_echo_family(family: str, provider: Any, model: Any, base_url: Any) -> bool:
    """True when (provider, model, base_url) matches one echo-back family (families can overlap;
    membership is tested independently). Raises KeyError for an unknown family."""
    from .utils import base_url_host_matches

    _, raw_providers, lowered_providers, model_subs, hosts = _REASONING_ECHO_RULE_BY_FAMILY[family]
    model_lower = (model or "").lower()
    return (
        provider in raw_providers or (provider or "").lower() in lowered_providers
        or any(sub in model_lower for sub in model_subs) or any(base_url_host_matches(base_url, host) for host in hosts)
    )


def reasoning_echo_family(provider: Any, model: Any, base_url: Any) -> str | None:
    """``"kimi"`` / ``"deepseek"`` / ``"mimo"`` (first match in table order) when the endpoint
    enforces reasoning_content echo-back on tool-call turns, else ``None``."""
    families = (rule[0] for rule in _REASONING_ECHO_RULES)
    return next((f for f in families if matches_reasoning_echo_family(f, provider, model, base_url)), None)


def needs_reasoning_echo(provider: Any, model: Any, base_url: Any) -> bool:
    """True when the endpoint requires reasoning_content echo-back (the must-echo tier)."""
    return reasoning_echo_family(provider, model, base_url) is not None


def route_reasoning_carriers(provider: Any, base_url: Any) -> frozenset:
    """Reasoning carriers the chat-completions route reads (before any runtime rejection)."""
    from .utils import base_url_host_matches

    provider_lower = (provider or "").strip().lower()
    carriers = next(
        (c for c, providers, hosts in _REASONING_CARRIER_ROUTES
         if provider_lower in providers or any(base_url_host_matches(base_url, h) for h in hosts)),
        None,
    )
    if carriers is None:
        from .model_metadata import is_local_endpoint

        carriers = _LOCAL_CARRIERS if base_url and is_local_endpoint(str(base_url)) else _DEFAULT_CARRIERS
    if RD not in carriers and carriers and _profile_declares_native_details(provider_lower):
        carriers = carriers | {RD}
    return carriers


def _profile_declares_native_details(provider_lower: str) -> bool:
    """A profile declaring ``native_reasoning_details_type`` consumes replayed details by contract."""
    if not provider_lower:
        return False
    from .host_boundaries import get_provider_profile

    return bool(getattr(get_provider_profile(provider_lower), "native_reasoning_details_type", None))


def reasoning_replay_route(
    api_mode: Any, provider: Any, model: Any, base_url: Any, *, echo_opt_in: bool = False,
    rejected: Iterable[str] = (),
) -> ReasoningReplayRoute:
    """Replay decision for one route. Deterministic in its inputs, so the wire prefix is byte-stable
    across turns and changes only on a route switch or a recorded rejection (``rejected``)."""
    pad = bool(echo_opt_in) or needs_reasoning_echo(provider, model, base_url)
    if (api_mode or "chat_completions") != "chat_completions":
        return ReasoningReplayRoute(pad, None)
    carriers = route_reasoning_carriers(provider, base_url) - frozenset(rejected)
    # A strict route never gets a reasoning key, not even the must-echo pad.
    return ReasoningReplayRoute(pad and RC in carriers, carriers)


def stale_thinking_reaches_wire(api_mode: Any, provider: Any, model: Any, base_url: Any) -> bool:
    """True when stale assistant reasoning text is actually replayed on the wire for the route.

    The single wire-truth predicate the compaction TRIGGER estimator and the tail-budget
    walks must share: if they disagree, a reasoning-heavy session can look over-threshold
    to preflight yet fully tail-protected to the walk — an infinite compaction loop.
    ``codex_responses`` never reads the text keys (continuity rides the encrypted sidecar).
    A runtime rejection is not visible here; both sides then over-charge identically.
    """
    if (api_mode or "") == "anthropic_messages":
        from .anthropic_thinking_policy import native_anthropic_preserves_prior_thinking
        if native_anthropic_preserves_prior_thinking(base_url, model):
            return True
    if not api_mode:
        # No route facts (a bare compressor): only the must-echo tier is known to replay.
        return needs_reasoning_echo(provider, model, base_url)
    route = reasoning_replay_route(api_mode, provider, model, base_url)
    if route.carriers is None:
        return (api_mode or "") != "codex_responses" and route.pad
    return bool(route.carriers & {RC, R})


def native_anthropic_accounting_projection(messages: Any) -> tuple[Any, tuple[str, ...]]:
    """Return the native Anthropic wire shadow plus readable replay thinking out-of-band.

    Canonical history may retain storage-only reasoning alongside signed replay carriers.
    Native conversion prefers ordered anthropic_content_blocks over reasoning_details and
    never sends reasoning itself. The generic message estimator therefore receives only
    ordinary wire-shaped fields, while readable thinking is returned separately for the
    explicit Anthropic accounting seam. Opaque signature/data bytes are never priced.
    """
    if not isinstance(messages, list):
        return messages, ()

    from .anthropic_message_convert import assistant_replay_carrier

    projected = []
    replayed_thinking: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            projected.append(message)
            continue

        # Mirror _convert_assistant_message's actual inputs instead of starting
        # from canonical storage. Context selection is allowed to return canonical
        # rows, which can contain timestamp/finish_reason/api_content and other
        # local metadata that native Anthropic never sees.
        shadow = {"role": "assistant"}
        for key in ("content", "tool_calls", "reasoning_content", "cache_control"):
            if key in message:
                shadow[key] = message[key]
        # Canonical input (preflight, tail walk) still holds the api_content sidecar that
        # build_api_messages substitutes into content; post-build input already carries it in
        # content. Charge it either way: an ordered turn, or a context-selection clone the
        # converter reads raw, then overcounts, never undercounts.
        sidecar = message.get("api_content")
        if isinstance(sidecar, str) and sidecar:
            shadow["content"] = sidecar

        _, carrier = assistant_replay_carrier(message)
        # The converter ignores reasoning_content for an ordered turn and only injects it when the
        # details carrier holds no thinking, so it must not be charged in addition to the carrier.
        if carrier:
            shadow.pop("reasoning_content", None)

        replayed_thinking.extend(
            block["thinking"]
            for block in carrier
            if block.get("type") == "thinking" and isinstance(block.get("thinking"), str) and block["thinking"]
        )
        projected.append(shadow)
    return projected, tuple(replayed_thinking)
