from __future__ import annotations
from typing import Any, Optional

class CodexMethods:
    def _disable_codex_reasoning_replay(
        self, messages: Optional[list[dict[str, Any]]] = None, *, keep_replay: bool = False,
    ) -> dict[str, int]:
        """On HTTP 400 ``invalid_encrypted_content``: pop ``codex_reasoning_items`` from every assistant
        message and, unless ``keep_replay``, disable Responses reasoning replay. Returns
        ``{"messages", "items"}`` counts."""
        stripped_messages = stripped_items = 0
        for msg in (messages if isinstance(messages, list) else []):
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            items = msg.pop("codex_reasoning_items", None)
            if isinstance(items, list) and items:
                stripped_messages += 1
                stripped_items += len(items)
        if not keep_replay:
            self._codex_reasoning_replay_enabled = False
        return {"messages": stripped_messages, "items": stripped_items}

