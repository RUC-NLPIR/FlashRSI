"""Actual Computer provider profile."""

import os
import sys
from typing import Any
from urllib.parse import urlparse

from ..profile_registry import register_provider
from ..provider_base import ProviderProfile

DEFAULT_ACTUAL_BASE_URL = "https://api.actual.inc/v1"


class ActualProfile(ProviderProfile):
    """Actual Computer: hosted at api.actual.inc; local (offline-mode client)
    inference opted into via model.base_url in config.yaml."""


    def supported_reasoning_efforts(self, model: str | None) -> tuple[str, ...] | None:
        from ..reasoning_effort import ACTUAL_RELAY_EFFORTS

        return ACTUAL_RELAY_EFFORTS

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(reasoning_config, dict):
            return {}, {}
        from ..reasoning_effort import thinking_toggle_extras

        # The relay accepts ``none`` as a real effort level: it switches thinking off AND
        # is echoed as reasoning_effort, unlike the Moonshot/DeepSeek wires.
        effort_none = str(reasoning_config.get("effort") or "").strip().lower() == "none"
        if reasoning_config.get("enabled") is not False and effort_none:
            return {"thinking": {"type": "disabled"}}, {"reasoning_effort": "none"}
        supported = self.supported_reasoning_efforts(context.get("model")) or ()
        return thinking_toggle_extras(reasoning_config, supported, always_emit_toggle=True)



actual = ActualProfile(
    name="actual",
    aliases=("actual-computer", "actualcomputer", "aci"),
    display_name="Actual Computer",
    description="Actual Computer - hosted inference via api.actual.inc, or local "
    "offline inference via model.base_url in config.yaml",
    signup_url="https://actual.inc",
    env_vars=("ACTUAL_API_KEY",),
    base_url=DEFAULT_ACTUAL_BASE_URL,
    auth_type="api_key",
    api_mode="chat_completions",
)

register_provider(actual)
