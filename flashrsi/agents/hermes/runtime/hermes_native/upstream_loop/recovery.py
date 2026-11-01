from __future__ import annotations


_TRANSIENT_TRANSPORT_ERRORS = frozenset({
    "ReadTimeout", "ConnectTimeout", "PoolTimeout", "ConnectError", "ReadError", "RemoteProtocolError",
    "APIConnectionError", "APITimeoutError",
})
