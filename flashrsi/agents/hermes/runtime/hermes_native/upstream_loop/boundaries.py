"""Explicit-runtime boundaries for upstream's optional discovery surfaces.

This snapshot has no plugins, profile registry, catalogue, or ambient configuration.
The original classifier's ordinary built-in pipeline still executes in full.
"""

from types import SimpleNamespace

_IMAGE_SHRINK_TARGET_BYTES = 4 * 1024 * 1024


def get_plugin_error_classification(**kwargs):
    return None


def get_provider_profile(provider):
    return SimpleNamespace()


def provider_owns_route(provider, base_url, config=None):
    return True if str(provider or "").lower() in {"custom", "local"} else None


def suggest_prefixed_model_id(provider, model_name):
    # No model catalogue is loaded; the original helper likewise returns None
    # when the provider/catalogue cannot resolve a unique prefixed identifier.
    return None


def estimate_usage_cost(*args, **kwargs):
    from ..pricing import estimate_usage_cost as estimate

    return estimate(*args, **kwargs)


def get_compatible_custom_providers(config=None):
    # Capability callers supply the role's explicit list. No host profile exists.
    return (config or {}).get("custom_providers", [])


def load_config_readonly():
    return {}
