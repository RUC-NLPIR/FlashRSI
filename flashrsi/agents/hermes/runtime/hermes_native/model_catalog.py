"""Original Hermes capability lookup against Snapshot-owned catalog data."""

from .upstream_catalog import models_dev
from .upstream_catalog.boundaries import settings as catalog_settings
from .upstream_catalog.vision import _coerce_capability_bool, _supports_vision_override


def model_capabilities(provider, model, settings=None):
    settings = settings or {}
    token = catalog_settings.set(settings)
    try:
        return models_dev.get_model_capabilities(provider, model, config=settings)
    finally:
        catalog_settings.reset(token)


def model_info(provider, model, settings=None):
    settings = settings or {}
    token = catalog_settings.set(settings)
    try:
        return models_dev.get_model_info(provider, model, config=settings)
    finally:
        catalog_settings.reset(token)


def supports_vision(route, settings):
    for explicit in (route.get("supports_vision"), settings.get("supports_vision")):
        if (value := _coerce_capability_bool(explicit)) is not None:
            return value
    provider = route.get("provider", "custom")
    model = route.get("model_name", route.get("model", ""))
    value = _supports_vision_override(
        settings, provider, model, requested_provider=route.get("requested_provider", "")
    )
    if value is not None:
        return value
    caps = model_capabilities(provider, model, settings)
    return caps.supports_vision is True if caps else False


def context_length(provider, model, settings=None):
    settings = settings or {}
    token = catalog_settings.set(settings)
    try:
        return models_dev.lookup_models_dev_context(provider, model)
    finally:
        catalog_settings.reset(token)
