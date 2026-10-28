"""Boundary checks for the optional native file-editing Worker example."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1] / "examples/claude_edit_worker/hooks/checkout_only.py"
)
spec = importlib.util.spec_from_file_location("checkout_only", SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize("tool", ["Read", "Write", "Edit", "Glob", "Grep"])
def test_current_directory_access_and_parent_escape(tmp_path, tool):
    root = tmp_path / "checkout"
    root.mkdir()
    key = "file_path" if tool in {"Read", "Write", "Edit"} else "path"
    payload = {
        "cwd": str(root),
        "tool_name": tool,
        "tool_input": {key: "inside.txt", "pattern": "**/*.py"},
    }
    assert policy.rejection(payload) is None
    payload["tool_input"][key] = "../test.json"
    assert policy.rejection(payload)
    payload["tool_input"][key] = str(tmp_path / "checkout-other/test.json")
    assert policy.rejection(payload)


def test_read_symlink_cannot_escape(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    outside = tmp_path / "sealed.txt"
    outside.write_text("held out")
    try:
        (root / "alias").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert policy.rejection(
        {"cwd": str(root), "tool_name": "Read", "tool_input": {"file_path": "alias"}}
    )


@pytest.mark.parametrize("tool", ["Bash", "Agent", "WebFetch", "Unknown"])
def test_other_tools_are_denied(tmp_path, tool):
    assert policy.rejection({"cwd": str(tmp_path), "tool_name": tool, "tool_input": {}})


@pytest.mark.parametrize("pattern", ["../**", "/root/**", "a/../../*"])
def test_glob_pattern_cannot_escape(tmp_path, pattern):
    assert policy.rejection(
        {"cwd": str(tmp_path), "tool_name": "Glob", "tool_input": {"pattern": pattern}}
    )


def test_malformed_hook_payload_denies_with_native_protocol():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="{}",
        capture_output=True,
        text=True,
        check=True,
    )
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
