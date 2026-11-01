"""Execute pinned original timestamp/profile/environment prompt functions."""

import ast
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Optional
from unittest.mock import patch
from zoneinfo import ZoneInfo

source = Path(sys.argv[1])
target = Path(sys.argv[2])
namespace = {
    "Any": Any,
    "Optional": Optional,
    "Path": Path,
    "re": re,
    "sys": sys,
    "os": os,
    "logger": logging.getLogger(__name__),
}
files = {
    "agent/system_prompt.py": [
        "_zone_bits",
        "_timestamp_line",
        "_session_start_like",
        "_active_profile_line",
    ],
    "agent/prompt_builder.py": ["_local_host_hints"],
}
hashes = {}
for name, wanted in files.items():
    text = (source / name).read_text()
    lines = text.splitlines(keepends=True)
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(
                compile(
                    "from __future__ import annotations\n"
                    + "".join(lines[node.lineno - 1 : node.end_lineno]),
                    name,
                    "exec",
                ),
                namespace,
            )
    hashes[name] = hashlib.sha256(text.encode()).hexdigest()
clock = ModuleType("hermes_time")
clock.safe_strftime = lambda value, fmt: value.strftime(fmt)
sys.modules["hermes_time"] = clock
cases = []
definitions = [
    (
        "utc_same_day",
        "UTC",
        "2026-10-31T03:00:00+00:00",
        "2026-10-31T04:00:00+00:00",
        "default",
    ),
    (
        "shanghai_cross_day",
        "Asia/Shanghai",
        "2026-10-30T03:00:00+08:00",
        "2026-10-31T04:00:00+08:00",
        "research",
    ),
    (
        "dst_zone",
        "America/New_York",
        "2026-07-01T03:00:00-04:00",
        "2026-07-01T04:00:00-04:00",
        "default",
    ),
]
for name, timezone, start, now, profile in definitions:
    current = datetime.fromisoformat(now).astimezone(ZoneInfo(timezone))
    settings = {
        "timezone": timezone,
        "_runtime_started_at": start,
        "profile_name": profile,
        "profile_root": "/profiles",
        "user_home": "/home/fixture",
        "_scratch_dir": "/scratch",
        "_runtime_host": "Linux (6.1)",
        "llm": {"model_name": "test-model", "provider": "custom"},
        "platform": "cli",
        "session_id": "opaque-session",
        "pass_session_id": True,
    }
    clock.get_timezone = lambda: current.tzinfo
    clock.now = lambda: current
    namespace.update(
        _agent_home=lambda agent: Path("/profile"),
        _active_profile_name=lambda agent, ambient: profile,
        _ambient_file_safety_profile_name=lambda: profile,
        get_default_hermes_root=lambda: (
            Path("/profiles") if profile != "default" else Path("/profile")
        ),
        get_hermes_home=lambda: Path("/profile"),
        is_wsl=lambda: False,
        resolve_agent_cwd=lambda: "/task",
        get_scratch_dir=lambda: "/scratch",
    )
    agent = SimpleNamespace(
        session_start=datetime.fromisoformat(start),
        session_id="opaque-session",
        pass_session_id=True,
        model="test-model",
        provider="custom",
        platform="cli",
        _session_db=None,
    )
    with (
        patch.object(sys, "platform", "linux"),
        patch("platform.system", return_value="Linux"),
        patch("platform.release", return_value="6.1"),
        patch("os.path.expanduser", return_value="/home/fixture"),
    ):
        expected = [
            namespace["_active_profile_line"](agent),
            namespace["_timestamp_line"](agent),
            "\n\n".join(namespace["_local_host_hints"]()),
        ]
    cases.append({"name": name, "settings": settings, "now": now, "expected": expected})
target.write_text(
    json.dumps(
        {
            "commit": "bf0203a794a07aac3ff764972ab9087baa4e4f4e",
            "source_sha256": hashes,
            "cases": cases,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
