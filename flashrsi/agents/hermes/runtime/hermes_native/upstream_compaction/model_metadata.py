from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)
from .message_metadata import PERSISTENCE_ONLY_MESSAGE_FIELDS, UNPRICED_REPLAY_FIELDS, without_persistence_fields


CONTEXT_PROBE_TIERS = [256_000, 128_000, 64_000, 32_000, 16_000, 8_000]


DEFAULT_FALLBACK_CONTEXT = CONTEXT_PROBE_TIERS[0]


MINIMUM_CONTEXT_LENGTH = 64_000


DEFAULT_CONTEXT_LENGTHS = {
    # Anthropic — bare ids only (prefixed ids resolve via OpenRouter/models.dev
    # and would collide: "anthropic/claude-sonnet-4" ⊂ "anthropic/claude-sonnet-4.6").
    "claude-fable-5": 1000000, "claude-fable": 1000000, "claude-opus-5": 1000000, "claude-sonnet-5": 1000000,
    "claude-opus-4-8": 1000000, "claude-opus-4.8": 1000000, "claude-opus-4-7": 1000000, "claude-opus-4.7": 1000000,
    "claude-opus-4-6": 1000000, "claude-sonnet-4-6": 1000000, "claude-opus-4.6": 1000000, "claude-sonnet-4.6": 1000000,
    "claude": 200000,  # catch-all for older Claude models
    # OpenAI — direct-API windows (Codex OAuth caps gpt-5.4+/5.5/5.6 at 272K, resolved by
    # its own branch). 5.4-nano/-mini are 400k, not 1.05M; gpt-5.3-codex-spark is
    # Codex-OAuth-only and listed so "gpt-5" (400k) doesn't win.
    "gpt-6-astra": 1050000,  # also matches -pro (verified live on OpenRouter)
    "gpt-6.1-sol": 1050000,  # -pro too (OpenAI model page + OpenRouter live 2026-09-29)
    "gpt-6-sol": 1050000, "gpt-6-luna": 1050000,  # -pro too (OpenRouter live 2026-09-22)
    "gpt-5.6-luna": 1050000, "gpt-5.6-terra": 1050000, "gpt-5.6-sol": 1050000, "gpt-5.5": 1050000,
    "gpt-5.4-nano": 400000, "gpt-5.4-mini": 400000, "gpt-5.4": 1050000,
    "gpt-5.3-codex-spark": 128000, "gpt-5.1-chat": 128000, "gpt-5": 400000,
    "gpt-4.1": 1047576, "gpt-4": 128000,
    # Google / Gemma ("gemma4" is Ollama-style naming, e.g. gemma4:31b-cloud)
    "gemini": 1048576,
    "gemma-4": 256000, "gemma4": 256000, "gemma-4-31b": 256000, "gemma-3": 131072, "gemma": 8192,
    # DeepSeek — V4 family is 1M; deepseek-chat/-reasoner alias v4-flash modes. ``deepseek-flash``
    # (version-less canonical id, 2026-09 Flash refresh) needs a discrete entry or the
    # longest-key-first scan falls through to the 128K ``deepseek`` catch-all below.
    # https://api-docs.deepseek.com/zh-cn/quick_start/pricing
    "deepseek-v4-pro": 1_000_000, "deepseek-v4.1-flash": 1_000_000, "deepseek-v4-flash": 1_000_000, "deepseek-chat": 1_000_000,
    "deepseek-reasoner": 1_000_000, "deepseek-flash": 1_000_000, "deepseek": 128000,
    # Meta; Muse Spark family (1.1/1.2/1.3, -contributor(-free), meta/ prefixed) is 1M per OpenRouter,
    # models.dev and api.commandcode.ai /models — keep the "muse-spark" prefix (bare "muse" would match
    # muse-image/muse-voice). Thinking Machines inkling (covers inkling-small and :free/:batch variants)
    "llama": 131072, "muse-spark-1.3": 1_048_576, "muse-spark": 1_048_576, "inkling": 1_048_576,
    # Qwen — https://help.aliyun.com/zh/model-studio/developer-reference/ (3.8-max/flash
    # 1M verified on OpenRouter & Nous portal 2026-08; qwen3-max = 256K Coding Plan snapshot)
    "qwen3.8-max": 1_000_000, "qwen3.8-flash": 1_000_000, "qwen3.6-plus": 1048576, "qwen3.7-plus": 1048576,
    "qwen3-coder-plus": 1000000, "qwen3-coder": 262144, "qwen3-max": 262144, "qwen": 131072,
    # MiniMax — M3 is 1M; M2.x is 204,800. https://platform.minimax.io/docs/api-reference/text-chat-openai
    "minimax-m3": 1000000, "minimax": 204800,
    # GLM — Nous + OpenRouter /v1/models (2026-09-09): 5.3 / 5.3-flash 1,310,720 (:batch/:US 1,048,576);
    # 5.3-flashx 1,048,576 (2026-09-20; its own key, else the shorter 5.3-flash entry wins by substring);
    # 5.2 1,048,576; 5 / 5.1 / 4.7 / 4.6 204,800; *-turbo / 4.7-flash 202,752 (the catch-all).
    # The OpenRouter :free variant is capped; the longer key wins.
    "glm-5.3": 1_310_720, "glm-5.3-flash": 1_310_720, "glm-5.3:batch": 1_048_576, "glm-5.3:us": 1_048_576,
    "glm-5.3-flash:batch": 1_048_576, "glm-5.3-flash:us": 1_048_576, "glm-5.3-flashx": 1_048_576,
    "glm-5.2": 1_048_576, "glm-5.2:free": 256_000,
    "glm-5.1": 204_800, "glm-5-turbo": 202752, "glm-5v-turbo": 202752, "glm-5": 204_800,
    "glm-4.7-flash": 202752, "glm-4.7": 204_800, "glm-4.6v": 131072, "glm-4.6": 204_800, "glm": 202752,
    # xAI — /v1/models returns no context_length, so these prevent probe-down on api.x.ai
    # custom providers (docs.x.ai). grok-composer(-2.5-fast, Grok Build CLI) is OAuth-only:
    # 200k usable (the /v1/responses ~262144 input+output budget is a separate limit).
    # grok-build-latest aliases grok-4.5; grok-4-fast / grok-4.20 also match their
    # -(non-)reasoning and -multi-agent variants; "grok" is the catch-all.
    "grok-composer": 200000, "grok-build-latest": 500000, "grok-build": 256000, "grok-code-fast": 256000,
    "grok-2-vision": 8192, "grok-4-fast": 2000000, "grok-4.20": 2000000,
    "grok-4.6": 500000, "grok-4.5": 500000, "grok-4.3": 1000000, "grok-4": 256000,
    "grok-3": 131072, "grok-2": 131072, "grok": 131072,
    # Kimi — K3 is 1 Mi (matches the endpoint-scoped override); older Kimi 256K.
    "kimi-k3": 1_048_576, "kimi": 262144,
    # Upstage Solar — /v1/models returns no context_length. Later generations and new lineups
    # default to 512K (Upstage /v1/solar/models max_model_len, 2026-09).
    "solar-open2": 262144, "solar-pro3": 131072, "solar-pro2": 65536, "solar-mini": 32768, "solar-": 524288,
    # Tencent Hunyuan (262144 = 256 × 1024, aligned with OpenRouter live metadata)
    "hy4-preview": 1_048_576, "hy3-preview": 262144, "hy3": 262144,
    # "Ox Alpha" stealth model (OpenCode Zen / OpenRouter slugs); "Union Alpha" stealth model
    # (OpenRouter ``stealth/union-alpha``, 262144 per /api/v1/models); NVIDIA Nemotron (128K
    # except 3.5 Lightning and 3.5 Super); Poolside Laguna 2.1 (:free / -free slugs); Arcee; OpenRouter.
    "x-preview-f": 1_048_576, "ox-alpha": 1_048_576, "union-alpha": 262144,
    "nemotron-3.5-lightning": 1_000_000, "nemotron-3.5-super-vl": 1_000_000, "nemotron": 131072,
    "laguna-s-2.1": 262144, "laguna-xs-2.1": 262144, "trinity": 262144, "elephant": 262144,
    # Hugging Face Inference Providers — model IDs use org/name format
    "Qwen/Qwen3.5-397B-A17B": 131072, "Qwen/Qwen3.5-35B-A3B": 131072, "deepseek-ai/DeepSeek-V3.2": 65536,
    "moonshotai/Kimi-K2.5": 262144, "moonshotai/Kimi-K2.6": 262144, "moonshotai/Kimi-K2-Thinking": 262144,
    "MiniMaxAI/MiniMax-M2.5": 204800, "XiaomiMiMo/MiMo-V2-Flash": 262144,
    "mimo-v2.6-pro-ultraspeed": 1048576, "mimo-v2.6-pro": 1048576, "mimo-v2.6-flash": 1048576,
    "mimo-v2-pro": 1048576, "mimo-v2.5-pro": 1048576, "mimo-v2.5": 1048576, "mimo-v2-omni": 262144, "mimo-v2-flash": 262144,
    "zai-org/GLM-5": 202752,
}


_BOUNDARY_MATCHED_KEY_PREFIXES = ("solar-",)


_HYPHENATED_GENERATION_RE = re.compile(
    rf"((?:{'|'.join(map(re.escape, _BOUNDARY_MATCHED_KEY_PREFIXES))})[a-z]+)-(\d{{1,2}})(?=[-:.@]|$)")


def _catalog_key_matches(key: str, model_lower: str) -> bool:
    """Substring match with version separators normalised on both sides, so a relay slug like
    ``z-ai-glm-5-3`` still hits the ``glm-5.3`` entry instead of the ``glm`` catch-all (#97398).
    Boundary-matched families: a key must be followed by ``-:.@`` or the end, and a key ending in
    ``-`` is the family default for bare names (``org/`` allowed) continuing with a lineup letter."""
    if key.startswith(_BOUNDARY_MATCHED_KEY_PREFIXES):
        model_lower = _HYPHENATED_GENERATION_RE.sub(r"\1\2", model_lower)
        if key.endswith("-"):
            return re.match(re.escape(key) + "[a-z]", model_lower.rsplit("/", 1)[-1]) is not None
        return re.search(re.escape(key) + r"(?:[-:.@]|$)", model_lower) is not None
    return key in model_lower or _normalize_model_version(key) in _normalize_model_version(model_lower)


def _longest_key_match(table: dict[str, int], model_lower: str) -> Optional[tuple[str, int]]:
    """First ``(key, value)`` whose key is a substring of ``model_lower``, longest key first so
    specific entries (``gpt-5.4-mini``) beat their family catch-all (``gpt-5``); ties keep table order."""
    for key, value in sorted(table.items(), key=lambda x: len(x[0]), reverse=True):
        if _catalog_key_matches(key, model_lower):
            return key, value
    return None


def _normalize_model_version(model: str) -> str:
    """Dots -> dashes so Nous ids (claude-opus-4-6) compare with OpenRouter's (claude-opus-4.6)."""
    return model.replace(".", "-")


CHARS_PER_TOKEN = 4


_CJK_DENSE_RE = re.compile("[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


def estimate_tokens_rough(text: str) -> int:
    """Rough token estimate: CJK/Hangul/Kana codepoints ~1 token each; everything else ceil(UTF-8 bytes/4).
    Ceiling keeps short texts from estimating 0. Runs on every preflight walk, so all-ASCII stays O(1).

    Byte-counting (not chars) is the corrective for non-CJK, non-ASCII text: Cyrillic/Greek/Arabic are 2
    bytes/char so count ~chars/2, matching real BPE cost (~2-3 chars/token) where chars/4 under-counted
    ~2x and let sessions ride the provider ceiling below the compaction threshold. Calibrated vs
    cl100k/o200k/Qwen2.5 (estimate/real): Russian 0.67->1.24, Arabic 0.53->0.96, Hindi 0.34->0.90,
    Greek 0.37->0.68; accented Latin barely moves (French 1.02->1.03). errors="replace": lone surrogates
    (routine in tool output; see message_sanitization) must not turn an estimate into a raise."""
    if not text:
        return 0
    text = str(text)
    if text.isascii():  # flag check on CPython; ASCII cannot contain token-dense CJK
        return (len(text) + 3) // CHARS_PER_TOKEN
    stripped = _CJK_DENSE_RE.sub("", text)
    dense = len(text) - len(stripped)
    return dense + ((len(stripped.encode("utf-8", "replace")) + 3) // CHARS_PER_TOKEN)


def estimate_messages_tokens_rough(messages: list[dict[str, Any]], *, charge_stale_thinking: bool = True) -> int:
    """Rough token estimate for a message list (pre-flight only). Images cost the per-image price
    learned from provider usage (``agent.image_token_cost``; flat default before calibration)
    rather than their base64 length. ``charge_stale_thinking=False`` mirrors the tail-budget
    walk (``context_compressor._estimate_msg_budget_tokens``): on non-echo routes stale reasoning
    rides the wire only for the NEWEST assistant turn, so excluding it keeps the compaction TRIGGER
    in the same size class as the walk — otherwise reasoning-heavy sessions fire preflight forever."""
    from .image_token_cost import current_image_token_cost

    image_cost = current_image_token_cost()
    if not charge_stale_thinking:
        messages = _strip_stale_thinking_for_estimate(messages)
    return sum(_estimate_message_tokens_cached(msg, image_cost) for msg in messages)


_STALE_THINKING_ESTIMATE_KEYS = ("reasoning", "reasoning_content")


def _strip_stale_thinking_for_estimate(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of ``messages`` with stale thinking keys removed (newest kept). Shallow stripped copies
    share the original value objects, so the per-message memo still hits for the stripped shape."""
    def _is_assistant(m: Any) -> bool:
        return isinstance(m, dict) and m.get("role") == "assistant"
    newest = next((i for i in range(len(messages) - 1, -1, -1) if _is_assistant(messages[i])), -1)
    return [
        {k: v for k, v in m.items() if k not in _STALE_THINKING_ESTIMATE_KEYS}
        if i != newest and _is_assistant(m) and any(m.get(k) for k in _STALE_THINKING_ESTIMATE_KEYS) else m
        for i, m in enumerate(messages)
    ]


_MSG_TOKENS_CACHE: dict[Any, tuple[list, int, int]] = {}  # pins, text tokens, image count


_MSG_TOKENS_CACHE_MAX = 4096


def _msg_fingerprint(value: Any, pins: list) -> Any:
    if value is None or value is True or value is False:
        return value
    t = type(value)
    if t is str:
        pins.append(value)
        return ("s", id(value))
    if t is int or t is float:
        return ("n", t.__name__, value)
    if t is dict:
        return ("d", tuple((_msg_fingerprint(k, pins), _msg_fingerprint(v, pins)) for k, v in value.items()))
    if t is list or t is tuple:
        return ("l" if t is list else "t", tuple(_msg_fingerprint(v, pins) for v in value))
    raise ValueError("unfingerprintable message value")


def _estimate_message_tokens_cached(msg: Any, image_cost: int) -> int:
    """Text tokens + images x ``image_cost``; the memo holds text and image COUNT so a recalibrated
    per-image price re-prices cached rows without invalidating them."""
    def _compute() -> tuple[int, int]:
        return _estimate_message_tokens_without_images(msg), _count_image_tokens(msg, 1)
    try:
        pins: list = []
        # Persistence-only fields (identity, timestamps, display metadata) never reach the estimate: keep them
        # out of the key so stamping them neither costs a walk nor misses the memo.
        key = _msg_fingerprint(
            without_persistence_fields(msg) if type(msg) is dict else msg, pins)
        hash(key)
    except Exception:
        text, images = _compute()
        return text + images * image_cost
    cached = _MSG_TOKENS_CACHE.get(key)
    if cached is not None:
        return cached[1] + cached[2] * image_cost
    text, images = _compute()
    tokens = text + images * image_cost
    _MSG_TOKENS_CACHE[key] = (pins, text, images)
    while len(_MSG_TOKENS_CACHE) > _MSG_TOKENS_CACHE_MAX:
        try:
            _MSG_TOKENS_CACHE.pop(next(iter(_MSG_TOKENS_CACHE)))
        except (StopIteration, KeyError, RuntimeError):
            break
    return tokens


def _count_parts(parts: Any, types: set) -> int:
    return sum(1 for part in parts if isinstance(part, dict) and part.get("type") in types) if isinstance(parts, list) else 0


_IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})


def _count_image_tokens(msg: dict[str, Any], cost_per_image: int) -> int:
    """Count image-like content parts in a message; return their token cost."""
    if not isinstance(msg, dict):
        return 0
    content = msg.get("content")
    count = _count_parts(content, _IMAGE_PART_TYPES)
    count += _count_parts(msg.get("_anthropic_content_blocks"), {"image"})
    # Multimodal tool results that haven't been converted yet.
    if isinstance(content, dict) and content.get("_multimodal"):
        count += _count_parts(content.get("content"), {"image", "image_url"})
    # Responses ``function_call_output`` items carry converted tool-result
    # parts under ``output`` (the converter moves chat ``content`` there).
    count += _count_parts(msg.get("output"), _IMAGE_PART_TYPES)
    return count * cost_per_image


def strip_opaque_replay_items(items: Any) -> Any:
    """``codex_reasoning_items`` with ``encrypted_content`` blanked for local token estimation.
    The ciphertext is priced by the provider's own count, never by its bytes (a compaction
    checkpoint alone can be 5M chars, #100611); only real usage prices it."""
    if not isinstance(items, list):
        return items
    return [
        {k: ("" if k == "encrypted_content" else v) for k, v in item.items()} if isinstance(item, dict) else item
        for item in items
    ]


def _wire_message_shadow(msg: dict[str, Any]) -> dict[str, Any]:
    """Shadow of a message holding only what the provider actually receives.
    * ``api_content`` SUBSTITUTES ``content`` (mirrors ``turn_context.substitute_api_content`` exactly):
      only a non-empty STRING sidecar on a user/assistant row displaces content; substituting any
      other shape would UNDERcount — the dangerous direction.
    * Base64 images become a placeholder; ``_count_image_tokens`` charges them flat.
    * ``reasoning`` never ships as-is (request builds pop it after optionally promoting it into
      ``reasoning_content``); counting both inflated estimates up to +53%.
    * Opaque provider blobs (``encrypted_content`` on codex reasoning / compaction items) are
      ciphertext the provider prices by its OWN token count, never by bytes; a native compaction
      checkpoint alone can be 5M chars (#100611). They contribute 0 here: only real usage ever
      prices them, and the usage anchor carries that price forward."""
    sidecar = msg.get("api_content")
    sidecar_wins = isinstance(sidecar, str) and bool(sidecar) and msg.get("role") in ("user", "assistant")
    _rc = msg.get("reasoning_content")
    drop_reasoning_dup = isinstance(_rc, str) and bool(_rc.strip())
    shadow: dict[str, Any] = {}
    for k, v in msg.items():
        if k in UNPRICED_REPLAY_FIELDS or k in PERSISTENCE_ONLY_MESSAGE_FIELDS or (k == "reasoning" and drop_reasoning_dup):
            continue
        if k == "api_content":
            if sidecar_wins:
                shadow["content"] = v
        elif k == "content" and sidecar_wins:
            continue
        elif k == "content" and isinstance(v, list):
            shadow[k] = [
                {"type": part.get("type"), "image": "[stripped]"}
                if isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES
                else part
                for part in v
            ]
        elif k == "content" and isinstance(v, dict) and v.get("_multimodal"):
            shadow[k] = v.get("text_summary", "")
        elif k == "output" and isinstance(v, list):
            # Responses ``function_call_output`` output parts: strip the image
            # payload like the ``content`` branch above so encoded bytes are
            # priced by the flat per-image model, never as text.
            shadow[k] = [
                {"type": part.get("type"), "image": "[stripped]"}
                if isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES
                else part
                for part in v
            ]
        elif k == "codex_reasoning_items":
            shadow[k] = strip_opaque_replay_items(v)
        elif k == "encrypted_content":  # a Responses reasoning/compaction item passed as a row
            shadow[k] = ""
        else:
            shadow[k] = v
    return shadow


def _estimate_message_tokens_without_images(msg: dict[str, Any]) -> int:
    """Token estimate for a message shadow with image payloads stripped."""
    return estimate_tokens_rough(str(_wire_message_shadow(msg) if isinstance(msg, dict) else msg))


def estimate_request_tokens_rough(
    messages: list[dict[str, Any]], *, system_prompt: str = "", tools: Optional[list[dict[str, Any]]] = None, charge_stale_thinking: bool = True,
) -> int:
    """Rough token estimate for a full request: system prompt + messages + tool schemas (50+ tools
    add 20-30K on their own). ``charge_stale_thinking`` is forwarded — pass False when the route
    provably strips stale thinking (``message_sanitization.stale_thinking_reaches_wire``)."""
    total = estimate_tokens_rough(system_prompt) if system_prompt else 0
    if messages:
        # Positional call: test seams and plugin engines monkeypatch estimate_messages_tokens_rough with (messages)-only signatures.
        total += estimate_messages_tokens_rough(messages) if charge_stale_thinking else estimate_messages_tokens_rough(messages, charge_stale_thinking=False)
    if tools:
        total += _estimate_tools_tokens_rough(tools)
    return total


_TOOLS_TOKENS_CACHE: dict[int, tuple[int, str, str, int]] = {}


_TOOLS_TOKENS_CACHE_MAX = 256


def _tool_name_for_cache(tool: Any) -> str:
    if not isinstance(tool, dict):
        return ""
    fn = tool.get("function")
    name = fn.get("name") if isinstance(fn, dict) else None
    name = name if isinstance(name, str) else tool.get("name")
    return name if isinstance(name, str) else ""


def _estimate_tools_tokens_rough(tools: list[dict[str, Any]]) -> int:
    if not tools:
        return 0
    key = id(tools)
    signature = (len(tools), _tool_name_for_cache(tools[0]), _tool_name_for_cache(tools[-1]))
    cached = _TOOLS_TOKENS_CACHE.get(key)
    if cached is not None and cached[:3] == signature:
        return cached[3]
    # Sum the major schema fields (descriptions + parameters dominate).
    total_chars = 0
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        src = fn if isinstance(fn, dict) else tool
        params = src.get("parameters") or {}
        total_chars += sum(len(v) for v in (src.get("name") or "", src.get("description") or "") if isinstance(v, str))
        try:  # JSON is closer to wire size than repr()
            total_chars += len(json.dumps(params, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            total_chars += len(str(params))
    tokens = (total_chars + 3) // 4
    if len(_TOOLS_TOKENS_CACHE) >= _TOOLS_TOKENS_CACHE_MAX:
        _TOOLS_TOKENS_CACHE.pop(next(iter(_TOOLS_TOKENS_CACHE)), None)
    _TOOLS_TOKENS_CACHE[key] = (*signature, tokens)
    return tokens


def get_model_context_length(model, base_url='', api_key='', config_context_length=None, custom_providers=None, **kwargs):
    """Explicit override then pinned metadata; no endpoint probes or ambient profiles."""
    if isinstance(config_context_length, int) and config_context_length > 0:
        return config_context_length
    from ..model_catalog import context_length
    settings = kwargs.get('model_catalog_settings') or {}
    provider = kwargs.get('provider', '')
    # Source step 0b: explicit model_overrides precede endpoint/catalog data.
    from ..upstream_catalog.boundaries import settings as catalog_settings
    from ..upstream_catalog.models_dev import _override_context_window
    token = catalog_settings.set(settings)
    try:
        override = _override_context_window(provider, model)
    finally:
        catalog_settings.reset(token)
    if override:
        return override
    for provider in custom_providers or []:
        if base_url and str(provider.get('base_url', '')).rstrip('/') != str(base_url).rstrip('/'):
            continue
        models = provider.get('models') or []
        if isinstance(models, dict):
            models = [{'id': key, **value} for key, value in models.items() if isinstance(value, dict)]
        for item in models:
            if isinstance(item, dict) and item.get('id', item.get('name')) == model:
                value = item.get('context_length', item.get('context_window'))
                if isinstance(value, int) and value > 0:
                    return value
    catalog = context_length(kwargs.get('provider', ''), model, settings)
    if catalog:
        # The source rejects models.dev's known MiniMax-M3 underreport.
        if 'minimax-m3' in str(model).lower():
            catalog = max(catalog, DEFAULT_CONTEXT_LENGTHS.get('minimax-m3', 0))
        return catalog
    match = _longest_key_match(DEFAULT_CONTEXT_LENGTHS, str(model).lower())
    return match[1] if match else DEFAULT_FALLBACK_CONTEXT


from .context_endpoints import is_local_endpoint
