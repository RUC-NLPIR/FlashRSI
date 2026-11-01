"""Native boundary for the pinned original Hermes pricing and empty guard."""

from .upstream_pricing.boundaries import metadata
from .upstream_pricing.usage_pricing import estimate_usage_cost as _estimate


def estimate_usage_cost(*args, pricing_metadata=None, **kwargs):
    token = metadata.set(pricing_metadata or {})
    try:
        return _estimate(*args, **kwargs)
    finally:
        metadata.reset(token)
