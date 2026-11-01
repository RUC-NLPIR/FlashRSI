from __future__ import annotations
from typing import Any, NamedTuple
from .boundaries import get_provider_profile

_REASONING_ECHO_RULES: tuple = (
    # (family, exact providers (raw), exact providers (lowered), model substrings (lowered), hosts)
    ("kimi", frozenset({"kimi-coding", "kimi-coding-cn"}), frozenset(), (), ("api.kimi.com", "moonshot.ai", "moonshot.cn")),
    ("deepseek", frozenset(), frozenset({"deepseek"}), ("deepseek",), ("api.deepseek.com",)),
    ("mimo", frozenset(), frozenset({"xiaomi"}), ("mimo",), ("api.xiaomimimo.com", "xiaomimimo.com")),
    # Portal stealth model that 400s on a tool-call turn without reasoning_content (f86276d2ebc).
    ("missingno", frozenset(), frozenset(), ("stealth/missingno",), ()),
)


_REASONING_ECHO_RULE_BY_FAMILY = {rule[0]: rule for rule in _REASONING_ECHO_RULES}


RC, R, RD = "reasoning_content", "reasoning", "reasoning_details"


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
    from .urls import base_url_host_matches

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
    from .urls import base_url_host_matches

    provider_lower = (provider or "").strip().lower()
    carriers = next(
        (c for c, providers, hosts in _REASONING_CARRIER_ROUTES
         if provider_lower in providers or any(base_url_host_matches(base_url, h) for h in hosts)),
        None,
    )
    if carriers is None:
        from ..upstream_compaction.model_metadata import is_local_endpoint

        carriers = _LOCAL_CARRIERS if base_url and is_local_endpoint(str(base_url)) else _DEFAULT_CARRIERS
    if RD not in carriers and carriers and _profile_declares_native_details(provider_lower):
        carriers = carriers | {RD}
    return carriers


def _profile_declares_native_details(provider_lower: str) -> bool:
    """A profile declaring ``native_reasoning_details_type`` consumes replayed details by contract."""
    if not provider_lower:
        return False
    from .boundaries import get_provider_profile

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


def _replayable_reasoning_text(msg: dict) -> str | None:
    """The turn's reasoning text: a non-blank ``reasoning_content`` wins over ``reasoning``."""
    for key in (RC, R):
        value = msg.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _apply_legacy_must_echo_pad(source_msg: dict, api_msg: dict) -> None:
    """Native-adapter wires (``carriers=None``): the pre-replay contract, byte-for-byte. An explicit
    value is kept verbatim (legacy "" upgraded to " "); a tool-call turn holding only another
    provider's ``reasoning`` is padded instead of converted into a native thinking block."""
    existing, reasoning = source_msg.get(RC), source_msg.get(R)
    if isinstance(existing, str):
        api_msg[RC] = existing or " "
    elif isinstance(reasoning, str) and reasoning and not source_msg.get("tool_calls"):
        api_msg[RC] = reasoning
    else:
        api_msg[RC] = " "


def apply_reasoning_content_policy(
    source_msg: dict, api_msg: dict, needs_thinking_pad: bool, carriers: frozenset | None = None,
) -> None:
    """Shape an assistant replay message's reasoning keys for the active route (mutates ``api_msg``).

    ``needs_thinking_pad`` is the must-echo flag; ``carriers`` the keys the route reads
    (``reasoning_replay_route``). ``carriers=None`` is a non-chat-completions wire: only the
    must-echo ``reasoning_content`` rides there and ``reasoning_details`` is left to the adapter.
    Keys the route does not read are removed, so a strict host never sees one (#45655, #70233).
    """
    if source_msg.get("role") != "assistant":
        return
    text = _replayable_reasoning_text(source_msg)
    effective = carriers if carriers is not None else (frozenset({RC}) if needs_thinking_pad else frozenset())
    if carriers is None and needs_thinking_pad:
        _apply_legacy_must_echo_pad(source_msg, api_msg)
    elif RC in effective and (text is not None or needs_thinking_pad):
        # Must-echo tier: every assistant turn carries the field; " " (not "") when there is no
        # text, because DeepSeek V4 rejects empty string (#17341) and a legacy "" pad upgrades.
        api_msg[RC] = text if text is not None else " "
    else:
        # Also drops a non-string value (None after compaction) and a whitespace pad written
        # for a must-echo provider: never pass null, never replay a pad as reasoning.
        api_msg.pop(RC, None)
    if R in effective and text is not None:
        api_msg[R] = text
    else:
        api_msg.pop(R, None)
    if carriers is not None and RD not in carriers:
        # Private ``*.native_assistant`` records (Gemini/Copilot carriers) survive: the transport lifts
        # them onto the route that reads them and filters them from every other wire.
        private = [d for d in api_msg.pop(RD, None) or () if isinstance(d, dict)
                   and str(d.get("type") or "").endswith(".native_assistant")]
        if private:
            api_msg[RD] = private
