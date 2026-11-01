"""Compression's status classification boundary; no host plugin/provider discovery."""
from dataclasses import dataclass
from enum import Enum

class FailoverReason(Enum):
    auth = 'auth'
    auth_permanent = 'auth_permanent'
    overloaded = 'overloaded'
    rate_limit = 'rate_limit'
    unknown = 'unknown'

@dataclass
class ClassifiedError:
    reason: FailoverReason

def classify_api_error(exc):
    code = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
    text = str(exc).lower()
    reason = FailoverReason.unknown
    if any(marker in text for marker in ('insufficient_quota', 'quota exceeded', 'quota_exceeded', 'out of funds', 'out of credits', 'out of credit', 'out of extra usage')) and not any(marker in text for marker in ('rate limit', 'rate_limit', 'try again', 'retry after', 'reset in')):
        reason = FailoverReason.unknown
    elif code == 429 or 'rate limit' in text or 'rate_limit' in text:
        reason = FailoverReason.rate_limit
    elif code in (401, 403) or 'authentication' in text or 'invalid api key' in text or any(marker in text for marker in ('invalid_api_key', 'gateway_auth_failed', 'unauthorized', 'forbidden', 'invalid token', 'token expired', 'token revoked', 'access denied', 'http 401', 'failed to extract accountid from token')):
        reason = FailoverReason.auth
    elif code in (503, 529) or 'overloaded' in text:
        reason = FailoverReason.overloaded
    return ClassifiedError(reason)
