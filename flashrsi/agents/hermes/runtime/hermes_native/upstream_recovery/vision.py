from __future__ import annotations
from typing import Any

_IMAGE_PART_TYPES = {"image_url", "input_image"}


_TEXT_PART_TYPES = {"text", "input_text"}


def _is_image_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES


def _salvage_text_parts(content: list, *, any_dict_text: bool) -> list[str]:
    """Stripped, non-empty text from string parts and text-typed dict parts (or any dict's
    ``text`` when ``any_dict_text``), in order."""
    texts: list[str] = []
    for part in content:
        if isinstance(part, str):
            text = part.strip()
        elif isinstance(part, dict) and (any_dict_text or part.get("type") in _TEXT_PART_TYPES):
            text = str(part.get("text", "") or "").strip()
        else:
            continue
        if text:
            texts.append(text)
    return texts


def _provider_model_key(agent: Any) -> tuple[str, str]:
    """``(provider.lower(), model)`` as recorded in ``_no_list_tool_content_models``.
    Module-level so ``MagicMock(spec=AIAgent)`` agents in tests don't swallow it."""
    return (
        (getattr(agent, "provider", "") or "").strip().lower(),
        (getattr(agent, "model", "") or "").strip(),
    )
