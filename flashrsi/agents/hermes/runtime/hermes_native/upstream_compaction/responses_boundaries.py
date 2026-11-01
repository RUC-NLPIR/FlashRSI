"""Pure Hermes v0.22.5 source helpers; see RESPONSES_PROVENANCE.json."""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import re
import unicodedata
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, fields
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, TypeGuard
from urllib.parse import urlparse, urlsplit, urlunsplit
logger = logging.getLogger(__name__)
CODEX_AUX_BASE_URL = "https://chatgpt.com/backend-api/codex"

def is_official_codex_base_url(base_url: str) -> bool:
    """Identify OpenAI's Codex endpoint without matching custom proxies."""
    try:
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")
        return (
            parsed.scheme == "https"
            and parsed.hostname == "chatgpt.com"
            and parsed.port in (None, 443)
            and (path == "/backend-api/codex" or path.startswith("/backend-api/codex/"))
        )
    except (TypeError, ValueError):
        return False

def codex_cloudflare_headers(access_token: str, *, base_url: str = CODEX_AUX_BASE_URL) -> dict[str, str]:
    """Identity and account headers for chatgpt.com/backend-api/codex.

    OpenAI requires third-party harnesses to identify themselves: the official
    endpoint gets Hermes' originator and version, custom endpoints keep the
    codex_cli_rs compatibility identity. The account headers come from the
    OAuth JWT (see :func:`codex_account_headers`).
    """
    if is_official_codex_base_url(base_url):
        from .responses_boundaries import get_version_info
        headers = {
            "User-Agent": f"HermesAgent/{get_version_info().base_version}",
            "originator": "hermes-agent",
        }
    else:
        headers = {"User-Agent": "codex_cli_rs/0.0.0 (Hermes Agent)", "originator": "codex_cli_rs"}
    headers.update(codex_account_headers(access_token))
    return headers

def codex_account_headers(access_token: str) -> dict[str, str]:
    """Workspace headers the Codex backend derives from the OAuth JWT.

    ``ChatGPT-Account-ID`` (canonical casing, from codex-rs ``auth.rs``) comes from
    ``chatgpt_account_id``; ``x-openai-internal-codex-residency`` from
    ``chatgpt_data_residency`` (fallback ``chatgpt_compute_residency``) — without
    it residency-enforced workspaces answer 401 "Workspace is not authorized in
    this region". A malformed token drops the headers rather than raising, so it
    surfaces as a 401 instead of a crash at client construction.
    """
    headers: dict[str, str] = {}
    if not isinstance(access_token, str) or not access_token.strip():
        return headers
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return headers
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        auth = json.loads(base64.urlsafe_b64decode(payload_b64)).get("https://api.openai.com/auth", {})
        acct_id = auth.get("chatgpt_account_id")
        if isinstance(acct_id, str) and acct_id:
            headers["ChatGPT-Account-ID"] = acct_id
        residency = auth.get("chatgpt_data_residency") or auth.get("chatgpt_compute_residency")
        if isinstance(residency, str) and residency.strip():
            headers["x-openai-internal-codex-residency"] = residency.strip()
    except Exception:
        pass
    return headers

def normalize_route_base_url(base_url: Any) -> str:
    """Canonicalize only proven-equivalent endpoint URL components."""
    raw = str(base_url or "")
    if not raw:
        return ""
    if any(ord(char) <= 0x20 for char in raw):
        return raw
    had_query_delimiter = "?" in raw.split("#", 1)[0]
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        if not parsed.scheme or not hostname:
            return raw
        scheme = parsed.scheme.lower()
        if "%" in hostname:
            address, zone = hostname.split("%", 1)
            host = f"{address.lower()}%{zone}"
        else:
            host = hostname.lower()
        port = parsed.port
    except (TypeError, ValueError):
        return raw
    route_host = parsed.netloc.rsplit("@", 1)[-1]
    if route_host.startswith("[") or ":" in host:
        host = f"[{host}]"
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    if "@" in parsed.netloc:
        host = f"{parsed.netloc.rsplit('@', 1)[0]}@{host}"
    path = parsed.path
    if path.endswith("/") and not had_query_delimiter:
        path = path[:-1]
    normalized = urlunsplit((scheme, host, path, parsed.query, ""))
    if had_query_delimiter and not parsed.query:
        normalized += "?"
    return normalized

def _parse_base_url(base_url: str):
    """``urlparse`` that tolerates a bare ``host[:port][/path]`` (no scheme)."""
    raw = (base_url or "").strip()
    return urlparse(raw if "://" in raw else f"//{raw}") if raw else None

def _hostname_of(parsed) -> str:
    return (parsed.hostname or "").lower().rstrip(".") if parsed else ""

def base_url_hostname(base_url: str) -> str:
    """Lowercased hostname for a base URL, or ``""`` if absent.

    Compare exact hostnames against provider hosts instead of substring-matching the raw URL:
    ``https://api.openai.com.example/v1`` or ``https://proxy.test/api.openai.com/v1`` would
    otherwise pass as native endpoints and mis-route api_mode and auth.
    """
    return _hostname_of(_parse_base_url(base_url))

def base_url_host_matches(base_url: str, domain: str) -> bool:
    """True when the base URL's hostname is ``domain`` or a subdomain.

    Safer than ``domain in base_url`` (``evil.com/moonshot.ai`` / ``moonshot.ai.evil`` must not
    match). Accepts bare hosts, full URLs, and URLs with paths.
    """
    hostname = base_url_hostname(base_url)
    domain = (domain or "").strip().lower().rstrip(".")
    return bool(hostname and domain) and (hostname == domain or hostname.endswith("." + domain))

EFFORT_LADDER: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

CODEX_GPT56_EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh", "max")

CODEX_LEGACY_EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh")

CODEX_ASTRA_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

ASTRA_MODEL_IDS: frozenset[str] = frozenset({"gpt-6-astra", "gpt-6-astra-900k"})

GPT6_TIER_PREFIXES: tuple[str, ...] = ("gpt-6-sol", "gpt-6-luna")

NO_DISABLE_TIER_PREFIXES: tuple[str, ...] = ("gpt-6.1-sol",)

DAYBREAK_MODEL_IDS: frozenset[str] = frozenset(
    {"gpt-daybreak-blue-latest", "gpt-daybreak-blue-latest-900k"}
)

XAI_GROK46_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh")

XAI_LEGACY_EFFORTS: tuple[str, ...] = ("low", "medium", "high")

def is_astra_model(model: Optional[str]) -> bool:
    """``gpt-6-astra`` or its Hermes-side ``-900k`` picker alias, with or without a ``vendor/`` prefix.
    The single home for the slug set: picker gating, effort vocabulary and the request sanitizer all
    key off it, so a new Astra alias is one edit."""
    return (model or "").strip().lower().rsplit("/", 1)[-1] in ASTRA_MODEL_IDS

def codex_supported_efforts(model: Optional[str]) -> tuple[str, ...]:
    """Supported effort set for an OpenAI/Codex Responses model."""
    bare = (model or "").strip().lower().rsplit("/", 1)[-1]
    if is_astra_model(model) or bare.startswith(NO_DISABLE_TIER_PREFIXES):
        return CODEX_ASTRA_EFFORTS
    return (
        CODEX_GPT56_EFFORTS
        if "gpt-5.6" in bare or bare.startswith(GPT6_TIER_PREFIXES) or bare in DAYBREAK_MODEL_IDS
        else CODEX_LEGACY_EFFORTS
    )

def clamp_effort(
    effort: Optional[str], supported: Optional[Sequence[str]], overrides: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Clamp a requested reasoning effort onto a wire's supported levels.

    ``overrides`` (a declared vendor mapping, e.g. Kimi K3 ``medium → high``) is consulted
    first. Otherwise the request passes through unchanged when it is supported, when the
    supported set is unknown/empty, or when it isn't a recognized ladder level (custom
    providers may use bespoke names). Else the **nearest weaker** supported level is returned
    so a clamp never escalates cost; when nothing weaker exists, the weakest supported level
    (the provider's floor is the closest honest match). Monotonic: a stronger request never
    resolves weaker than a weaker request would.
    """
    requested = str(effort or "").strip().lower()
    if not requested or not supported:
        return effort
    supported_norm = [lvl for lvl in (str(s).strip().lower() for s in supported) if lvl in EFFORT_LADDER]
    if not supported_norm or requested in supported_norm:
        return effort
    if overrides and overrides.get(requested) in supported_norm:
        return overrides[requested]
    if requested not in EFFORT_LADDER:
        return effort
    # "none" disables reasoning — never a degradation target for an enabled ask
    # (clamping "minimal" to "none" would silently switch thinking off).
    candidates = [level for level in supported_norm if level != "none"]
    if not candidates:
        return effort
    requested_idx = EFFORT_LADDER.index(requested)
    below = [level for level in candidates if EFFORT_LADDER.index(level) < requested_idx]
    return max(below, key=EFFORT_LADDER.index) if below else min(candidates, key=EFFORT_LADDER.index)

_GROK_EFFORT_CAPABLE_PREFIXES = ("grok-3-mini", "grok-4.20-multi-agent", "grok-4.3", "grok-4.5", "grok-4.6")

def grok_supports_reasoning_effort(model: str) -> bool:
    """Allowlist check (aggregator prefixes like ``x-ai/`` stripped); unknown Grok models get no effort dial."""
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return bool(name) and any(name.startswith(prefix) for prefix in _GROK_EFFORT_CAPABLE_PREFIXES)

_OPENAI_NON_REASONING_RE = re.compile(r"^(?:ft:)?(?:gpt-3\.5|gpt-4(?![0-9])|chatgpt-)")

def openai_model_rejects_reasoning(model: str) -> bool:
    """True for an OpenAI model id (aggregator ``openai/`` prefix stripped) that rejects the
    Responses ``reasoning`` parameter outright, so callers send no ``reasoning`` key at all."""
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return bool(_OPENAI_NON_REASONING_RE.match(name))

def is_grok_46_family(model: str) -> bool:
    """Whether *model* is a Grok 4.6 family identifier."""
    name = (model or "").strip().lower().replace("_", "-").rsplit("/", 1)[-1]
    return name == "grok-4.6" or name.startswith("grok-4.6-")

CODEX_CONTEXT_VARIANT_SUFFIX = "-900k"  # picker-only opt-in suffix; never sent on the wire

_CODEX_900K_SNAPSHOT_BASES = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-sol", "gpt-6-luna")

_CODEX_900K_ELIGIBLE_BASES = frozenset({*_CODEX_900K_SNAPSHOT_BASES, "gpt-5.4", "gpt-daybreak-blue-latest", "gpt-6-astra", "gpt-6.1-sol"})

_CODEX_900K_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _bare_codex_slug(model: Optional[str]) -> str:
    """Lowercased slug without ``vendor/`` (display/auxiliary callers pass ``openai/gpt-5.6-sol-900k``).

    Display/auxiliary callers pass ids like ``openai/gpt-5.6-sol-900k``; the main-agent path normalizes the
    namespace away earlier, but this resolver must accept both shapes (#92797 review).
    """
    return (model or "").strip().lower().rsplit("/", 1)[-1]

def is_codex_900k_base(model: Optional[str]) -> bool:
    """Single source of truth for ``-900k`` eligibility (picker, resolution, /model validation, wire stripping)."""
    slug = _bare_codex_slug(model)
    if not slug or slug.endswith(CODEX_CONTEXT_VARIANT_SUFFIX):
        return False
    # Dated snapshots of the routable tier bases (gpt-5.6-sol-2026-07-09, gpt-6-sol-2026-09-22) also qualify.
    return slug in _CODEX_900K_ELIGIBLE_BASES or any(
        slug.startswith(base + "-") and _CODEX_900K_SNAPSHOT_RE.match(slug[len(base) + 1:]) for base in _CODEX_900K_SNAPSHOT_BASES
    )

def _codex_variant_base(model: Optional[str]) -> Optional[str]:
    """Lowercased eligible base of a VALID ``-900k`` variant, else None (``gpt-5.5-900k`` is an invalid alias)."""
    slug = _bare_codex_slug(model)
    base = slug[: -len(CODEX_CONTEXT_VARIANT_SUFFIX)] if slug.endswith(CODEX_CONTEXT_VARIANT_SUFFIX) else None
    return base if base is not None and is_codex_900k_base(base) else None

def strip_codex_context_variant_suffix(model: Optional[str]) -> str:
    """Wire-safe slug with a VALID ``-900k`` suffix removed (vendor prefix kept); an ineligible alias is
    returned unchanged so it fails honestly at the API instead of running as another model."""
    raw = (model or "").strip()
    return raw[: -len(CODEX_CONTEXT_VARIANT_SUFFIX)] if _codex_variant_base(raw) is not None else raw

_VALID_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")

def coerce_tool_name(name: Any, fallback: str = "invalid_tool_call") -> str:
    """Coerce a *replayed* tool/function name to ``^[A-Za-z0-9_-]{1,64}$``. Valid names are returned
    as-is (identity — prompt-cache safe); invalid runs collapse to ``_`` and the result is cut at 64;
    empty/all-invalid → ``fallback``. Deterministic, so the same stored name always renders the same
    bytes. Never apply to live tool definitions (schema names must match the dispatch registry)."""
    if not isinstance(name, str):
        return fallback
    if _VALID_TOOL_NAME_RE.fullmatch(name):
        return name
    coerced = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]", "_", name.strip())).strip("_")
    return coerced[:64] or fallback

def deterministic_call_id(fn_name: str, arguments: str, index: int = 0) -> str:
    """Deterministic call_id fallback when the API omits one (random ids would break caching)."""
    seed = f"{fn_name}:{arguments}:{index}"
    return f"call_{hashlib.sha256(seed.encode('utf-8', errors='replace')).hexdigest()[:12]}"

DEFAULT_AGENT_IDENTITY = (
    # A behavior spec (sizing rule, named prohibitions, earned-depth escape hatch), not a trait list — trait
    # lists change nothing. Maintainer rule: models UNDER-explore by default; never re-add an exploration-thrift line.
    "You are Hermes Agent, built by Nous Research. Be direct: match the length of your reply to the weight of the ask "
    "— a one-line question gets a one-line answer, and finished work gets a short report of what changed, what's "
    "verified, and what's left, never a replay of the process. No filler (\"Great question,\" \"I'd be happy to\"), no "
    "restating the request back, no re-summarizing what you already said, no narrating tool calls the user can see. "
    "Plain claims over adjectives; when unsure, say so plainly. Agree because it's right, not because the user said "
    "it. Depth is earned — give it when the user asks for detail, teaches, or the stakes demand it, not by default."
)

_ANTHROPIC_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

def unsupported_inline_image_media_type(url: str) -> Optional[str]:
    """``image/<subtype>`` of a ``data:image/...`` URL the inline-image wire paths reject
    (``image/jpg`` counts as JPEG); None for accepted rasters and for non-data URLs (the
    provider owns remote-URL validation)."""
    header = url.partition(",")[0].lower()
    if not header.startswith("data:image/"):
        return None
    subtype = header[len("data:image/"):].split(";", 1)[0].strip() or "unknown"
    media_type = "image/jpeg" if subtype == "jpg" else f"image/{subtype}"
    return None if media_type in _ANTHROPIC_SUPPORTED_MEDIA_TYPES else media_type

logger = logging.getLogger(__name__)

_STRIP_ON_RECOVERY_KEYS = frozenset({"pattern", "format"})

_SCHEMA_MARKERS = frozenset({"type", "anyOf", "oneOf", "allOf"})  # a node with one IS a schema

def _dict_nodes(node: Any):
    """Pre-order walk over every dict node (yielded before its values, so it may be mutated)."""
    if isinstance(node, dict):
        yield node
    children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
    for child in children:
        yield from _dict_nodes(child)

def _reactive_strip(
    tools: list[dict], strip_node: Callable[[dict], int], log_msg: str) -> tuple[list[dict], int]:
    """Apply *strip_node* (-> keywords removed) to every dict node of each tool's parameters, in
    place; OpenAI (``{"function": {"parameters"}}``) and Responses (``{"parameters"}``) formats."""
    stripped = 0
    for tool in tools or ():
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        params = fn.get("parameters") if isinstance(fn, dict) else None
        params = params if isinstance(params, dict) else tool.get("parameters")
        if isinstance(params, dict):
            stripped += sum(strip_node(node) for node in _dict_nodes(params))
    if stripped:
        logger.info(log_msg, stripped)
    return tools, stripped

def strip_pattern_and_format(tools: list[dict]) -> tuple[list[dict], int]:
    """Strip ``pattern``/``format`` in place — reactive, only after llama.cpp's grammar converter
    rejected a schema (its regex engine is a small ECMAScript subset); cloud providers use these as
    prompting hints. Only beside ``type``/combinators, so a property *named* ``pattern`` stays."""
    def _strip(node: dict) -> int:
        is_schema = bool(node.keys() & _SCHEMA_MARKERS)
        hits = [k for k in node if k in _STRIP_ON_RECOVERY_KEYS] if is_schema else []
        for k in hits:
            del node[k]
        return len(hits)
    return _reactive_strip(
        tools, _strip,
        "schema_sanitizer: stripped %d pattern/format keyword(s) from "
        "tool schemas (llama.cpp grammar-parse recovery)")

def strip_slash_enum(tools: list[dict]) -> tuple[list[dict], int]:
    """Strip ``enum`` keywords whose string values contain ``/``, in place: xAI's grammar compiler
    rejects them (HTTP 400 before any token) — typically MCP enums of HuggingFace model IDs."""
    def _strip(node: dict) -> int:
        enum_val = node.get("enum")
        if isinstance(enum_val, list) and any(isinstance(v, str) and "/" in v for v in enum_val):
            del node["enum"]
            return 1
        return 0
    return _reactive_strip(
        tools, _strip,
        "schema_sanitizer: stripped %d enum keyword(s) containing '/' "
        "from tool schemas (xAI Responses grammar-compile recovery)")

def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider aliases to canonical ids. ``"auto"`` passes through — use
    ``hermes_cli.auth.resolve_provider()`` to resolve it from credentials."""
    normalized = (provider or "openrouter").strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized)

_OPENCODE_FAMILIES = ("opencode-go", "opencode-zen")

def opencode_provider_family(provider_id: Optional[str]) -> Optional[str]:
    """Resolve a provider id (canonical or prefixed) to its OpenCode family, or None.

    Returns ``"opencode-zen"`` or ``"opencode-go"`` for the built-in providers AND for custom providers
    whose name extends a family slug (e.g. ``opencode-go-bridge`` pointing at
    ``https://opencode.ai/zen/go/v1``, issue #85589). Matching is case-insensitive. Custom family providers
    need the same per-model api_mode routing and /v1 base-url normalization as the built-ins — this
    predicate is the single owner of that family-membership question; do not re-implement it inline.
    """
    raw = str(provider_id or "").strip().lower()
    if not raw:
        return None
    canonical = normalize_provider(provider_id)
    if canonical in _OPENCODE_FAMILIES:
        return canonical
    return next((f for f in _OPENCODE_FAMILIES if raw.startswith(f)), None)

# The harness has no ambient Hermes profiles, gateway scheduler or optional rasterizer.
# Explicit route configuration is scoped to one request and never read from HOME.
request_settings = ContextVar("hermes_responses_request_settings", default={})
def current_execution():
    return None
def rasterize_svg_data_url(url):
    return None
def get_active_search_provider():
    backend = request_settings.get().get("web_search_backend")
    return SimpleNamespace(name=backend) if backend else None
def _get_search_backend():
    return request_settings.get().get("web_search_backend", "")
def _profile_declared_efforts(provider, model, base_url=None):
    explicit = request_settings.get().get("supported_reasoning_efforts")
    return tuple(explicit) if isinstance(explicit, (tuple, list)) else None
def get_version_info():
    return SimpleNamespace(base_version="0.22.5")
def _runtime_main_value(key):
    return request_settings.get().get(key)
