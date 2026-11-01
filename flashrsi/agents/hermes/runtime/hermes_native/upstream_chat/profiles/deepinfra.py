"""DeepInfra provider profile (chat surface; image-gen/TTS/STT are wired via
their own plugin subsystems)."""

from typing import Any

from ..reasoning_effort import OPENAI_COMPAT_WIRE_EFFORTS, clamp_effort, requested_effort
from ..profile_registry import register_provider
from ..provider_base import ProviderProfile


class _DeepInfraProfile(ProviderProfile):
    """DeepInfra profile with live vision-default discovery, so shared vision
    resolution in ``agent/auxiliary_client.py`` stays provider-agnostic."""

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Map Hermes reasoning controls to DeepInfra's top-level ``reasoning_effort``.

        DeepInfra applies a per-model default when the field is absent (DeepSeek-V4.x off,
        GLM/Qwen-Thinking on), so ``none`` is the only working off switch and an unset effort
        is omitted rather than guessed. The core ``_supports_reasoning_extra_body`` allowlist
        does not know this host, so the transport always passes ``supports_reasoning=False``
        here — gating on it would make the method a permanent no-op (#111872).
        """
        if isinstance(reasoning_config, dict) and reasoning_config.get("enabled") is False:
            return {}, {"reasoning_effort": "none"}
        effort = requested_effort(reasoning_config)
        clamped = clamp_effort(effort, OPENAI_COMPAT_WIRE_EFFORTS)
        return ({}, {"reasoning_effort": clamped}) if clamped in OPENAI_COMPAT_WIRE_EFFORTS else ({}, {})



deepinfra = _DeepInfraProfile(
    name="deepinfra", aliases=("deep-infra", "deepinfra-ai"), display_name="DeepInfra",
    description="DeepInfra — 100+ open models, pay-per-use", signup_url="https://deepinfra.com/dash/api_keys",
    env_vars=("DEEPINFRA_API_KEY", "DEEPINFRA_BASE_URL"), base_url="https://api.deepinfra.com/v1/openai",
    auth_type="api_key",
    default_max_tokens=None,  # DeepInfra applies its documented per-model limit
    # The only hardcoded DeepInfra model: aux resolution is synchronous, so it
    # can't wait on a catalog round-trip. Everything else is discovered live.
    default_aux_model="deepseek-ai/DeepSeek-V4-Flash",
    # Empty on purpose: the live catalog is the source of truth; an empty picker
    # beats silently routing to a retired model.
    fallback_models=(),
)

register_provider(deepinfra)
