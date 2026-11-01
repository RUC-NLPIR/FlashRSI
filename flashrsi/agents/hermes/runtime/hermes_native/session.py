"""Explicit, atomic session persistence for the native Hermes context engine.

No ambient session is discovered. A caller opts in with ``session_file`` and
concurrent runs sharing that path serialize before reading or changing it.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .upstream_loop.persistence import _is_ephemeral_scaffolding


class Session:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.state: dict = {}
        self._lock = None

    async def open(self) -> None:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = (self.path.parent / (self.path.name + ".lock")).open("a+b")
        try:
            while True:
                try:
                    fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            if self.path.exists():
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if (
                    not isinstance(value, dict)
                    or value.get("format") != "hermes-native-v1"
                ):
                    raise ValueError("Unrecognized Hermes session format")
                history = value.get("messages")
                if not isinstance(history, list) or any(
                    not isinstance(item, dict)
                    or item.get("role") not in {"system", "user", "assistant", "tool"}
                    for item in history
                ):
                    raise ValueError("Invalid Hermes session messages")
                self.state = value
        except BaseException:
            self.close()
            raise

    def save(self, messages, todos, context_state) -> None:
        history = copy.deepcopy(
            [row for row in messages if not _is_ephemeral_scaffolding(row)]
        )
        # A cancelled tool round must not be replayed as an unpaired call or
        # executed again when the next invocation resumes this session.
        index = 0
        while index < len(history):
            message = history[index]
            calls = (
                message.get("tool_calls", [])
                if message.get("role") == "assistant"
                else []
            )
            if calls:
                end = index + 1
                while end < len(history) and history[end].get("role") == "tool":
                    end += 1
                paired = {row.get("tool_call_id") for row in history[index + 1 : end]}
                missing = [
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": "Tool execution was interrupted; no completed result was recorded.",
                    }
                    for call in calls
                    if call.get("id") not in paired
                ]
                history[end:end] = missing
                index = end + len(missing)
            else:
                index += 1
        if history and history[-1].get("role") == "tool":
            history.append(
                {
                    "role": "assistant",
                    "content": "The turn was interrupted before a final response.",
                }
            )
        value = {
            "format": "hermes-native-v1",
            "baseline": "v0.22.5",
            "last_activity": time.time(),
            "messages": history,
            "todos": todos,
            "context_state": context_state,
            "runtime_started_at": self.state.get("runtime_started_at"),
        }
        fd, temporary = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.state = value
        finally:
            Path(temporary).unlink(missing_ok=True)

    def save_checkpoint(self, messages, context_state):
        """Durably retain the pre-compaction transcript before any lossy rewrite."""
        content = {"messages": messages, "context_state": context_state}
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        digest = hashlib.sha256(encoded).hexdigest()
        directory = self.path.parent / (self.path.name + ".checkpoints")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("Hermes checkpoint directory must be a real directory")
        path = directory / (digest + ".json")
        fd, temporary = tempfile.mkstemp(
            prefix=digest + ".", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {"id": digest, "path": str(path)}

    def close(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None
