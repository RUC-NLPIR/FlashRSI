from __future__ import annotations
import json
import logging
from typing import Any
from .vision import _is_image_part, _salvage_text_parts, _provider_model_key
from .multimodal import _is_multimodal_tool_result, _multimodal_text_summary
logger=logging.getLogger(__name__)

class VisionMethods:
    @staticmethod
    def _content_has_image_parts(content: Any) -> bool:
        return isinstance(content, list) and any(_is_image_part(part) for part in content)

    def _tool_result_content_for_active_model(self, tool_name: str, result: Any) -> Any:
        """Tool message content that is safe for the active model. Text-only providers must not receive
        image parts: a rejected tool result becomes canonical history and can break the next user turn."""
        if not _is_multimodal_tool_result(result):
            return result

        content = result.get("content") or []
        if not self._content_has_image_parts(content):
            return content

        if self._model_supports_vision():
            # Vision on paper, but the provider rejects list-type tool content (or we already learned that
            # in-session): short-circuit to a text summary.
            if not self._provider_supports_vision_tool_messages():
                logger.debug(
                    "Tool %s: provider %s does not accept list-type tool "
                    "content — sending text summary",
                    tool_name, getattr(self, "provider", ""),
                )
                return _multimodal_text_summary(result)
            key = _provider_model_key(self)
            if key in (getattr(self, "_no_list_tool_content_models", None) or ()):
                logger.debug(
                    "Tool %s: model %s/%s known to reject list-type tool "
                    "content this session — sending text summary",
                    tool_name, key[0], key[1],
                )
                return _multimodal_text_summary(result)
            return content

        summary = _multimodal_text_summary(result)
        if tool_name == "computer_use":
            return json.dumps({
                "error": (
                    "computer_use returned screenshot/image content, but the active "
                    "model/provider does not support image input. Switch to a "
                    "vision-capable model for desktop computer use, or use browser "
                    "tools for browser tasks."
                ),
                "text_summary": summary,
            })

        logger.warning(
            "Tool %s returned image content for non-vision model %s/%s; "
            "falling back to text summary",
            tool_name, self.provider, self.model,
        )
        return summary

    def _try_strip_image_parts_from_tool_messages(
        self, api_messages: list, *, remember_model: bool = True
    ) -> bool:
        """Downgrade list-type tool messages to text in place; True if any were downgraded.

        Recovery for providers that 400 on list-type tool content (e.g. MiMo "text is not set"). By default
        records (provider, model) in ``_no_list_tool_content_models`` so later results downgrade without a
        round-trip; 413 recovery passes ``remember_model=False`` (body too large ≠ provider rejects lists).
        """
        if not isinstance(api_messages, list):
            return False

        if remember_model:
            # Record (provider, model) so we don't relearn this lesson.
            key = _provider_model_key(self)
            if not hasattr(self, "_no_list_tool_content_models"):
                self._no_list_tool_content_models = set()
            if key[1]:  # only record when we actually have a model id
                self._no_list_tool_content_models.add(key)

        changed = False
        for msg in api_messages:
            if not isinstance(msg, dict) or msg.get("role") != "tool":
                continue
            content = msg.get("content")
            # List content without image parts is left alone; stripping wouldn't reduce ambiguity.
            if not self._content_has_image_parts(content):
                continue

            # Salvage any text parts so the model still sees some signal.
            msg["content"] = "\n\n".join(_salvage_text_parts(content, any_dict_text=False)) or (
                "[image content removed — provider does not accept "
                "list-type tool message content]"
            )
            changed = True

        return changed

