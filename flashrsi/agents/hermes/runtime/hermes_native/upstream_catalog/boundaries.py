"""Explicit immutable catalog/config replacing ambient caches and profiles."""

import gzip
import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

settings = ContextVar("hermes_catalog_settings", default={})


@lru_cache(maxsize=1)
def bundled_catalog():
    return json.loads(gzip.decompress(Path(__file__).with_name("models_dev.json.gz").read_bytes()))


def fetch_models_dev(force_refresh=False, *, allow_network=True):
    explicit = settings.get().get("models_dev_catalog")
    return explicit if isinstance(explicit, dict) else bundled_catalog()


def load_config_readonly():
    return settings.get()


def cfg_get(config, *keys, default=None):
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def opencode_provider_family(provider):
    from ..chat_transport import provider_profile

    raw = str(provider or "").strip().lower()
    profile = provider_profile(raw)
    canonical = profile.name if profile else raw
    families = ("opencode-zen", "opencode-go")
    if canonical in families:
        return canonical
    return next((family for family in families if raw.startswith(family)), None)
