"""Pi v1.4.0 SettingsManager and SDK tool-selection behavior.

Reference: packages/coding-agent/src/core/settings-manager.ts,
getDefaultTools(), resolveDefaultTools(), and applyToolModifiers().
"""

import json

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import default_tools
from flashrsi.agents.pi_agent.runtime.pi_native.loop import _selected_tools


def _settings(tmp_path, value):
    directory = tmp_path / ".pi" / "agent"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "settings.json").write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([], []),
        (["read", "grep"], ["read", "grep"]),
        (["-write", "+grep"], ["read", "bash", "edit", "grep"]),
        (["read", "write", "-write", "+grep"], ["read", "grep"]),
        (["+grep", "-grep"], ["read", "bash", "edit", "write"]),
        (["-write", "+write"], ["read", "bash", "edit", "write"]),
        (["+read", "+read"], ["read", "bash", "edit", "write"]),
        (["read", "read", "-read"], ["read"]),
        (["read", 7, False, None], ["read"]),
        (["-read", "-bash", "-edit", "-write"], []),
        (["custom-tool"], ["custom-tool"]),
        (["+", "-"], ["read", "bash", "edit", "write"]),
        (None, []),
        ("read", []),
    ],
)
def test_pi_settings_tool_selection_matches_upstream(tmp_path, entries, expected):
    _settings(tmp_path, {"defaultTools": entries})
    assert default_tools(tmp_path) == expected


def test_pi_missing_default_tools_uses_builtin_defaults(tmp_path):
    assert default_tools(tmp_path) == ["read", "bash", "edit", "write"]
    _settings(tmp_path, {})
    assert default_tools(tmp_path) == ["read", "bash", "edit", "write"]


def test_pi_explicit_modifiers_build_on_snapshot_selection(tmp_path):
    _settings(tmp_path, {"defaultTools": ["-write", "+grep"]})
    assert _selected_tools({"tools": ["-edit", "+ls"]}, tmp_path) == [
        "read",
        "bash",
        "grep",
        "ls",
    ]
    assert _selected_tools({"tools": []}, tmp_path) == []
    assert _selected_tools({"tools": ["read"]}, tmp_path) == ["read"]


def test_pi_explicit_tools_rejects_mixed_modifier_syntax():
    # SDK/CLI validation differs deliberately from permissive settings parsing.
    with pytest.raises(ValueError, match="mix"):
        _selected_tools({"tools": ["read", "+grep"]})
