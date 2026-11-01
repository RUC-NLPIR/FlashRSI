"""Pinned upstream Chat Completions output-budget recovery."""

from typing import Any, Optional

def _model_output_limit(agent):
    # Upstream returns None for every Chat Completions route.
    return None

def boosted_output_cap(agent: Any, requested_cap: Optional[int], n: int, base: Optional[int] = None) -> int:
    """Output budget for truncation retry ``n`` (1-based): ``base·2ⁿ``, never below the
    failed request's cap, at most ``max(32768, 2×cap)``, and never above the model's
    known output limit. ``base`` defaults to max_tokens, else the cap actually sent.

    A ceiling equal to the requested cap would re-send the same budget (#72770); a
    ceiling past the model limit only buys a provider 400 (#79715).
    """
    if base is None:
        base = agent.max_tokens or requested_cap or 4096
    anchor = requested_cap or base
    limit = _model_output_limit(agent)
    if limit and anchor >= limit:
        return anchor  # already at the model ceiling: doubling cannot help
    boost = min(max(base * (2 ** n), requested_cap or 0), max(32768, anchor * 2))
    return min(boost, limit) if limit else boost
