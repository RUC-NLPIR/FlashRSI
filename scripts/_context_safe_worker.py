"""Retry context overflow after removing progress-only Claude SDK events.

The original prompt is always tried first. Successful requests are unchanged,
including replayed serial requests. Raw target trajectories remain untouched.
Actual thinking text, tool use/results, output, feedback and other system events
are preserved; only the SDK's numeric thinking_tokens progress notices are removed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from scripts._experiment_runtime import CachedLLM


def _progress(message):
    if not isinstance(message, dict):
        return False
    data = message.get("data")
    return (
        set(message) == {"type", "subtype", "data"}
        and message["type"] == "SystemMessage"
        and message["subtype"] == "thinking_tokens"
        and isinstance(data, dict)
        and data.get("type") == "system"
        and data.get("subtype") == "thinking_tokens"
        and set(data)
        <= {
            "type",
            "subtype",
            "estimated_tokens",
            "estimated_tokens_delta",
            "session_id",
            "uuid",
        }
    )


def strip_progress_events(prompt):
    marker = (
        "EVIDENCE (training tasks only):\n"
        if prompt.startswith(("[SkillOpt: failure]", "[SkillOpt: success]"))
        else "COMPARISON: "
        if prompt.startswith(("[SkillOpt: meta]", "[SkillOpt: slow]"))
        else None
    )
    if marker is None or marker not in prompt:
        return prompt, 0
    start = prompt.index(marker) + len(marker)
    try:
        value, length = json.JSONDecoder().raw_decode(prompt[start:])
    except json.JSONDecodeError:
        return prompt, 0
    removed = 0

    def visit(value):
        nonlocal removed
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "messages" and isinstance(child, list):
                    kept = [message for message in child if not _progress(message)]
                    removed += len(child) - len(kept)
                    value[key] = kept
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(value)
    if not removed:
        return prompt, 0
    return (
        prompt[:start]
        + json.dumps(value, ensure_ascii=False)
        + prompt[start + length :],
        removed,
    )


class ContextSafeLLM(CachedLLM):
    async def _run(self, prompt, working_dir=None):
        first = await super()._run(prompt, working_dir)
        error = first.error_message or ""
        if first.status != "error" or not (
            "maximum context length" in error or "context_length_exceeded" in error
        ):
            return first
        cleaned, removed = strip_progress_events(prompt)
        if not removed:
            return first
        second = await super()._run(cleaned, working_dir)
        recovery = {
            "type": "ContextLengthRecovery",
            "policy": "remove_numeric_thinking_tokens_progress_events_only",
            "initial_error": error,
            "removed_events": removed,
            "original_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "retry_prompt_sha256": hashlib.sha256(cleaned.encode()).hexdigest(),
            "original_characters": len(prompt),
            "retry_characters": len(cleaned),
        }
        return replace(second, messages=(*first.messages, recovery, *second.messages))
