from __future__ import annotations
from typing import Any

class AIAgent:
    @staticmethod
    def _is_thinking_only_assistant(msg: dict[str, Any], *, drop_codex_reasoning_items: bool = True) -> bool:
        """True if ``msg`` is an assistant turn whose only payload is reasoning (no text, no tool_calls).

        Providers converting reasoning to thinking blocks reject it (400 "final block cannot be thinking"), so
        the turn is dropped from the API copy; the transcript keeps the reasoning block.
        """
        if not isinstance(msg, dict) or msg.get("role") != "assistant" or msg.get("tool_calls"):
            return False
        # Prefill stubs are thinking-only by construction; checked before content inspection since
        # repair_empty_non_final_messages may have healed content.
        if msg.get("_thinking_prefill"):
            return True
        if AIAgent._content_has_real_payload(msg.get("content")):
            return False
        # A native compaction checkpoint makes a carrier never thinking-only, regardless of api_mode or
        # reasoning field. Checked above every reasoning branch so no carrier shape is dropped.
        # The checkpoint is the server-side stand-in for already-pruned history and exists in exactly one
        # place; the codex_responses adapter also surfaces commentary text via msg["reasoning"], so the
        # string branch below would otherwise drop a carrier before the sidecar is ever inspected. See
        # #82108.
        from ..native_compaction import has_compaction_checkpoint

        if has_compaction_checkpoint(msg.get("codex_reasoning_items")):
            return False
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        rd = msg.get("reasoning_details")
        if (isinstance(reasoning, str) and reasoning.strip()) or (isinstance(rd, list) and rd):
            return True
        # Codex Responses keeps encrypted reasoning under a separate key; only real items count as
        # thinking-only, empty/junk lists fall through to generic empty-turn handling.
        codex_items = msg.get("codex_reasoning_items")
        if drop_codex_reasoning_items and isinstance(codex_items, list):
            return any(isinstance(item, dict) and item.get("type") == "reasoning" for item in codex_items)
        return False

    @staticmethod
    def _content_has_real_payload(content: Any) -> bool:
        """True when assistant ``content`` carries anything beyond (redacted) thinking blocks / whitespace."""
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    if block:  # non-empty non-dict string etc.
                        return True
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text", "")
                    if isinstance(text, str) and text.strip():
                        return True
                elif btype not in {"thinking", "redacted_thinking"}:
                    return True  # tool_use, image, document, etc. — real payload
            return False
        return content is not None and content != ""

