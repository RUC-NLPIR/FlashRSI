from __future__ import annotations
import hashlib
import json
from typing import Any

def deterministic_call_id(fn_name: str, arguments: str, index: int = 0) -> str:
    """Deterministic call_id fallback when the API omits one (random ids would break caching)."""
    seed = f"{fn_name}:{arguments}:{index}"
    return f"call_{hashlib.sha256(seed.encode('utf-8', errors='replace')).hexdigest()[:12]}"
