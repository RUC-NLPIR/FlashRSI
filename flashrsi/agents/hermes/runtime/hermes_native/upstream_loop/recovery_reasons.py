from __future__ import annotations
from .error_classifier import FailoverReason

_RATE_LIMIT_REASONS = frozenset({
    FailoverReason.rate_limit, FailoverReason.billing, FailoverReason.upstream_rate_limit,
})


_TRANSPORT_FAILURE_REASONS = frozenset({FailoverReason.timeout, FailoverReason.overloaded})
