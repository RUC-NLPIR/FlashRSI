"""Private, crash-readable evidence for bounded tau2 conversations."""

import json
import os
from pathlib import Path

from flashrsi._records import _redact


def _read_rows(path):
    rows, truncated = [], False
    if path.exists():
        lines = path.read_bytes().splitlines(keepends=True)
        for index, line in enumerate(lines):
            try:
                rows.append(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                # Only a torn final append can be caused by the hard kill.
                if index != len(lines) - 1 or line.endswith(b"\n"):
                    raise
                truncated = True
    return rows, truncated


class _Evidence:
    def __init__(self, path=None, secrets=()):
        self.path = Path(path) if path is not None else None
        self.secrets = secrets
        self.rows = []

    def append(self, row):
        # Redact before persistence, including partial records read after SIGKILL.
        row = _redact(row, self.secrets)
        self.rows.append(row)
        if self.path is not None:
            data = json.dumps(row, ensure_ascii=False).encode() + b"\n"
            with os.fdopen(
                os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600),
                "ab",
            ) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

    def read(self):
        rows = self.rows
        truncated = False
        if self.path is not None:
            rows, truncated = _read_rows(self.path)
            # Completed native calls clean their temporary directories. A hard
            # kill leaves only the interrupted call, whose flushed events retain
            # model usage even before Agent.run has returned a Trajectory.
            for path in sorted(
                (self.path.parent / "native").glob(
                    "flashrsi-miniagent-*/runs/run_*/trace.jsonl"
                )
            ):
                events, torn = _read_rows(path)
                rows.append({"type": "Tau2InterruptedAgentTrace", "events": events})
                truncated |= torn
        rows = _redact(rows, self.secrets)
        calls = []
        for row in rows:
            if row["type"] == "Tau2InterruptedAgentTrace":
                calls.extend(e for e in row["events"] if e.get("kind") == "model_usage")
                continue
            if row["type"] != "Tau2AgentExecution":
                continue
            usage = row["trajectory"]["usage"]
            if usage.get("model_calls"):
                calls.extend(usage["model_calls"])
            elif usage:
                calls.append({"usage": usage, "call_id": usage.get("session_id")})
        return {
            "messages": rows,
            "usage": {"model_calls": calls} if calls else {},
            "evidence_truncated": truncated,
        }
