"""Catalog inputs captured with the Snapshot, rather than ambient user caches.

The pricing engine and official price tables are unchanged upstream code. Live
catalog rows may be supplied explicitly under ``pricing_metadata`` so a replay
uses the same rates as the original run, without reading another user's cache.
"""

import gzip
import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

metadata = ContextVar("hermes_pricing_metadata", default={})


@lru_cache(maxsize=1)
def bundled_openrouter_metadata():
    raw = json.loads(
        gzip.decompress(
            (Path(__file__).parent / "openrouter_models.json.gz").read_bytes()
        )
    )
    return {
        str(item.get("id")): {
            "context_length": item.get("context_length", 128000),
            "max_completion_tokens": (item.get("top_provider") or {}).get(
                "max_completion_tokens", 4096
            ),
            "name": item.get("name", item.get("id", "")),
            "pricing": item.get("pricing", {}),
        }
        for item in raw.get("data", [])
        if item.get("id")
    }


def fetch_model_metadata(force_refresh=False):
    return metadata.get().get("openrouter") or bundled_openrouter_metadata()


def fetch_endpoint_model_metadata(base_url, api_key="", force_refresh=False):
    endpoints = metadata.get().get("endpoints", {})
    normalized = str(base_url or "").rstrip("/")
    return next(
        (rows for url, rows in endpoints.items() if url.rstrip("/") == normalized),
        {},
    )


def get_model_info(provider, model):
    rows = metadata.get().get("models_dev", {})
    value = rows.get(provider, {}).get(model)
    if not isinstance(value, dict):
        from ..model_catalog import model_info

        return model_info(provider, model, metadata.get())
    cost = value.get("cost", value)
    values = {
        "cost_input": cost.get("input", cost.get("cost_input", 0)),
        "cost_output": cost.get("output", cost.get("cost_output", 0)),
        "cost_cache_read": cost.get("cache_read", cost.get("cost_cache_read")),
        "cost_cache_write": cost.get("cache_write", cost.get("cost_cache_write")),
    }
    return SimpleNamespace(
        **values,
        has_cost_data=lambda: bool(values["cost_input"] or values["cost_output"]),
    )


def get_provider_profile(provider):
    from ..chat_transport import provider_profile

    return provider_profile(provider)
