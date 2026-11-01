"""Pi v3 JSONL session storage and compaction-aware transcript projection.

Session locations are explicit.  The runtime never searches the host Pi home or
inherits model credentials from a saved session.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def milliseconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(
            datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
        )
    except (ValueError, TypeError):
        return 0


def entry_messages(entry: dict[str, Any]) -> list[dict[str, Any]]:
    kind = entry.get("type")
    if kind == "message":
        message = copy.deepcopy(entry.get("message", {}))
        if message.get("content") is None:
            if message.get("role") == "system":
                message["content"] = ""
            elif message.get("role") in {"user", "assistant", "toolResult"}:
                message["content"] = []
        return [message]
    if kind == "custom_message":
        return [
            {
                "role": "custom",
                "content": entry.get("content") or [],
                "customType": entry.get("customType", ""),
                "display": entry.get("display", True),
                "details": entry.get("details"),
                "timestamp": milliseconds(entry.get("timestamp")),
            }
        ]
    if kind == "branch_summary" and entry.get("summary"):
        return [
            {
                "role": "branchSummary",
                "summary": entry["summary"],
                "fromId": entry.get("fromId"),
                "timestamp": milliseconds(entry.get("timestamp")),
            }
        ]
    if kind == "compaction":
        summary = {
            "role": "compactionSummary",
            "summary": entry["summary"],
            "tokensBefore": entry.get("tokensBefore", 0),
            "timestamp": milliseconds(entry.get("timestamp")),
        }
        return (
            [copy.deepcopy(entry["systemMessage"])]
            if entry.get("systemMessage")
            else []
        ) + [summary]
    return []


def current_system_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Replay Pi system content, section patches and tool declaration deltas."""
    content, sections, tools = [], {}, {}
    first_timestamp = None
    for message in messages:
        if message.get("role") != "system":
            continue
        if first_timestamp is None:
            first_timestamp = message.get("timestamp", 0)
        value = message.get("content") or ""
        text = (
            value
            if isinstance(value, str)
            else "\n".join(
                block.get("text", "") for block in value if block.get("type") == "text"
            )
        )
        if text:
            content.append(text)
        for name, value in (message.get("sections") or {}).items():
            if value is None:
                sections.pop(name, None)
            else:
                sections[name] = value
        for tool in message.get("toolsRemoved") or []:
            tools.pop(tool["name"], None)
        for tool in message.get("toolsAdded") or []:
            tools[tool["name"]] = copy.deepcopy(tool)
    if first_timestamp is None and not tools:
        return None
    return {
        "role": "system",
        "content": "\n\n".join(content),
        **({"sections": sections} if sections else {}),
        **({"toolsAdded": list(tools.values())} if tools else {}),
        "timestamp": first_timestamp or 0,
    }


def system_message_text(message: dict[str, Any]) -> str:
    return "\n\n".join(
        value
        for value in [
            message.get("content", ""),
            *(message.get("sections") or {}).values(),
        ]
        if value
    )


def session_path(
    entries: list[dict[str, Any]], leaf_id: str | None = None
) -> list[dict[str, Any]]:
    if not entries:
        return []
    by_id = {entry["id"]: entry for entry in entries if "id" in entry}
    current = leaf_id or entries[-1].get("id")
    path, seen = [], set()
    while current and current in by_id:
        if current in seen:
            raise ValueError("Pi session contains a parent cycle")
        seen.add(current)
        entry = by_id[current]
        path.append(entry)
        current = entry.get("parentId")
    return list(reversed(path))


def project(
    entries: list[dict[str, Any]], leaf_id: str | None = None
) -> list[dict[str, Any]]:
    """Return entries plus their visible messages, matching buildSessionProjection."""
    path = session_path(entries, leaf_id)
    compact_index = next(
        (
            i
            for i in range(len(path) - 1, -1, -1)
            if path[i].get("type") == "compaction"
        ),
        None,
    )
    if compact_index is not None:
        boundary = path[compact_index]
        kept = next(
            (
                i
                for i, entry in enumerate(path[:compact_index])
                if entry.get("id") == boundary.get("firstKeptEntryId")
            ),
            compact_index,
        )
        path = (
            [boundary]
            + [
                entry
                for entry in path[kept:compact_index]
                if not (
                    entry.get("type") == "message"
                    and entry.get("message", {}).get("role") == "system"
                )
            ]
            + path[compact_index + 1 :]
        )
    edits = {
        entry.get("targetId"): entry
        for entry in path
        if entry.get("type") == "context_edit"
    }
    result = []
    for index, entry in enumerate(path):
        messages = (
            []
            if entry.get("type") == "compaction" and index > 0
            else entry_messages(entry)
        )
        if entry.get("id") in edits:
            replacement = edits[entry["id"]].get("replacement")
            if replacement is None:
                messages = []
            else:
                for message in messages:
                    if message.get("role") in {
                        "user",
                        "assistant",
                        "toolResult",
                        "custom",
                    }:
                        content = copy.deepcopy(replacement.get("content", []))
                        if message["role"] in {
                            "assistant",
                            "toolResult",
                        } and isinstance(content, str):
                            content = [{"type": "text", "text": content}]
                        message["content"] = content
        result.append({"sourceEntry": entry, "messages": messages})
    return result


class Session:
    """Append-only Pi-compatible entries; summaries commit only after success."""

    def __init__(
        self, cwd: Path, path: str | Path | None = None, leaf_id: str | None = None
    ):
        self.path = Path(path).expanduser().resolve() if path is not None else None
        self.entries: list[dict[str, Any]] = []
        self.header = {
            "type": "session",
            "version": 3,
            "id": str(uuid.uuid4()),
            "timestamp": timestamp(),
            "cwd": str(cwd),
        }
        if self.path is not None and self.path.exists():
            lines = self.path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid Pi session JSON on line {index + 1}"
                    ) from exc
                if value.get("type") == "session":
                    if value.get("version") != 3:
                        raise ValueError(
                            "Pi native sessions require JSONL session version 3"
                        )
                    self.header = value
                elif "id" in value:
                    self.entries.append(value)
        self.leaf_id = leaf_id or (self.entries[-1]["id"] if self.entries else None)
        if leaf_id and not any(entry.get("id") == leaf_id for entry in self.entries):
            raise ValueError("Pi session_leaf_id does not exist")

    def _write(self, value: dict[str, Any]) -> None:
        if self.path is not None:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, ensure_ascii=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def append(self, kind: str, **value: Any) -> dict[str, Any]:
        entry = {
            "type": kind,
            "id": uuid.uuid4().hex[:8],
            "parentId": self.leaf_id,
            "timestamp": timestamp(),
            **copy.deepcopy(value),
        }
        if self.path is not None and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(self.header)
        self._write(entry)
        self.entries.append(entry)
        self.leaf_id = entry["id"]
        return entry

    def append_message(self, message: dict[str, Any]) -> dict[str, Any]:
        return self.append("message", message=message)

    def branch(self) -> list[dict[str, Any]]:
        return (
            session_path(self.entries, self.leaf_id) if self.leaf_id is not None else []
        )

    def projection(self) -> list[dict[str, Any]]:
        return project(self.entries, self.leaf_id) if self.leaf_id is not None else []

    def messages(self) -> list[dict[str, Any]]:
        return [message for entry in self.projection() for message in entry["messages"]]

    def append_compaction(self, result: dict[str, Any]) -> dict[str, Any]:
        system = current_system_message(self.messages())
        checkpoint_timestamp = timestamp()
        if system:
            system["timestamp"] = milliseconds(checkpoint_timestamp)
        return self.append(
            "compaction",
            timestamp=checkpoint_timestamp,
            **{
                key: copy.deepcopy(result[key])
                for key in (
                    "summary",
                    "firstKeptEntryId",
                    "tokensBefore",
                    "details",
                    "usage",
                )
                if key in result
            },
            **({"systemMessage": system} if system else {}),
        )
