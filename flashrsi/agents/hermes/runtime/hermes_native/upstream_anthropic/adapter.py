from __future__ import annotations
import logging,math,re
from typing import Any,Dict,List,Optional
from .endpoints import (_base_url_needs_context_1m_beta,_is_azure_anthropic_endpoint,_is_kimi_coding_endpoint,_is_minimax_anthropic_endpoint,_is_nous_portal_endpoint,_is_opencode_endpoint,_is_third_party_anthropic_endpoint,_model_name_is_kimi_family,_normalize_base_url_text,_requires_bearer_auth)
from .credentials import _is_oauth_token
from .message_convert import convert_messages_to_anthropic,convert_tools_to_anthropic,normalize_model_name
from ..upstream_chat.boundaries import get_version_info
logger=logging.getLogger(__name__)
logger = logging.getLogger(__name__)


THINKING_BUDGET = {"xhigh": 32000, "high": 16000, "medium": 8000, "low": 4000}


ADAPTIVE_EFFORT_MAP = {
    "ultra": "max", "max": "max", "xhigh": "xhigh", "high": "high", "medium": "medium", "low": "low",
    "minimal": "low",
}


_LEGACY_MANUAL_THINKING_CLAUDE_SUBSTRINGS = (
    "claude-3", "claude-opus-4-0", "claude-opus-4.0", "claude-opus-4-1", "claude-opus-4.1",
    "claude-sonnet-4-0", "claude-sonnet-4.0", "claude-opus-4-2025", "claude-sonnet-4-2025",
    "claude-opus-4-5", "claude-opus-4.5", "claude-sonnet-4-5", "claude-sonnet-4.5", "claude-haiku-4-5",
    "claude-haiku-4.5",
)


_NO_XHIGH_CLAUDE_SUBSTRINGS = ("claude-opus-4-6", "claude-opus-4.6", "claude-sonnet-4-6", "claude-sonnet-4.6")


_MANDATORY_THINKING_CLAUDE_SUBSTRINGS = ("claude-fable", "claude-opus-5-5", "claude-opus-5.5")


_BETWEEN_TOOLS_OFF_CLAUDE_SUBSTRINGS = ("claude-sonnet-5-5", "claude-sonnet-5.5")


def _is_claude_model(model: str | None) -> bool:
    return "claude" in (model or "").lower()


def _model_matches(model: str, substrings) -> bool:
    """Case-insensitive substring match of ``model`` against a family list."""
    m = model.lower()
    return any(v in m for v in substrings)


_ANTHROPIC_OUTPUT_LIMITS = {
    "claude-fable": 128_000, "claude-sonnet-5": 128_000, "claude-opus-4-8": 128_000,
    "claude-opus-4-7": 128_000, "claude-opus-4-6": 128_000, "claude-sonnet-4-6": 64_000,
    "claude-opus-4-5": 64_000, "claude-sonnet-4-5": 64_000, "claude-haiku-4-5": 64_000,
    "claude-opus-4": 32_000, "claude-sonnet-4": 64_000, "claude-3-7-sonnet": 128_000,
    "claude-3-5-sonnet": 8_192, "claude-3-5-haiku": 8_192, "claude-3-opus": 4_096,
    "claude-3-sonnet": 4_096, "claude-3-haiku": 4_096, "minimax": 131_072, "qwen3": 65_536,
}


_ANTHROPIC_DEFAULT_OUTPUT_LIMIT = 128_000


def _get_anthropic_max_output(model: str) -> int:
    """Max output tokens for ``model`` via longest substring match against
    ``_ANTHROPIC_OUTPUT_LIMITS`` (so date-stamped ids and ``:1m``/``:fast`` suffixes resolve, and
    ``claude-3-5-sonnet`` beats ``claude-3-5``). Dots normalize to hyphens (``claude-opus-4.6``)."""
    m = model.lower().replace(".", "-")
    best_key = max((key for key in _ANTHROPIC_OUTPUT_LIMITS if key in m), key=len, default=None)
    return _ANTHROPIC_OUTPUT_LIMITS[best_key] if best_key else _ANTHROPIC_DEFAULT_OUTPUT_LIMIT


def _resolve_positive_anthropic_max_tokens(value) -> Optional[int]:
    """``value`` floored to a positive int, or None when it is not a finite positive number.
    Anthropic 400s on max_tokens that are 0, negative, fractional or non-finite; the ``max_tokens
    or fallback`` idiom catches 0 but lets ``-1``/``0.5`` through. Booleans are excluded (they
    subclass int)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
    except Exception:  # e.g. OverflowError for ints too large for float
        return None
    return int(value) if int(value) > 0 else None  # int() truncates toward zero for floats


def _resolve_anthropic_messages_max_tokens(requested, model: str, context_length: Optional[int] = None) -> int:
    """``requested`` when it is a positive finite number, else the model's output ceiling. Raises
    ValueError if neither is positive. The context-window clamp is the caller's job so the
    positive-value contract stays endpoint-agnostic."""
    resolved = _resolve_positive_anthropic_max_tokens(requested) or _get_anthropic_max_output(model)
    if resolved > 0:
        return resolved
    raise ValueError(
        f"Anthropic Messages adapter requires a positive max_tokens value for "
        f"model {model!r}; got {requested!r} and no model default resolved."
    )


def _supports_adaptive_thinking(model: str) -> bool:
    """True for Claude models using adaptive thinking (4.6+): unknown Claude models default to
    adaptive, the explicit legacy list stays manual, and non-Claude models return False — except
    Kimi/Moonshot, whose Anthropic-compatible endpoints implement the adaptive contract."""
    return _model_name_is_kimi_family(model) or (
        _is_claude_model(model) and not _model_matches(model, _LEGACY_MANUAL_THINKING_CLAUDE_SUBSTRINGS)
    )


def _supports_xhigh_effort(model: str) -> bool:
    """True for models accepting the 'xhigh' effort (Opus 4.7+). Opus/Sonnet 4.6 400 on it —
    callers downgrade xhigh->max when this returns False."""
    return _supports_adaptive_thinking(model) and not _model_matches(model, _NO_XHIGH_CLAUDE_SUBSTRINGS)


def _accepts_thinking_disable(model: str) -> bool:
    """True when ``model`` accepts an explicit ``thinking: {"type": "disabled"}``. Adaptive Claude
    thinks by default, so "off" only works if the disable is sent; mandatory-thinking families
    400 on it and keep the omit behavior. Legacy manual-thinking models are opt-in via
    budget_tokens, so omission is already off. Scoped to Claude: Kimi's documented disable is
    omission, and sending it a new parameter on the strength of Claude's contract is a guess."""
    return (
        _is_claude_model(model)
        and _supports_adaptive_thinking(model)
        and not _model_matches(model, _MANDATORY_THINKING_CLAUDE_SUBSTRINGS + _BETWEEN_TOOLS_OFF_CLAUDE_SUBSTRINGS)
    )


def _is_pre_thinking_haiku(model: str) -> bool:
    """Haiku generations that never get a thinking request (through 4.5). Haiku 5.5+ uses adaptive thinking."""
    from .thinking_policy import claude_family_version

    if "haiku" not in model.lower():
        return False
    parsed = claude_family_version(model)
    return parsed is None or parsed[0] != "haiku" or parsed[1] < (5, 5)


def _forbids_sampling_params(model: str) -> bool:
    """True for models that 400 on any non-default temperature/top_p/top_k (Opus 4.7 and later;
    unknown Claude defaults to forbidding). The 4.6 family and the legacy manual-thinking families
    still accept them. Callers omit the fields entirely — the API rejects anything non-null."""
    return _is_claude_model(model) and not _model_matches(
        model, _NO_XHIGH_CLAUDE_SUBSTRINGS + _LEGACY_MANUAL_THINKING_CLAUDE_SUBSTRINGS
    )


def _supports_fast_mode(model: str) -> bool:
    """True for models accepting ``speed: "fast"`` (Opus 4.8 / Opus 5 / Opus 5.5, Claude API only).
    The list lives in ``agent.model_metadata`` so the wire gate and the ``/fast`` toggle agree."""
    from .metadata import is_anthropic_fast_mode_model

    return is_anthropic_fast_mode_model(model)


_TOOL_STREAMING_BETA = "fine-grained-tool-streaming-2025-05-14"


_COMMON_BETAS = ["interleaved-thinking-2025-05-14", _TOOL_STREAMING_BETA]


_CONTEXT_1M_BETA = "context-1m-2025-08-07"


_FAST_MODE_BETA = "fast-mode-2026-02-01"


_OAUTH_ONLY_BETAS = ["claude-code-20250219", "oauth-2025-04-20"]


_CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."


_MCP_TOOL_PREFIX = "mcp__"


_OAUTH_TOOL_NAME_ALIASES = {"session_search": "chat_history_lookup", "memory": "context_notes"}


_OAUTH_TOOL_NAME_REVERSE_ALIASES = {wire_name: name for name, wire_name in _OAUTH_TOOL_NAME_ALIASES.items()}


_OAUTH_PROSE_ALIAS_NAMES = frozenset({"session_search"})


_OAUTH_PROSE_ALIAS_PATTERNS = tuple(
    (re.compile(rf"\b{re.escape(name)}\b"), _OAUTH_TOOL_NAME_ALIASES[name])
    for name in sorted(_OAUTH_PROSE_ALIAS_NAMES)
)


def _apply_oauth_prose_aliases(text: str) -> str:
    """Rewrite prose-safe tool-name tokens to their OAuth wire aliases."""
    for pattern, wire_name in _OAUTH_PROSE_ALIAS_PATTERNS:
        text = pattern.sub(wire_name, text)
    return text


def _common_betas_for_base_url(base_url: str | None, *, drop_context_1m_beta: bool = False) -> list[str]:
    """Beta headers safe for the configured endpoint. MiniMax (Bearer-auth) rejects both the
    fine-grained-tool-streaming beta (every tool-use message errors) and the 1M-context beta.
    Azure AI Foundry also uses Bearer auth but keeps both — it needs the 1M beta for 1M context,
    which native Anthropic does not get by default (some subscriptions reject it; Bedrock opts in
    via its own client helper). ``drop_context_1m_beta`` strips the 1M beta after a
    subscription/endpoint rejected it."""
    betas = list(_COMMON_BETAS)
    if _base_url_needs_context_1m_beta(base_url) and not drop_context_1m_beta:
        betas.append(_CONTEXT_1M_BETA)
    if _is_minimax_anthropic_endpoint(base_url):
        return [b for b in betas if b not in (_TOOL_STREAMING_BETA, _CONTEXT_1M_BETA)]
    return betas


def _beta_header(betas: list) -> dict[str, str]:
    """``{"anthropic-beta": ...}`` when there are betas, else ``{}``."""
    return {"anthropic-beta": ",".join(betas)} if betas else {}


def _attribution_headers() -> dict[str, str]:
    """Same client-attribution set sent to OpenRouter / Vercel AI Gateway / Fireworks."""
    return {
        "HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent",
        "User-Agent": f"HermesAgent/{get_version_info().base_version}",
    }


def _client_timeout(timeout):
    """httpx.Timeout with the caller's read timeout (default 900s) and a 10s connect."""
    from httpx import Timeout
    read = timeout if (isinstance(timeout, (int, float)) and timeout > 0) else 900.0
    return Timeout(timeout=float(read), connect=10.0)


def _base_client_kwargs(base_url, timeout) -> tuple[str, dict[str, Any]]:
    """Shared SDK constructor kwargs -> ``(normalized_base_url, kwargs)``. Retry is delegated to
    hermes's outer loop (``max_retries=0``): the SDK default of 2 uses its own backoff that ignores
    Retry-After and double-retries inside our loop. Any trailing ``/v1`` is stripped because the
    SDK appends ``/v1/messages``. Azure's ``api-version`` goes through ``default_query`` so the
    base_url is not corrupted into ``/anthropic?api-version=.../v1/messages``."""
    kwargs: dict[str, Any] = {"timeout": _client_timeout(timeout), "max_retries": 0}
    normalized = re.sub(r"/v1/?$", "", _normalize_base_url_text(base_url).rstrip("/"))
    if normalized:
        kwargs["base_url"] = normalized
        if _is_azure_anthropic_endpoint(normalized) and "api-version" not in normalized:
            kwargs["default_query"] = {"api-version": "2025-04-15"}
    return normalized, kwargs


def _auth_style(api_key, base_url, normalized_base_url) -> str:
    """Order-sensitive endpoint/key classification for :func:`build_anthropic_client`. ``kimi``:
    Kimi's /coding endpoint 403s without a User-Agent (the Kimi team asked for proper attribution).
    ``bearer``: MiniMax & co. want Authorization: Bearer — checked before the OAuth shape test
    because their secrets lack the sk-ant-api prefix and would be misread as OAuth/setup tokens.
    ``api_key``: third-party proxies use their own x-api-key keys (skip OAuth detection). ``oauth``:
    Bearer auth + Claude Code identity (Anthropic routes OAuth by user-agent; without it, 500s)."""
    if _is_kimi_coding_endpoint(base_url):
        return "kimi"
    if _requires_bearer_auth(normalized_base_url):
        return "bearer"
    if _is_third_party_anthropic_endpoint(base_url):
        return "api_key"
    if _is_oauth_token(api_key):
        return "oauth"
    return "api_key"


def _normalize_to_mcp_wire(name: str) -> str:
    """OAuth wire form of a tool name (no aliasing): ``mcp__<...>``. Anthropic's OAuth billing
    classifier treats a single-underscore ``mcp_`` tool name as a third-party-app fingerprint
    (HTTP 400 "Third-party apps now draw from extra usage"); ``mcp__foo`` is accepted. Both bare
    Hermes tools (``read_file``) and native MCP tools registered as ``mcp_<server>_<tool>`` must
    land on the double-underscore form. normalize_response reverses both via registry lookup."""
    if name.startswith("mcp__"):
        return name  # already correct, don't double-prefix
    return _MCP_TOOL_PREFIX + name.removeprefix("mcp_")


def _oauth_wire_namer(anthropic_tools: list[dict[str, Any]]):
    """Return ``name -> OAuth wire name`` for this request's tool set. An alias must never collide
    with a wire name owned by a non-alias tool: two identical tool names in one request is a hard
    400, strictly worse than the bug being fixed. Mirrors normalize_response's "registered tool
    wins" so outbound and inbound agree on who owns a contested name."""
    claimed = {
        _normalize_to_mcp_wire(tool["name"])
        for tool in (anthropic_tools or [])
        if isinstance(tool.get("name"), str) and tool["name"] not in _OAUTH_TOOL_NAME_ALIASES
    }

    def to_wire(name: str) -> str:
        aliased = _OAUTH_TOOL_NAME_ALIASES.get(name)
        if aliased and _MCP_TOOL_PREFIX + aliased not in claimed:
            name = aliased
        return _normalize_to_mcp_wire(name)

    return to_wire


_OAUTH_SYSTEM_REPLACEMENTS = (
    ("Hermes Agent", "Claude Code"), ("Hermes agent", "Claude Code"), ("Nous Research", "Anthropic"),
)


_OAUTH_SLUG_PATTERN = re.compile(r"""(?<![\w./:@'"`-])hermes-agent(?![\w/@-]|\.\w)""")


def _apply_claude_code_identity(system, anthropic_tools, anthropic_messages, to_wire):
    """OAuth transforms: Claude Code system prefix, product-name sanitizing (avoids server-side
    content filters), tool/description aliasing, and the same tool renames on replayed tool_use
    blocks so history matches ``tools[]``. Returns the new ``system``; tools and messages are
    mutated in place."""
    cc_block = {"type": "text", "text": _CLAUDE_CODE_SYSTEM_PREFIX}
    if isinstance(system, str) and system:
        system = [{"type": "text", "text": system}]
    system = [cc_block] + (system if isinstance(system, list) else [])
    for block in system:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            for old, new in _OAUTH_SYSTEM_REPLACEMENTS:
                text = text.replace(old, new)
            text = _OAUTH_SLUG_PATTERN.sub("claude-code", text)
            block["text"] = _apply_oauth_prose_aliases(text)
    for tool in anthropic_tools or []:
        if "name" in tool:
            tool["name"] = to_wire(tool["name"])
        if isinstance(tool.get("description"), str):
            tool["description"] = _apply_oauth_prose_aliases(tool["description"])  # prose-safe aliases only
    for msg in anthropic_messages:
        for block in msg.get("content") if isinstance(msg.get("content"), list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and "name" in block:
                block["name"] = to_wire(block["name"])  # tool_result pairs by id, not name
    return system


def _thinking_kwargs(reasoning_config: dict[str, Any], model: str, effective_max_tokens: int) -> dict[str, Any]:
    """Map ``reasoning_config`` to Anthropic thinking kwargs. Adaptive models (Claude 4.6+,
    Kimi/Moonshot) get ``thinking.type=adaptive`` + ``output_config.effort``; older models and
    manual-only compat endpoints (MiniMax) get budget_tokens. Haiku through 4.5 gets none. On
    4.7+ ``thinking.display`` defaults to "omitted", hiding the reasoning Hermes shows in its CLI,
    so "summarized" is requested to keep the activity feed populated."""
    if reasoning_config.get("enabled") is False:
        # Adaptive models think by DEFAULT, so omitting the parameter is not a disable — the user
        # silently keeps paying. Mandatory-thinking models 400 on the disable, so they keep the
        # omission: a silently-ignored disable beats a dead turn.
        if _model_matches(model, _BETWEEN_TOOLS_OFF_CLAUDE_SUBSTRINGS):
            return {"thinking": {"type": "between_tools"}}
        return {"thinking": {"type": "disabled"}} if _accepts_thinking_disable(model) else {}
    if _is_pre_thinking_haiku(model):
        return {}
    effort = str(reasoning_config.get("effort", "medium")).lower()
    if _supports_adaptive_thinking(model):
        adaptive_effort = ADAPTIVE_EFFORT_MAP.get(effort, "medium")
        if adaptive_effort == "xhigh" and not _supports_xhigh_effort(model):
            adaptive_effort = "max"
        return {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": adaptive_effort}}
    budget = THINKING_BUDGET.get(effort, 8000)
    return {
        "thinking": {"type": "enabled", "budget_tokens": budget},
        "temperature": 1,  # required when thinking is enabled on older models
        "max_tokens": max(effective_max_tokens, budget + 4096),
    }


_TOOL_CHOICE_MAP = {None: {"type": "auto"}, "auto": {"type": "auto"}, "required": {"type": "any"}}


def build_anthropic_kwargs(
    model: str, messages: list[dict], tools: Optional[list[dict]], max_tokens: Optional[int],
    reasoning_config: Optional[dict[str, Any]], tool_choice: Optional[str] = None,
    is_oauth: bool = False, preserve_dots: bool = False, context_length: Optional[int] = None,
    base_url: str | None = None, fast_mode: bool = False, drop_context_1m_beta: bool = False,
) -> dict[str, Any]:
    """Build kwargs for anthropic.messages.create(). ``max_tokens`` is the OUTPUT cap for one
    response; ``context_length`` is the TOTAL window (input + output). ``max_tokens=None`` uses the
    model's native output ceiling; if that exceeds ``context_length`` (small local endpoints) it is
    clamped to ``context_length - 1``. The clamp ignores prompt size — callers must catch
    "max_tokens too large given prompt" and retry smaller (parse_available_output_tokens_from_error).
    ``is_oauth`` applies Claude Code compatibility transforms; ``preserve_dots`` keeps model-name
    dots (DashScope: qwen3.5-plus); a third-party ``base_url`` strips thinking signatures;
    ``fast_mode`` adds ``extra_body.speed="fast"`` plus the fast-mode beta on native Anthropic only."""
    system, anthropic_messages = convert_messages_to_anthropic(messages, base_url=base_url, model=model)
    anthropic_tools = convert_tools_to_anthropic(tools) if tools else []
    # Nous Portal routes on its own catalog ids (``anthropic/claude-opus-4.8``); normalizing would
    # make the model unresolvable there (prefix AND dots kept).
    if not _is_nous_portal_endpoint(base_url):
        model = normalize_model_name(model, preserve_dots=preserve_dots)
    # Non-positive/non-finite values fail locally instead of 400-ing upstream.
    effective_max_tokens = _resolve_anthropic_messages_max_tokens(max_tokens, model, context_length=context_length)
    if context_length and effective_max_tokens > context_length:
        effective_max_tokens = max(context_length - 1, 1)
    to_wire = _oauth_wire_namer(anthropic_tools) if is_oauth else None
    if to_wire:
        system = _apply_claude_code_identity(system, anthropic_tools, anthropic_messages, to_wire)
    kwargs: dict[str, Any] = {"model": model, "messages": anthropic_messages, "max_tokens": effective_max_tokens}
    if system:
        kwargs["system"] = system
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools
        if tool_choice == "none":
            kwargs.pop("tools", None)  # no Anthropic "none" — omit tools to prevent use
        elif tool_choice is None or isinstance(tool_choice, str):
            # A forced tool name goes through the OAuth normalizer too: every tools[] entry is
            # mcp__-prefixed/aliased there, so the literal would leak and name a nonexistent tool.
            kwargs["tool_choice"] = _TOOL_CHOICE_MAP.get(tool_choice) or {
                "type": "tool", "name": to_wire(tool_choice) if to_wire else tool_choice
            }
    # Map reasoning_config to Anthropic's thinking parameter. Claude 4.6+ models use adaptive thinking +
    # output_config.effort. Older models use manual thinking with budget_tokens. MiniMax Anthropic-compat
    # endpoints support thinking (manual mode only, not adaptive). Haiku through 4.5 gets no thinking
    # request; Haiku 5.5+ is adaptive. Kimi / Moonshot models also use adaptive thinking: their Anthropic-compatible
    # endpoints (api.moonshot.cn/anthropic, api.kimi.com/coding) accept ``thinking.type="adaptive"`` +
    # ``output_config.effort``, and the replay-validation 400s that originally motivated dropping the
    # parameter (#13848) no longer occur. (Kimi on chat_completions enables thinking via extra_body in the
    # ChatCompletionsTransport — see #13503.) On 4.7+ the `thinking.display` field defaults to "omitted",
    # which silently hides reasoning text that Hermes surfaces in its CLI. We request "summarized" so the
    # reasoning blocks stay populated — matching 4.6 behavior and preserving the activity-feed UX during
    # long tool runs.
    if reasoning_config and isinstance(reasoning_config, dict):
        kwargs.update(_thinking_kwargs(reasoning_config, model, effective_max_tokens))
    # Safety net so upstream 4.6 -> 4.7 migrations don't need coordinated edits everywhere callers
    # (auxiliary_client, ...) set sampling params.
    if _forbids_sampling_params(model):
        for key in ("temperature", "top_p", "top_k"):
            kwargs.pop(key, None)
    # Fast mode: native Anthropic only — third-party providers reject the unknown beta/param and
    # Anthropic scopes it to the Claude API (not Bedrock/Vertex/Foundry). Per-request extra_headers
    # OVERRIDE the client-level anthropic-beta header, so rebuild the full beta list.
    if fast_mode and not _is_third_party_anthropic_endpoint(base_url) and _supports_fast_mode(model):
        kwargs.setdefault("extra_body", {})["speed"] = "fast"
        betas = _common_betas_for_base_url(base_url, drop_context_1m_beta=drop_context_1m_beta)
        kwargs["extra_headers"] = _beta_header(betas + (_OAUTH_ONLY_BETAS if is_oauth else []) + [_FAST_MODE_BETA])
    return kwargs


_RESPONSES_ONLY_KWARGS = frozenset({"instructions", "input", "store", "parallel_tool_calls"})


def sanitize_anthropic_kwargs(api_kwargs: Any, *, log_prefix: str = "") -> Any:
    """Drop Responses-API-only keys before an Anthropic Messages SDK call. Boundary guard for
    api_mode-flip races (a concurrent auxiliary call mutating a shared agent between kwargs build
    and dispatch): a Responses-shaped payload reaching ``messages.stream()`` dies with a
    non-retryable TypeError that takes the whole turn and fallback chain with it. Mutates and
    returns ``api_kwargs``; logs a WARNING so the race stays visible."""
    leaked = _RESPONSES_ONLY_KWARGS.intersection(api_kwargs) if isinstance(api_kwargs, dict) else ()
    if leaked:
        for key in leaked:
            del api_kwargs[key]
        logger.warning(
            "%sStripped Responses-only kwarg(s) %s from an Anthropic Messages "
            "call (api_mode flip race — see #31673). The call will proceed; "
            "this breadcrumb means a kwargs build ran under a Responses "
            "api_mode while dispatch ran under anthropic_messages.",
            log_prefix,
            sorted(leaked),
        )
    return api_kwargs


def buffer_anthropic_tool_input(api_kwargs: dict[str, Any], base_url: str | None) -> None:
    """Retry knob for a malformed fine-grained tool-JSON stream (#107830): the beta streams tool
    args unvalidated, so a model that emits ``{"names": cronjob_manage}`` breaks the SDK parser
    and an identical retry breaks identically. ``eager_input_streaming: false`` per tool restores
    Anthropic's buffered, validated args for the rest of this turn (the flag lives on the turn's
    kwargs, so a later retry of the same turn keeps it; the changed ``tools`` block costs one
    prompt-cache miss, cheaper than a dead turn). Off the happy path on purpose:
    buffering a large payload is a zero-event gap the stale-stream detector kills. No-op on
    endpoints that never get the beta (MiniMax) rather than sending them an unknown field."""
    if _TOOL_STREAMING_BETA not in _common_betas_for_base_url(base_url):
        return
    for tool in api_kwargs.get("tools") or ():
        tool["eager_input_streaming"] = False

