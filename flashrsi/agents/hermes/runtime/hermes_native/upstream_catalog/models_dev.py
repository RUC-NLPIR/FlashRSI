from __future__ import annotations
import contextlib,copy,logging,re
from dataclasses import dataclass
from typing import Any,Optional
from .boundaries import fetch_models_dev
from .variants import openrouter_variant_base
logger=logging.getLogger(__name__)
logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Full metadata for a single model from models.dev."""
    id: str
    name: str
    family: str
    provider_id: str        # models.dev provider ID (e.g. "anthropic")
    # Capabilities
    reasoning: bool = False
    tool_call: bool = False
    attachment: bool = False       # supports image/file attachments (vision)
    temperature: bool = False
    structured_output: bool = False
    open_weights: bool = False
    # Modalities
    input_modalities: tuple[str, ...] = ()    # ("text", "image", "pdf", ...)
    output_modalities: tuple[str, ...] = ()
    # Limits
    context_window: int = 0
    max_output: int = 0
    max_input: Optional[int] = None
    # Cost (per million tokens, USD)
    cost_input: float = 0.0
    cost_output: float = 0.0
    cost_cache_read: Optional[float] = None
    cost_cache_write: Optional[float] = None
    # Metadata
    knowledge_cutoff: str = ""
    release_date: str = ""
    status: str = ""          # "alpha", "beta", "deprecated", or ""
    interleaved: Any = False  # True or {"field": "reasoning_content"}
    def has_cost_data(self) -> bool:
        return self.cost_input > 0 or self.cost_output > 0
    def supports_vision(self) -> bool:
        return self.attachment or "image" in self.input_modalities
    def supports_pdf(self) -> bool:
        return "pdf" in self.input_modalities
    def supports_audio_input(self) -> bool:
        return "audio" in self.input_modalities
    def format_capabilities(self) -> str:
        """Human-readable capabilities, e.g. 'reasoning, tools, vision, PDF'."""
        flags = (
            (self.reasoning, "reasoning"), (self.tool_call, "tools"), (self.supports_vision(), "vision"), (self.supports_pdf(), "PDF"),
            (self.supports_audio_input(), "audio"), (self.structured_output, "structured output"), (self.open_weights, "open weights"),
        )
        return ", ".join(label for on, label in flags if on) or "basic"


@dataclass
class ModelCapabilities:
    """Structured capability metadata for a model from models.dev."""
    supports_tools: bool = True
    supports_vision: Optional[bool] = None
    supports_reasoning: Optional[bool] = None
    context_window: int = 200000
    max_output_tokens: Optional[int] = None
    model_family: str = ""


PROVIDER_TO_MODELS_DEV: dict[str, str] = {
    "openrouter": "openrouter", "novita": "novita-ai", "anthropic": "anthropic",
    "openai": "openai", "openai-api": "openai", "openai-codex": "openai", "zai": "zai",
    "kimi": "kimi-for-coding", "kimi-coding": "kimi-for-coding",
    "moonshot": "kimi-for-coding", "stepfun": "stepfun",
    "kimi-coding-cn": "kimi-for-coding", "minimax": "minimax",
    "minimax-oauth": "minimax", "minimax-cn": "minimax-cn", "deepseek": "deepseek",
    "alibaba": "alibaba", "qwen-oauth": "alibaba", "copilot": "github-copilot",
    "ai-gateway": "vercel", "opencode-zen": "opencode",
    "opencode-go": "opencode-go",
    "kilocode": "kilo", "fireworks": "fireworks-ai",
    "huggingface": "huggingface", "gemini": "google", "google": "google",
    "xai": "xai",
    "xai-oauth": "xai",  # OAuth is a transport path for the same xAI catalog
    "xiaomi": "xiaomi", "nvidia": "nvidia",
    # Meta Model API (Muse Spark, api.meta.ai): models.dev keys it "meta", the
    # Hermes provider is "meta-ai"; both aliases are needed or muse-spark-*
    # falls back to the generic 256K default instead of its true 1M window.
    "meta-ai": "meta", "meta": "meta", "groq": "groq", "mistral": "mistral",
    "togetherai": "togetherai", "perplexity": "perplexity", "cohere": "cohere",
    "ollama-cloud": "ollama-cloud",
}


_MODELS_DEV_TO_PROVIDER: Optional[dict[str, list[str]]] = None


def _models_dev_to_hermes_ids(mdev_id: str) -> list[str]:
    """Return the Hermes provider ids that map to *mdev_id* (may be [])."""
    global _MODELS_DEV_TO_PROVIDER
    if _MODELS_DEV_TO_PROVIDER is None:
        _MODELS_DEV_TO_PROVIDER = {}
        for hermes_id, mapped in PROVIDER_TO_MODELS_DEV.items():
            _MODELS_DEV_TO_PROVIDER.setdefault(mapped, []).append(hermes_id)
    return _MODELS_DEV_TO_PROVIDER.get(mdev_id, [])


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _configured_catalog_provider(
    provider: str, *, config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """``catalog_provider`` declared on a custom provider's ``providers.<name>`` row (or legacy
    ``custom_providers[]`` entry): the catalogued vendor whose models it resells. None when unset."""
    name = (provider or "").strip()
    if name.lower().startswith("custom:"):
        name = name[len("custom:"):]
    if not name or name in PROVIDER_TO_MODELS_DEV:
        return None
    provider_config = (
        _cfg_get("providers", name, default=None, config=config)
        if config is not None
        else _cfg_get("providers", name, default=None)
    )
    alias = _dict_or_empty(provider_config).get("catalog_provider")
    if not alias:
        legacy = (
            _cfg_get("custom_providers", default=None, config=config)
            if config is not None
            else _cfg_get("custom_providers", default=None)
        )
        alias = next((e.get("catalog_provider") for e in (legacy if isinstance(legacy, list) else [])
                      if isinstance(e, dict) and str(e.get("name") or "").strip() == name), None)
    alias = str(alias or "").strip()
    return alias or None


def _models_dev_id(
    provider: str, *, config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """models.dev provider id for a Hermes provider id, or None. A custom provider reaches the
    catalog only through its configured ``catalog_provider`` alias (#112649)."""
    key = (provider or "").strip()
    mdev_id = PROVIDER_TO_MODELS_DEV.get(key)
    if mdev_id is None:
        alias = _configured_catalog_provider(key, config=config)
        mdev_id = PROVIDER_TO_MODELS_DEV.get(alias, alias) if alias else None
        if mdev_id is not None and mdev_id not in PROVIDER_TO_MODELS_DEV.values() \
                and mdev_id not in fetch_models_dev(allow_network=False):
            # A mistyped alias must not leak into ModelInfo.provider_id; the row stays on its own slug.
            if (key, alias) not in _UNKNOWN_CATALOG_PROVIDER_WARNED:
                _UNKNOWN_CATALOG_PROVIDER_WARNED.add((key, alias))
                logger.warning("providers.%s: catalog_provider %r is neither a Hermes provider id nor a "
                               "models.dev id; ignoring", key, alias)
            mdev_id = None
    return mdev_id


_UNKNOWN_CATALOG_PROVIDER_WARNED: set = set()  # (provider, alias) warned once per process


def _cfg_get(*keys: str, default: Any, config: Optional[dict[str, Any]] = None) -> Any:
    """``cfg_get`` over the read-only config; *default* on any failure."""
    try:
        from .boundaries import cfg_get,load_config_readonly
        return cfg_get(config if config is not None else load_config_readonly(), *keys, default=default)
    except Exception:
        return default


def _registry_provider(mdev_id: str, allow_network: bool) -> Optional[dict[str, Any]]:
    """The raw models.dev provider entry, or None."""
    # Keep the zero-argument call on the allow_network path: dozens of test sites monkeypatch fetch_models_dev with zero-arg lambdas.
    registry = fetch_models_dev() if allow_network else fetch_models_dev(allow_network=False)
    provider_data = registry.get(mdev_id)
    return provider_data if isinstance(provider_data, dict) else None


def _registry_models(mdev_id: str, *, allow_network: bool) -> Optional[dict[str, Any]]:
    """The ``models`` dict of a models.dev provider entry, or None."""
    provider_data = _registry_provider(mdev_id, allow_network)
    models = provider_data.get("models", {}) if provider_data is not None else None
    return models if isinstance(models, dict) else None


def _get_provider_models(
    provider: str, *, allow_network: bool = False, config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Resolve a Hermes provider ID to its models dict, or None if unknown.
    ``allow_network`` defaults to False — hot-path callers must never block."""
    mdev_id = _models_dev_id(provider, config=config)
    return _registry_models(mdev_id, allow_network=allow_network) if mdev_id else None


_OPENROUTER_CATALOG_PROVIDERS = frozenset({"openrouter"})


def _openrouter_catalog_lookup_base(provider: str, model: str) -> Optional[str]:
    """Return the base id to retry a catalog lookup with, or ``None``.

    OpenRouter's ``:nitro`` / ``:floor`` / ``:exacto`` / ``:online`` are
    request-time routing modifiers: they change which endpoint serves the
    request, never which model runs. ``/models`` and models.dev list only the
    base id, so a routed id must resolve to the base model's metadata.

    Scoped to OpenRouter so a genuine ``model:tag`` on another provider (an
    Ollama tag, a ``:cloud`` catalog key) is never rewritten.

    Deliberately excludes ``:free``, ``:batch``, ``:extended``, and
    ``:thinking``: those are REAL catalog SKUs with their own entries and
    their own — sometimes different — context windows. Stripping them would
    report a window LARGER than the model actually has. Their real entries
    are found by the exact/case-insensitive passes above, and a genuinely
    absent SKU must miss so ``model_overrides`` ``_default`` fill-gap
    semantics still apply.
    """
    if provider not in _OPENROUTER_CATALOG_PROVIDERS:
        return None
    return openrouter_variant_base(model)


def _iter_model_entries(
    models: dict[str, Any], model: str, *, suffix_fallback: bool = True, provider: str = ""
):
    """Yield ``(model_id, entry)`` candidates: exact, case-insensitive, then (optionally)
    ``:cloud``/``-cloud`` suffixed forms. Suffix fallback: some providers (ollama-cloud) store
    ``kimi-k2.6:cloud`` while the live API returns the bare name; without it context lookup falls to
    stale OpenRouter metadata and trips the 64k minimum-context guard. Every consumer shares this
    order so a suffix-keyed catalog model counts as KNOWN for ``model_overrides`` fill-gap ``_default``.

    ``provider`` enables the OpenRouter routing-variant fallback as a LAST
    resort — after exact, case-insensitive, and ``:cloud`` matching — so a
    real catalog SKU always wins over its base.
    """
    for name in ([model] + [model + suffix for suffix in (":cloud", "-cloud")] if suffix_fallback else [model]):
        entry = models.get(name)
        if isinstance(entry, dict):
            yield name, entry
        name_lower = name.lower()
        for mid, mdata in models.items():
            if mid.lower() == name_lower and isinstance(mdata, dict):
                yield mid, mdata
    routed_base = _openrouter_catalog_lookup_base(provider, model)
    if routed_base is not None:
        # Recursion is bounded: the base never carries a recognized variant suffix,
        # and provider is cleared so the retry cannot loop.
        yield from _iter_model_entries(
            models, routed_base, suffix_fallback=suffix_fallback, provider=""
        )


def _find_model_entry(
    models: dict[str, Any], model: str, provider: str = ""
) -> Optional[dict[str, Any]]:
    """First catalog entry for *model* (exact, case-insensitive, suffix), or None."""
    return next((entry for _mid, entry in _iter_model_entries(models, model, provider=provider)), None)


def _extract_limit(entry: Any, key: str) -> Optional[int]:
    """Positive int ``entry.limit[key]`` or None (audio/image models have context=0)."""
    value = _dict_or_empty(_dict_or_empty(entry).get("limit")).get(key)
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _extract_context(entry: dict[str, Any]) -> Optional[int]:
    """Context length from a models.dev model entry, or None if invalid/zero."""
    return _extract_limit(entry, "context")


def lookup_models_dev_context(provider: str, model: str, *, allow_network: bool = False) -> Optional[int]:
    """Context window in tokens for provider+model, or None if not found. An EXPLICIT ``model_overrides``
    entry wins over the catalog; ``_default`` fills the gap only when the catalog has no answer (the
    self-unblock path for wrong/missing context in models.dev). Catalog entries with context=0 are
    skipped in favour of later candidates. ``allow_network`` defaults to False — runs every turn.

    See #84482.
    """
    override_ctx = _override_context_window(provider, model)
    if override_ctx is not None:
        return override_ctx
    declared_ctx = _override_int(_provider_model_capabilities(provider, model), "context_window")
    if declared_ctx is not None:
        return declared_ctx
    models = _get_provider_models(provider, allow_network=allow_network)
    catalog_ctx = next((ctx for _mid, entry in _iter_model_entries(models, model, provider=provider) if (ctx := _extract_context(entry))), None) if models is not None else None
    return catalog_ctx if catalog_ctx is not None else _default_override_context(provider)


_OVERRIDE_WARNED_KEYS: set = set()


_UNKNOWN_MODEL_BASE: dict[str, Any] = {"limit": {"context": 200000}, "tool_call": True}


_DEEPSEEK_FLASH_VISION: dict[str, Any] = {
    "limit": {"context": 1_000_000, "output": 384_000},
    "modalities": {"input": ["text", "image"], "output": ["text"]},
    "tool_call": True,
    "reasoning": True,
    "family": "deepseek-flash",
}


_BUILTIN_MODEL_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    ("openai", "gpt-6-astra"): {
        "limit": {"context": 1_050_000, "output": 128_000},
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "tool_call": True,
        "reasoning": True,
        "family": "gpt-6",
    },
    # Native DeepSeek V4.1-Flash is multimodal (https://api-docs.deepseek.com/guides/vision).
    # models.dev lagged the 2026-09-10 rename; without this, a cold/empty cache treats
    # ``deepseek-flash`` as unknown → image_input_mode falls through to lossy text.
    # ``deepseek-v4-pro`` stays catalog-only: vendor docs still mark it text-only.
    ("deepseek", "deepseek-flash"): _DEEPSEEK_FLASH_VISION,
    ("deepseek", "deepseek-v4-flash"): _DEEPSEEK_FLASH_VISION,
    ("deepseek", "deepseek-v4.1-flash"): _DEEPSEEK_FLASH_VISION,
    ("deepseek", "deepseek-v4-flash-vision-exp"): _DEEPSEEK_FLASH_VISION,
}


def _load_model_overrides(*, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The ``model_overrides`` config section ({} on any failure). Deliberately not memoized:
    ``load_config_readonly()`` is already (mtime, size)-cached upstream, and an ``id(cfg)``-keyed
    layer can serve stale overrides after a reload when CPython reuses the dict address."""
    overrides = (
        _cfg_get("model_overrides", default={}, config=config)
        if config is not None
        else _cfg_get("model_overrides", default={})
    )
    return _dict_or_empty(overrides)


def _provider_override_section(provider: str, *, config: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Override section for *provider* (keyed by Hermes OR models.dev id), or None."""
    overrides = (
        _load_model_overrides(config=config)
        if config is not None
        else _load_model_overrides()
    )
    provider_key = (provider or "").strip()
    if not overrides or not provider_key:
        return None
    # Forward (Hermes → models.dev id) and reverse (caller passed a models.dev id, config keyed by Hermes id) aliases.
    candidates = [provider_key, PROVIDER_TO_MODELS_DEV.get(provider_key), *_models_dev_to_hermes_ids(provider_key)]
    return next((section for section in (overrides.get(key) if key else None for key in candidates) if isinstance(section, dict)), None)


def _explicit_model_override(provider: str, model: str, *, config: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Explicit per-provider+model override dict (exact, then case-insensitive skipping the ``_default`` sentinel), or None."""
    model_key = (model or "").strip()
    section = _provider_override_section(provider, config=config) if model_key else None
    if section is None:
        return None
    entry = section.get(model_key)
    if isinstance(entry, dict):
        return entry
    model_lower = model_key.lower()
    return next((mdata for mid, mdata in section.items() if mid != "_default" and mid.lower() == model_lower and isinstance(mdata, dict)), None)


def _default_model_override(provider: str, *, config: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Fill-gap ``_default`` override: per-provider first, then global; or None."""
    section = _provider_override_section(provider, config=config)
    if section is not None and isinstance(section.get("_default"), dict):
        return section["_default"]
    overrides = (
        _load_model_overrides(config=config)
        if config is not None
        else _load_model_overrides()
    )
    global_default = overrides.get("_default")
    return global_default if isinstance(global_default, dict) else None


def _override_for(
    provider: str, model: str, *, catalog_hit: bool, config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Explicit override if any; else the ``_default`` only on a catalog miss."""
    explicit = _explicit_model_override(provider, model, config=config)
    return explicit if explicit is not None or catalog_hit else _default_model_override(provider, config=config)


def _override_int(override: dict[str, Any], key: str) -> Optional[int]:
    """Coerce an override field to a positive int, warning once on garbage."""
    raw = override.get(key)
    if raw is None:
        return None
    with contextlib.suppress(TypeError, ValueError):
        value = int(raw)
        if value > 0:
            return value
    warn_key = (key, repr(raw))
    if warn_key not in _OVERRIDE_WARNED_KEYS:
        _OVERRIDE_WARNED_KEYS.add(warn_key)
        logger.warning("model_overrides: ignoring invalid %s value %r (expected a positive integer)", key, raw)
    return None


def _override_context_window(provider: str, model: str) -> Optional[int]:
    """EXPLICITLY overridden context_window, or None. Explicit-only on purpose: this runs early in the
    resolution chain (agent/model_metadata.py, before custom_providers and live probes) where a
    ``_default`` must not preempt more specific sources; fill-gap defaults apply in ``lookup_models_dev_context``."""
    ov = _explicit_model_override(provider, model)
    return _override_int(ov, "context_window") if ov is not None else None


def _default_override_context(provider: str) -> Optional[int]:
    """Fill-gap context from a ``_default`` override, for catalog misses."""
    default = _default_model_override(provider)
    return _override_int(default, "context_window") if default is not None else None


def _override_to_catalog_shape(override: dict[str, Any]) -> tuple[dict[str, Any], Optional[bool]]:
    """Translate canonical override keys into a models.dev-shaped patch. Returns ``(patch, vision)`` —
    vision is out-of-band because it maps onto the ``modalities.input`` list rather than a scalar field."""
    patch: dict[str, Any] = {}
    limit = {
        catalog_key: value for catalog_key, override_key in (("context", "context_window"),)
        if (value := _override_int(override, override_key)) is not None
    }
    if limit:
        patch["limit"] = limit
    for override_key, catalog_key in (("supports_tools", "tool_call"), ("supports_reasoning", "reasoning")):
        if override_key in override:
            patch[catalog_key] = bool(override[override_key])
    vision: Optional[bool] = None
    if "supports_vision" in override:
        vision = patch["attachment"] = bool(override["supports_vision"])
    if "model_family" in override:
        patch["family"] = str(override["model_family"] or "")
    return patch, vision


def _merge_catalog_entry_with_override(raw: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Patch a catalog entry with a canonical-schema override. Sub-dicts (``limit``, ``modalities``) are
    merged, not clobbered — setting only ``context_window`` must not wipe the catalog's ``limit.output``."""
    shaped, vision_override = _override_to_catalog_shape(override)
    merged = dict(raw)
    limit_patch = shaped.pop("limit", None)
    if limit_patch:
        merged["limit"] = {**_dict_or_empty(raw.get("limit")), **limit_patch}
    if vision_override is not None:
        base_mods = dict(_dict_or_empty(raw.get("modalities")))
        input_mods = base_mods.get("input")
        input_mods = list(input_mods) if isinstance(input_mods, list) else []
        if vision_override and "image" not in input_mods:
            input_mods.append("image")
        elif not vision_override and "image" in input_mods:
            input_mods.remove("image")
        base_mods["input"] = input_mods
        merged["modalities"] = base_mods
    merged.update(shaped)
    return merged


def _builtin_model_metadata(
    provider: str, model: str, *, config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Built-in metadata for a provider/model pair, if Hermes has a vendor-specific entry."""
    provider_key = _models_dev_id(provider, config=config) or (provider or "").strip()
    return _BUILTIN_MODEL_METADATA.get((provider_key, (model or "").strip().lower()))


def _relay_vision_marker_metadata(provider: str, model: str) -> Optional[dict[str, Any]]:
    """Fill-gap base for an OpenCode Zen/Go ``*-vision*`` model id the catalog does not know. The relays
    resell vendor previews (``deepseek-v4-flash-vision-exp``) before models.dev indexes them, and the id's
    ``-vision`` token is the vendor's own capability marker; without it ``image_input_mode: auto`` treats
    the model as text-only and detours images through the lossy describe path (#96066). Every other field
    keeps the unknown-model defaults, so only vision is claimed."""
    from .boundaries import opencode_provider_family

    if "-vision" not in (model or "").strip().lower() or opencode_provider_family(provider) is None:
        return None
    return {**_UNKNOWN_MODEL_BASE, "modalities": {"input": ["text", "image"], "output": ["text"]}}


def _provider_model_capabilities(provider: str, model: str) -> dict[str, Any]:
    """Exact-model declaration from the registered ``ProviderProfile.model_capabilities`` (canonical
    ``model_overrides`` schema). The ONE plugin seam: every consumer that reads models.dev through this
    module (picker badges, image routing, ``/api/model/info``, context lookup) sees it (#102115)."""
    from ..chat_transport import provider_profile as get_provider_profile

    profile = get_provider_profile(provider)
    return profile.model_capabilities.get(model, {}) if profile is not None else {}


def _apply_overrides(
    provider: str, model: str, entry: Optional[dict[str, Any]], *, config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Catalog/builtin metadata, patched by the plugin's declaration, then by the explicit user override.
    ``_UNKNOWN_MODEL_BASE`` is the base on a catalog miss; a fill-gap ``_default`` applies only when no
    source knows the model. None when nothing knows it."""
    builtin = _builtin_model_metadata(provider, model, config=config)
    base = entry if entry is not None else builtin
    declared = _provider_model_capabilities(provider, model)
    if declared:
        base = _merge_catalog_entry_with_override(base if base is not None else _UNKNOWN_MODEL_BASE, declared)
    override = _override_for(provider, model, catalog_hit=base is not None, config=config)
    if base is None:
        base = _relay_vision_marker_metadata(provider, model)
    return base if override is None else _merge_catalog_entry_with_override(base if base is not None else _UNKNOWN_MODEL_BASE, override)


def _entry_supports_vision(entry: dict[str, Any]) -> bool:
    """Prefer explicit ``modalities.input`` (the older ``attachment`` flag can be stale or too broad
    for image routing); fall back to it only when the input modalities are absent/invalid."""
    input_mods = _dict_or_empty(entry.get("modalities", {})).get("input")
    return "image" in input_mods if isinstance(input_mods, list) else bool(entry.get("attachment", False))


def get_model_capabilities(
    provider: str, model: str, *, allow_network: bool = False, config: Optional[dict[str, Any]] = None,
) -> Optional[ModelCapabilities]:
    """Capability metadata from the models.dev cache, or None if unresolvable. EXPLICIT ``model_overrides``
    patch catalog fields; ``_default`` fills the gap only for models the catalog does not know. Unspecified
    fields fall through to the catalog, or to safe defaults. ``allow_network`` defaults to False (hot path).

    EXPLICIT ``model_overrides`` entries (per-provider+model) win over catalog values for the fields they
    set. ``_default`` entries fill the gap only for models the catalog does not know — the supported
    self-unblock path for custom/local models (#8731) and for models with wrong metadata in models.dev
    (#84482).
    """
    models = _get_provider_models(provider, allow_network=allow_network, config=config)
    entry = _find_model_entry(models, model, provider) if models is not None else None
    unknown_base = (
        entry is None
        and _builtin_model_metadata(provider, model, config=config) is None
    )
    raw = _apply_overrides(provider, model, entry, config=config)
    if raw is None:
        return None
    return ModelCapabilities(
        supports_tools=bool(raw.get("tool_call", False)),
        supports_vision=(
            None
            if unknown_base and "attachment" not in raw and "modalities" not in raw
            else _entry_supports_vision(raw)
        ),
        supports_reasoning=None if unknown_base and "reasoning" not in raw else bool(raw.get("reasoning", False)),
        context_window=_extract_limit(raw, "context") or 200000,
        max_output_tokens=_extract_limit(raw, "output"),
        model_family=raw.get("family", "") or "",
    )


def _parse_model_info(model_id: str, raw: dict[str, Any], provider_id: str) -> ModelInfo:
    """Convert a raw models.dev model entry dict into a ModelInfo dataclass."""
    cost = _dict_or_empty(raw.get("cost"))
    modalities = _dict_or_empty(raw.get("modalities"))
    def _mods(key: str) -> tuple[str, ...]:
        mods = modalities.get(key) or []
        return tuple(mods) if isinstance(mods, list) else ()
    def _cost(key: str) -> Optional[float]:
        return float(cost[key]) if cost.get(key) is not None else None
    return ModelInfo(
        id=model_id, name=raw.get("name", "") or model_id, family=raw.get("family", "") or "", provider_id=provider_id,
        **{k: bool(raw.get(k, False)) for k in ("reasoning", "tool_call", "attachment", "temperature", "structured_output", "open_weights")},
        input_modalities=_mods("input"), output_modalities=_mods("output"),
        context_window=_extract_limit(raw, "context") or 0, max_output=_extract_limit(raw, "output") or 0, max_input=_extract_limit(raw, "input"),
        cost_input=float(cost.get("input", 0) or 0), cost_output=float(cost.get("output", 0) or 0),
        cost_cache_read=_cost("cache_read"), cost_cache_write=_cost("cache_write"),
        knowledge_cutoff=raw.get("knowledge", "") or "", release_date=raw.get("release_date", "") or "",
        status=raw.get("status", "") or "", interleaved=raw.get("interleaved", False),
    )


def get_model_info(
    provider_id: str, model_id: str, *, allow_network: bool = False, config: Optional[dict[str, Any]] = None,
) -> Optional[ModelInfo]:
    """Full model metadata by Hermes or models.dev provider ID (exact match, then case-insensitive), or
    None if not found. EXPLICIT ``model_overrides`` patch known catalog models; ``_default`` fills the gap
    only for unknown ones. ``allow_network`` defaults to False — cost guard and inventory are hot paths.

    ``model_overrides`` entries use the SAME canonical schema as every other consumer (``context_window``,
    ``supports_*``, ``model_family``) — they are translated into the catalog shape at
    this boundary, and sub-dicts (``limit``, ``modalities``) are merged rather than clobbered. See #84482,
    #8731.
    """
    mdev_id = _models_dev_id(provider_id, config=config) or provider_id
    models = _registry_models(mdev_id, allow_network=allow_network)
    mid, entry = next(_iter_model_entries(models, model_id, suffix_fallback=False, provider=provider_id), (model_id, None)) if models is not None else (model_id, None)
    # Not in catalog — an override (explicit or _default) may still provide it.
    raw = _apply_overrides(provider_id, model_id, entry, config=config)
    return _parse_model_info(mid, raw, mdev_id) if raw is not None else None

