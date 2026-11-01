"""Source port of Pi v1.4.0 context compaction (MIT, pinned in UPSTREAM.md).

All decisions operate on the persisted canonical transcript.  Provider usage is
trusted only when it postdates the latest context edit or compaction checkpoint.
"""

from __future__ import annotations

import copy
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .session import current_system_message, entry_messages, project

DEFAULT_SETTINGS = {"enabled": True, "reserveTokens": 16384, "keepRecentTokens": 20000}


@lru_cache(maxsize=1)
def _model_catalog() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("model_limits.json").read_text(encoding="utf-8")
    )


def model_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
    llm = config.get("llm", {})
    name = str(llm.get("model_name", "")).strip()
    if "/" in name:
        provider, model = name.split("/", 1)
    else:
        provider, model = str(llm.get("provider_name", "")), name
    name = f"{provider.strip().lower()}/{model.strip()}"
    return _model_catalog().get(name, {})


def model_limits(config: Mapping[str, Any]) -> tuple[int, int]:
    llm = config.get("llm", {})
    baseline = model_metadata(config)
    context = config.get(
        "context_window",
        llm.get(
            "context_window",
            llm.get("contextWindow", baseline.get("contextWindow", 128000)),
        ),
    )
    output = config.get(
        "model_max_tokens",
        llm.get(
            "model_max_tokens",
            llm.get("max_output_tokens", baseline.get("maxTokens", 16384)),
        ),
    )
    for label, value in (("context_window", context), ("model_max_tokens", output)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Pi {label} must be a non-negative integer")
    return context, output


def js_length(text: str) -> int:
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def js_json(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return re.sub(
        r"[\ud800-\udfff]", lambda match: "\\u" + f"{ord(match[0]):04x}", serialized
    )


def content_text(content: Any, separator: str = "\n") -> str:
    if isinstance(content, str):
        return content
    return separator.join(
        block.get("text", "")
        for block in content or []
        if isinstance(block, Mapping) and block.get("type") == "text"
    )


def settings(config: Mapping[str, Any], files_dir: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    path = files_dir / ".pi" / "agent" / "settings.json"
    if path.is_file():
        root = json.loads(path.read_text(encoding="utf-8"))
    value = config.get("compaction", {})
    if isinstance(value, bool):
        value = {"enabled": value}
    if not isinstance(value, Mapping):
        raise ValueError("Pi compaction must be a mapping or boolean")
    result = dict(DEFAULT_SETTINGS)
    # Pi settings permit per-model reserve/keep overrides.
    name = str(config.get("llm", {}).get("model_name", ""))
    if "/" not in name:
        name = f"{config.get('llm', {}).get('provider_name', '')}/{name}"
    for source in (root.get("compaction", {}), value):
        if not isinstance(source, Mapping):
            raise ValueError("Pi compaction settings must be a mapping")
        unknown = set(source) - {
            "enabled",
            "reserveTokens",
            "keepRecentTokens",
            "modelOverrides",
            "reserve_tokens",
            "keep_recent_tokens",
        }
        if unknown:
            raise ValueError(
                "Pi unknown compaction option(s): " + ", ".join(sorted(unknown))
            )
        overrides = source.get("modelOverrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("Pi compaction.modelOverrides must be a mapping")
        for key, override_value in overrides.items():
            if not isinstance(override_value, Mapping) or set(override_value) - {
                "reserveTokens",
                "keepRecentTokens",
            }:
                raise ValueError(f"Pi invalid compaction.modelOverrides[{key!r}]")
            if any(
                isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 2**53 - 1
                for v in override_value.values()
            ):
                raise ValueError(
                    f"Pi compaction.modelOverrides[{key!r}] requires non-negative safe integers"
                )
        result.update(source)
        override = (
            source.get("modelOverrides", {}).get(name, {})
            if isinstance(source, Mapping)
            else {}
        )
        for key in ("reserveTokens", "keepRecentTokens"):
            if key in override:
                result[key] = override[key]
    for snake, camel in (
        ("reserve_tokens", "reserveTokens"),
        ("keep_recent_tokens", "keepRecentTokens"),
    ):
        if snake in value:
            result[camel] = value[snake]
    if not isinstance(result["enabled"], bool):
        raise ValueError("Pi compaction.enabled must be boolean")
    for key in ("reserveTokens", "keepRecentTokens"):
        if (
            not isinstance(result[key], int)
            or isinstance(result[key], bool)
            or result[key] < 0
            or result[key] > 2**53 - 1
        ):
            raise ValueError(f"Pi compaction.{key} must be a non-negative safe integer")
    return {key: result[key] for key in DEFAULT_SETTINGS}


def retry_settings(config: Mapping[str, Any], files_dir: Path) -> dict[str, Any]:
    path = files_dir / ".pi" / "agent" / "settings.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    explicit = config.get("retry", {})
    if not isinstance(explicit, Mapping):
        raise ValueError("Pi retry must be a mapping")
    value = {
        "enabled": True,
        "maxRetries": 3,
        "baseDelayMs": 2000,
        "maxAgentDelayMs": 60000,
        **saved.get("retry", {}),
        **explicit,
    }
    unknown = set(value) - {
        "enabled",
        "maxRetries",
        "baseDelayMs",
        "maxAgentDelayMs",
        "provider",
    }
    if unknown:
        raise ValueError("Pi unknown retry option(s): " + ", ".join(sorted(unknown)))
    if not isinstance(value["enabled"], bool):
        raise ValueError("Pi retry.enabled must be boolean")
    provider = value.get("provider", {})
    if not isinstance(provider, Mapping) or set(provider) - {
        "maxRetries",
        "timeoutMs",
        "maxRetryDelayMs",
    }:
        raise ValueError(
            "Pi retry.provider accepts maxRetries, timeoutMs, maxRetryDelayMs"
        )
    for field, setting in provider.items():
        if (
            isinstance(setting, bool)
            or not isinstance(setting, int)
            or not 0 <= setting <= 2**53 - 1
        ):
            raise ValueError(
                f"Pi retry.provider.{field} must be a non-negative safe integer"
            )
    for key in ("maxRetries", "baseDelayMs", "maxAgentDelayMs"):
        if (
            isinstance(value[key], bool)
            or not isinstance(value[key], int)
            or value[key] < 0
        ):
            raise ValueError(f"Pi retry.{key} must be a non-negative integer")
    return value


def branch_settings(config: Mapping[str, Any], files_dir: Path) -> dict[str, Any]:
    path = files_dir / ".pi" / "agent" / "settings.json"
    root = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    explicit = config.get("branch_summary", config.get("branchSummary", {}))
    if isinstance(explicit, bool):
        explicit = {"enabled": explicit}
    if not isinstance(explicit, Mapping):
        raise ValueError("Pi branch_summary must be a mapping or boolean")
    result = {
        "enabled": True,
        "reserveTokens": 16384,
        **root.get("branchSummary", {}),
        **explicit,
    }
    unknown = set(result) - {
        "enabled",
        "reserveTokens",
        "skipPrompt",
        "customInstructions",
        "replaceInstructions",
        "label",
    }
    if unknown:
        raise ValueError(
            "Pi unknown branch_summary option(s): " + ", ".join(sorted(unknown))
        )
    if not isinstance(result["enabled"], bool):
        raise ValueError("Pi branch_summary.enabled must be boolean")
    reserve = result["reserveTokens"]
    if (
        isinstance(reserve, bool)
        or not isinstance(reserve, int)
        or not 0 <= reserve <= 2**53 - 1
    ):
        raise ValueError(
            "Pi branch_summary.reserveTokens must be a non-negative safe integer"
        )
    for key in ("customInstructions", "label"):
        if key in result and not isinstance(result[key], str):
            raise ValueError(f"Pi branch_summary.{key} must be a string")
    for key in ("replaceInstructions", "skipPrompt"):
        if key in result and not isinstance(result[key], bool):
            raise ValueError(f"Pi branch_summary.{key} must be boolean")
    return result


def is_retryable_summary_error(error: str) -> bool:
    return not any(re.search(p, error, re.I) for p in NON_RETRYABLE_ERRORS) and any(
        re.search(p, error, re.I) for p in RETRYABLE_ERRORS
    )


def calculate_context_tokens(usage: Mapping[str, Any]) -> float:
    return usage.get("totalTokens", 0) or sum(
        usage.get(k, 0) for k in ("input", "output", "cacheRead", "cacheWrite")
    )


def estimate_tokens(message: Mapping[str, Any]) -> int:
    chars = 0
    role, content = message.get("role"), message.get("content") or []
    if role in {"system", "user", "toolResult", "custom"}:
        if isinstance(content, str):
            chars = js_length(content)
        else:
            chars = sum(
                4800
                if b.get("type") == "image"
                else js_length(b.get("text", ""))
                if b.get("type") == "text"
                else 0
                for b in content
            )
        if role == "system":
            chars += sum(
                js_length(v) for v in message.get("sections", {}).values() if v
            )
            if message.get("toolsAdded") is not None:
                chars += js_length(js_json(message["toolsAdded"]))
    elif role == "assistant":
        for block in content:
            if block.get("type") == "text":
                chars += js_length(block.get("text", ""))
            elif block.get("type") == "thinking":
                chars += js_length(block.get("thinking", ""))
            elif block.get("type") == "toolCall":
                chars += js_length(block.get("name", "")) + js_length(
                    js_json(block.get("arguments", {}))
                )
    elif role == "bashExecution":
        chars = js_length(message.get("command", "")) + js_length(
            message.get("output", "")
        )
    elif role in {"branchSummary", "compactionSummary"}:
        chars = js_length(message.get("summary", ""))
    return math.ceil(chars / 4)


def estimate_context_tokens(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        usage = message.get("usage")
        if (
            message.get("role") == "assistant"
            and message.get("stopReason") not in {"error", "aborted"}
            and usage
            and calculate_context_tokens(usage) > 0
        ):
            tokens = calculate_context_tokens(usage)
            trailing = sum(estimate_tokens(m) for m in messages[index + 1 :])
            return {
                "tokens": tokens + trailing,
                "usageTokens": tokens,
                "trailingTokens": trailing,
                "lastUsageIndex": index,
            }
    total = sum(estimate_tokens(m) for m in messages)
    return {
        "tokens": total,
        "usageTokens": 0,
        "trailingTokens": total,
        "lastUsageIndex": None,
    }


def estimate_projected_tokens(
    projection: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    messages = [m for entry in projection for m in entry["messages"]]
    estimate = estimate_context_tokens(messages)
    invalidating = max(
        (
            i
            for i, e in enumerate(entries)
            if e.get("type") in {"compaction", "context_edit"}
        ),
        default=-1,
    )
    if estimate["lastUsageIndex"] is not None:
        count = 0
        for entry in projection:
            count += len(entry["messages"])
            if estimate["lastUsageIndex"] < count:
                source_index = next(
                    (
                        i
                        for i, e in enumerate(entries)
                        if e.get("id") == entry["sourceEntry"].get("id")
                    ),
                    -1,
                )
                if source_index > invalidating:
                    return estimate
                break
    system = current_system_message(messages)
    tokens = (estimate_tokens(system) if system else 0) + sum(
        estimate_tokens(m) for m in messages if m.get("role") != "system"
    )
    return {
        "tokens": tokens,
        "usageTokens": 0,
        "trailingTokens": tokens,
        "lastUsageIndex": None,
    }


def should_compact(
    tokens: float, context_window: int, options: Mapping[str, Any]
) -> bool:
    return bool(
        options["enabled"] and tokens > context_window - options["reserveTokens"]
    )


TURN_START_ROLES = {
    "user",
    "bashExecution",
    "custom",
    "branchSummary",
    "compactionSummary",
}
CUT_ROLES = TURN_START_ROLES | {"assistant"}


def find_cut_point(
    entries: list[dict[str, Any]],
    start: int,
    end: int,
    keep: float,
    *,
    projected: bool = False,
) -> dict[str, Any]:
    rows = (
        entries
        if projected
        else [{"sourceEntry": e, "messages": entry_messages(e)} for e in entries]
    )

    def is_start(row):
        return row["sourceEntry"].get("type") != "compaction" and any(
            m.get("role") in TURN_START_ROLES for m in row["messages"]
        )

    points = [
        i
        for i in range(start, end)
        if rows[i]["sourceEntry"].get("type") != "compaction"
        and any(m.get("role") in CUT_ROLES for m in rows[i]["messages"])
    ]
    if not points:
        return {
            "firstKeptEntryIndex": start,
            "turnStartIndex": -1,
            "isSplitTurn": False,
        }
    cut, total, exceeded = points[0], 0, False
    for index in range(end - 1, start - 1, -1):
        tokens = sum(estimate_tokens(m) for m in rows[index]["messages"])
        if tokens == 0:
            continue
        total += tokens
        if total >= keep:
            exceeded = True
            cut = next((p for p in points if p >= index), points[-1])
            break
    if projected and exceeded:
        suffix = rows[cut + 1 : end]

        def intrinsic(row):
            return row["sourceEntry"].get("type") != "context_edit" and bool(
                entry_messages(row["sourceEntry"])
            )

        omitted = {
            row["sourceEntry"]["id"]
            for row in suffix
            if intrinsic(row) and not row["messages"]
        }
        external = any(
            row["sourceEntry"].get("type") == "context_edit"
            and row["sourceEntry"].get("replacement") is not None
            and row["sourceEntry"].get("targetId") not in omitted
            for row in suffix
        )
        if (
            not external
            and any(
                row["sourceEntry"].get("type") == "message"
                and row["sourceEntry"].get("message", {}).get("role") == "assistant"
                and intrinsic(row)
                and not row["messages"]
                for row in suffix
            )
            and all(
                row["sourceEntry"].get("type") != "compaction"
                and (not intrinsic(row) or not row["messages"])
                for row in suffix
            )
        ):
            cut += 1
    while cut > start:
        previous = rows[cut - 1]
        if previous["sourceEntry"].get("type") == "compaction" or previous["messages"]:
            break
        cut -= 1
    starts = is_start(rows[cut])
    turn = (
        -1
        if starts
        else next((i for i in range(cut, start - 1, -1) if is_start(rows[i])), -1)
    )
    return {
        "firstKeptEntryIndex": cut,
        "turnStartIndex": turn,
        "isSplitTurn": not starts and turn != -1,
    }


def file_operations(
    messages: list[dict[str, Any]], previous: Mapping[str, Any] | None = None
) -> dict[str, list[str]]:
    previous = previous if isinstance(previous, Mapping) else {}
    reads, modifications = previous.get("readFiles"), previous.get("modifiedFiles")
    read = set(reads if isinstance(reads, list) else [])
    modified = set(modifications if isinstance(modifications, list) else [])
    for message in messages:
        blocks = (
            message.get("nestedCalls", {}).get("calls", [])
            if message.get("role") == "toolResult"
            else message.get("content", [])
            if message.get("role") == "assistant"
            else []
        )
        for block in blocks:
            if message.get("role") == "assistant" and block.get("type") != "toolCall":
                continue
            arguments = block.get("arguments")
            path = arguments.get("path") if isinstance(arguments, Mapping) else None
            if not isinstance(path, str) or not path:
                continue
            if block.get("name") == "read":
                read.add(path)
            elif block.get("name") in {"write", "edit"}:
                modified.add(path)

    # JavaScript sorts strings by UTF-16 code units, which differs from Python
    # code-point order for astral filenames next to high BMP characters.
    def utf16(value):
        return value.encode("utf-16-be", errors="surrogatepass")

    return {
        "readFiles": sorted(read - modified, key=utf16),
        "modifiedFiles": sorted(modified, key=utf16),
    }


def format_file_operations(value: Mapping[str, Any]) -> str:
    parts = []
    for key, tag in (("readFiles", "read-files"), ("modifiedFiles", "modified-files")):
        if value.get(key):
            parts.append(f"<{tag}>\n" + "\n".join(value[key]) + f"\n</{tag}>")
    return "\n\n" + "\n\n".join(parts) if parts else ""


def prepare_compaction(
    entries: list[dict[str, Any]], options: Mapping[str, Any]
) -> dict[str, Any] | None:
    if entries and entries[-1].get("type") == "compaction":
        return None
    rows = project(entries)
    prev_index = next(
        (
            i
            for i, row in enumerate(rows)
            if row["sourceEntry"].get("type") == "compaction" and row["messages"]
        ),
        -1,
    )
    previous = rows[prev_index]["sourceEntry"] if prev_index >= 0 else None
    start = prev_index + 1 if previous else 0
    cut = find_cut_point(
        rows, start, len(rows), options["keepRecentTokens"], projected=True
    )
    if cut["firstKeptEntryIndex"] >= len(rows):
        return None
    history_end = (
        cut["turnStartIndex"] if cut["isSplitTurn"] else cut["firstKeptEntryIndex"]
    )

    def conversation(begin, end):
        return [
            m
            for row in rows[begin:end]
            if row["sourceEntry"].get("type") != "compaction"
            for m in row["messages"]
            if m.get("role") != "system"
        ]

    history = conversation(start, history_end)
    prefix = (
        conversation(cut["turnStartIndex"], cut["firstKeptEntryIndex"])
        if cut["isSplitTurn"]
        else []
    )
    if not history and not prefix:
        return None
    details = (
        previous.get("details") if previous and not previous.get("fromHook") else None
    )
    return {
        "firstKeptEntryId": rows[cut["firstKeptEntryIndex"]]["sourceEntry"]["id"],
        "messagesToSummarize": history,
        "turnPrefixMessages": prefix,
        "isSplitTurn": cut["isSplitTurn"],
        "tokensBefore": estimate_projected_tokens(rows, entries)["tokens"],
        **({"previousSummary": previous["summary"]} if previous else {}),
        "fileOps": file_operations(history + prefix, details),
        "settings": dict(options),
    }


def convert_to_llm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for original in messages:
        message = copy.deepcopy(original)
        role = message.get("role")
        if role in {"compactionSummary", "branchSummary"}:
            prefix = (
                "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
                if role == "compactionSummary"
                else "The following is a summary of a branch that this conversation came back from:\n\n<summary>\n"
            )
            message = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prefix
                        + message["summary"]
                        + (
                            "\n</summary>"
                            if role == "compactionSummary"
                            else "</summary>"
                        ),
                    }
                ],
                "timestamp": message.get("timestamp", 0),
            }
        elif role == "custom":
            message = {
                "role": "user",
                "content": message.get("content", []),
                "timestamp": message.get("timestamp", 0),
            }
        elif role == "bashExecution":
            if message.get("excludeFromContext"):
                continue
            text = f"Ran `{message.get('command', '')}`\n"
            text += (
                f"```\n{message['output']}\n```"
                if message.get("output")
                else "(no output)"
            )
            if message.get("cancelled"):
                text += "\n\n(command cancelled)"
            elif message.get("exitCode") not in {None, 0}:
                text += f"\n\nCommand exited with code {message['exitCode']}"
            if message.get("truncated") and message.get("fullOutputPath"):
                text += (
                    f"\n\n[Output truncated. Full output: {message['fullOutputPath']}]"
                )
            message = {
                "role": "user",
                "content": [{"type": "text", "text": text}],
                "timestamp": message.get("timestamp", 0),
            }
        if message.get("role") in {"system", "user", "assistant", "toolResult"}:
            result.append(message)
    return result


def serialize_conversation(messages: list[dict[str, Any]]) -> str:
    parts = []
    for message in convert_to_llm(messages):
        role, content = message.get("role"), message.get("content", [])
        if role == "user":
            text = content_text(content, "")
            if text:
                parts.append(f"[User]: {text}")
        elif role == "assistant":
            calls = []
            for block in content:
                if block.get("type") == "toolCall":
                    args = ", ".join(
                        f"{k}={js_json(v)}"
                        for k, v in block.get("arguments", {}).items()
                    )
                    calls.append(f"{block['name']}({args})")
            if any(b.get("type") == "text" for b in content):
                parts.append(f"[Assistant]: {content_text(content)}")
            if calls:
                parts.append("[Assistant tool calls]: " + "; ".join(calls))
        elif role == "toolResult":
            text = content_text(content, "")
            if text:
                length = js_length(text)
                if length > 2000:
                    text = (
                        text.encode("utf-16-le", errors="surrogatepass")[:4000].decode(
                            "utf-16-le", errors="surrogatepass"
                        )
                        + f"\n\n[... {length - 2000} more characters truncated]"
                    )
                parts.append(f"[Tool result]: {text}")
    return "\n\n".join(parts)


def summary_prompt(
    messages: list[dict[str, Any]],
    previous: str | None = None,
    focus: str | None = None,
    *,
    turn_prefix: bool = False,
) -> str:
    conversation = serialize_conversation(messages)
    if turn_prefix:
        text = f"# Conversation\n{conversation}\n\n# Instructions\n{TURN_PREFIX_SUMMARIZATION_PROMPT}"
    else:
        text = f"<conversation>\n{conversation}\n</conversation>\n\n"
        if previous:
            text += f"<previous-summary>\n{previous}\n</previous-summary>\n\n"
        text += UPDATE_SUMMARIZATION_PROMPT if previous else SUMMARIZATION_PROMPT
    if focus:
        text += f"\n\nAdditional focus: {focus}"
    return text


_OVERFLOW_PATTERNS = [
    r"prompt (?:is )?too long",
    r"prompt exceeds max length",
    r"request_too_large",
    r"input is too long for requested model",
    r"exceeds the context window",
    r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
    r"input token count.*exceeds the maximum",
    r"maximum prompt length is \d+",
    r"reduce the length of the messages",
    r"maximum context length is \d+ tokens",
    r"exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?",
    r"input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)",
    r"exceeds the limit of \d+",
    r"exceeds the available context size",
    r"greater than the context length",
    r"context window exceeds limit",
    r"exceeded model token limit",
    r"too large for model with \d+ maximum context length",
    r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?",
    r"model_context_window_exceeded",
    r"prompt too long; exceeded (?:max )?context length",
    r"range of input length should be",
    r"context[_ ]length[_ ]exceeded",
    r"too many tokens",
    r"token limit exceeded",
    r"^(?:[\w -]+ API error \(413\):|413(?:\s|:|$))",
]


def is_context_overflow(message: Mapping[str, Any], context_window: int = 0) -> bool:
    reason = message.get("stopReason")
    error = str(message.get("errorMessage") or "")
    if (
        reason == "error"
        and error
        and not re.search(
            r"^(Throttling error|Service unavailable):|rate limit|too many requests",
            error,
            re.I,
        )
    ):
        if any(re.search(pattern, error, re.I) for pattern in _OVERFLOW_PATTERNS):
            return True
        if message.get("provider") == "cerebras" and re.search(
            r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)", error, re.I
        ):
            return True
    usage = message.get("usage") or {}
    tokens = usage.get("input", 0) + usage.get("cacheRead", 0)
    return bool(
        context_window
        and (
            (reason == "stop" and tokens > context_window)
            or (
                reason == "length"
                and usage.get("output", 0) == 0
                and tokens >= context_window * 0.99
            )
        )
    )


def is_recoverable_length(message: Mapping[str, Any], desired_max_output: int) -> bool:
    return bool(
        message.get("stopReason") == "length"
        and desired_max_output > 0
        and message.get("usage", {}).get("output", 0) < desired_max_output
    )


# Prompt text copied verbatim from the pinned MIT-licensed upstream.
SUMMARIZATION_PROMPT = 'The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.\n\nUse this EXACT format:\n\n## Goal\n[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]\n\n## Constraints & Preferences\n- [Any constraints, preferences, or requirements mentioned by user]\n- [Or "(none)" if none were mentioned]\n\n## Progress\n### Done\n- [x] [Completed tasks/changes]\n\n### In Progress\n- [ ] [Current work]\n\n### Blocked\n- [Issues preventing progress, if any]\n\n## Key Decisions\n- **[Decision]**: [Brief rationale]\n\n## Next Steps\n1. [Ordered list of what should happen next]\n\n## Critical Context\n- [Any data, examples, or references needed to continue]\n- [Or "(none)" if not applicable]\n\nKeep each section concise. Preserve exact file paths, function names, and error messages.'

UPDATE_SUMMARIZATION_INSTRUCTIONS = 'Update the existing structured summary with new information. RULES:\n- PRESERVE all existing information from the previous summary\n- ADD new progress, decisions, and context from the new messages\n- UPDATE the Progress section: move items from "In Progress" to "Done" when completed\n- UPDATE "Next Steps" based on what was accomplished\n- PRESERVE exact file paths, function names, and error messages\n- If something is no longer relevant, you may remove it\n\nUse this EXACT format:\n\n## Goal\n[Preserve existing goals, add new ones if the task expanded]\n\n## Constraints & Preferences\n- [Preserve existing, add new ones discovered]\n\n## Progress\n### Done\n- [x] [Include previously done items AND newly completed items]\n\n### In Progress\n- [ ] [Current work - update based on progress]\n\n### Blocked\n- [Current blockers - remove if resolved]\n\n## Key Decisions\n- **[Decision]**: [Brief rationale] (preserve all previous, add new)\n\n## Next Steps\n1. [Update based on current state]\n\n## Critical Context\n- [Preserve important context, add new if needed]\n\nKeep each section concise. Preserve exact file paths, function names, and error messages.'

UPDATE_SUMMARIZATION_PROMPT = 'The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.\n\nUpdate the existing structured summary with new information. RULES:\n- PRESERVE all existing information from the previous summary\n- ADD new progress, decisions, and context from the new messages\n- UPDATE the Progress section: move items from "In Progress" to "Done" when completed\n- UPDATE "Next Steps" based on what was accomplished\n- PRESERVE exact file paths, function names, and error messages\n- If something is no longer relevant, you may remove it\n\nUse this EXACT format:\n\n## Goal\n[Preserve existing goals, add new ones if the task expanded]\n\n## Constraints & Preferences\n- [Preserve existing, add new ones discovered]\n\n## Progress\n### Done\n- [x] [Include previously done items AND newly completed items]\n\n### In Progress\n- [ ] [Current work - update based on progress]\n\n### Blocked\n- [Current blockers - remove if resolved]\n\n## Key Decisions\n- **[Decision]**: [Brief rationale] (preserve all previous, add new)\n\n## Next Steps\n1. [Update based on current state]\n\n## Critical Context\n- [Preserve important context, add new if needed]\n\nKeep each section concise. Preserve exact file paths, function names, and error messages.'

TURN_PREFIX_SUMMARIZATION_PROMPT = "The messages above are earlier context from an ongoing conversation. Later messages are stored separately and do not need to be reconstructed.\n\nCreate a concise checkpoint of the user's request and the progress shown above. This checkpoint will be placed before the later messages so the conversation can continue with the necessary context.\n\n## Original Request\n[What did the user ask for?]\n\n## Progress So Far\n- [Key decisions and work completed in these messages]\n\n## Context Needed to Continue\n- [Information from these messages needed to understand the later work]\n\nOnly summarize information explicitly present above. Do not infer or recreate later messages."

SUMMARIZATION_SYSTEM_PROMPT = "You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.\n\nDo NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."
NON_RETRYABLE_ERRORS = [
    "GoUsageLimitError",
    "FreeUsageLimitError",
    "Monthly usage limit reached",
    "available balance",
    "insufficient_quota",
    "out of budget",
    "quota exceeded",
    "billing",
    "subscription_sharing_usage_limit_exceeded",
    "subscription_sharing_workplace_individual_usage_limit_exceeded",
]

RETRYABLE_ERRORS = [
    "overloaded",
    "server_busy",
    "servers are currently busy",
    "currently experiencing high demand",
    "model is at capacity",
    "rate.?limit",
    "too many requests",
    "(?<![a-z0-9])(?:429|500|502|503|504|520|524)(?![a-z0-9])",
    "service.?(?:is.?)?(?:temporarily.?)?unavailable",
    "server.?error",
    "internal.?error",
    "provider.?returned.?(?:an.?)?error",
    "exceeded request buffer limit while retrying upstream",
    "unable to forward upstream",
    "upstream.?request.?failed",
    "upstream_stream_read_error",
    "stream was interrupted",
    "http/?2 stream failed",
    "network.?error",
    "connection.?error",
    "connection.?refused",
    "connection.?lost",
    "other side closed",
    "fetch failed",
    "request to \\S+ failed, reason:",
    "getaddrinfo",
    "ENOTFOUND",
    "EAI_AGAIN",
    "upstream.?connect",
    "reset before headers",
    "socket hang up",
    "socket connection was closed",
    "timed? out",
    "timeout",
    "terminated",
    "websocket.?closed",
    "websocket.?error",
    "ended without",
    "stream ended before message_stop",
    "stream ended before a terminal response event",
    "http2 request did not get a response",
    "stream disconnected before completion",
    "pending stream has been canceled",
    "retry delay",
    "you can retry your request",
    "try your request again",
    "please retry your request",
    "ResourceExhausted",
    "subscription_sharing_usage_unavailable",
    "subscription_sharing_user_unavailable",
]
