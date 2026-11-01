from __future__ import annotations
import re
from typing import Optional
_ANTHROPIC_FAST_MODE_MODELS = frozenset({"claude-opus-4-8", "claude-opus-5", "claude-opus-5-5"})


def is_anthropic_fast_mode_model(model: Optional[str]) -> bool:
    """Whether *model* accepts Anthropic fast mode. Accepts vendor-prefixed, dotted, variant and
    dated spellings (``anthropic/claude-opus-5.5``, ``claude-opus-4-8-20260601``). Dedicated
    ``...-fast`` ids select fast inference through the model field and are not in the list."""
    name = str(model or "").strip().lower().split(":", 1)[0].rsplit("/", 1)[-1]
    name = re.sub(r"(\d)\.(\d)", r"\1-\2", name)
    return re.sub(r"-\d{8}$", "", name) in _ANTHROPIC_FAST_MODE_MODELS

