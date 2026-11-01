"""Contracts and executed upstream evidence for the native Hermes tools."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native._vendor.fuzzy_match import (
    fuzzy_find_and_replace,
)
from flashrsi.agents.hermes.runtime.hermes_native._vendor.tool_output_truncate import (
    truncate_head_tail,
)
from flashrsi.agents.hermes.runtime.hermes_native.tools import HermesTools

EVIDENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_tools_upstream.json").read_text()
)
DISPATCH_EVIDENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_dispatch_upstream.json").read_text()
)


@pytest.fixture
def hermes_tools(tmp_path):
    tools = HermesTools(tmp_path, tmp_path)
    yield tools
    tools.close()


def call(tools, name, **args):
    return json.loads(tools.execute(name, args))


def test_scratch_directory_matches_shell_temp_environment(hermes_tools, tmp_path):
    hermes_tools.configure_settings({"scratch_dir": "scratch-space"})
    assert hermes_tools.scratch_dir == tmp_path / "scratch-space"
    assert hermes_tools.scratch_dir.is_dir()
    result = call(
        hermes_tools, "terminal", command='printf \'%s|%s|%s\' "$TMPDIR" "$TMP" "$TEMP"'
    )
    assert result["output"] == "|".join([str(hermes_tools.scratch_dir)] * 3)
    assert hermes_tools.scratch_dir.stat().st_mode & 0o777 == 0o700


def _substitute_workdir(value, before, after):
    if isinstance(value, str):
        return value.replace(before, after)
    if isinstance(value, list):
        return [_substitute_workdir(item, before, after) for item in value]
    if isinstance(value, dict):
        return {
            _substitute_workdir(key, before, after): _substitute_workdir(
                item, before, after
            )
            for key, item in value.items()
        }
    return value


@pytest.mark.parametrize(
    "case", DISPATCH_EVIDENCE["cases"], ids=lambda case: case["name"]
)
def test_tool_sequences_match_actual_upstream_dispatch(hermes_tools, tmp_path, case):
    """Compare original outputs and on-disk bytes after each stateful tool call."""
    root = tmp_path.resolve()
    for filename, content in case["initial_file_hex"].items():
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex(content))
    for step in case["steps"]:
        if "external_write" in step:
            mutation = step["external_write"]
            (root / mutation["path"]).write_text(mutation["content"])
        else:
            arguments = _substitute_workdir(step["args"], "<WORKDIR>", str(root))
            actual = call(hermes_tools, step["tool"], **arguments)
            assert (
                _substitute_workdir(actual, str(root), "<WORKDIR>") == step["result"]
            ), (case["name"], step["index"], step["tool"])
        assert {
            str(path.relative_to(root)): path.read_bytes().hex()
            for path in root.rglob("*")
            if path.is_file()
        } == step["file_hex"], (case["name"], step["index"])


def test_patch_schema_tracks_main_model_family(hermes_tools):
    def schema():
        return next(
            item["function"]["parameters"]
            for item in hermes_tools.schemas
            if item["function"]["name"] == "patch"
        )

    assert "mode" not in schema()["properties"]
    hermes_tools.configure_model("gpt-4.1", "openai")
    assert schema()["required"] == ["mode"]
    assert schema()["properties"]["mode"]["enum"] == ["replace", "patch"]
    assert "patch" in schema()["properties"]
    hermes_tools.configure_model("claude-sonnet-4-5", "anthropic")
    assert "mode" not in schema()["properties"]
    assert schema()["required"] == ["path", "old_string", "new_string"]


@pytest.mark.parametrize("case", EVIDENCE["fuzzy"])
def test_fuzzy_replacement_matches_executed_original(case):
    notes = []
    actual = fuzzy_find_and_replace(*case["args"], correction_notes=notes)
    assert list(actual) == case["result"]
    assert notes == case["notes"]


@pytest.mark.parametrize("case", EVIDENCE["reads"])
def test_native_read_matches_executed_original(hermes_tools, tmp_path, case):
    # This fixture executes original ShellFileOperations._read_file_native,
    # below file_tools' binary-extension guard. Dispatch has its own oracle.
    (tmp_path / case["filename"]).write_bytes(bytes.fromhex(case["hex"]))
    assert (
        hermes_tools.files.read_file(
            case["filename"], case["offset"], case["limit"]
        ).to_dict()
        == case["result"]
    )


def test_todo_sequence_matches_executed_original(hermes_tools):
    for case in EVIDENCE["todo"]:
        assert call(hermes_tools, "todo_list", **case["args"]) == case["result"]


@pytest.mark.parametrize("case", EVIDENCE["truncation"])
def test_terminal_truncation_matches_executed_original(case):
    assert truncate_head_tail(case["text"], case["limit"]) == case["result"]


def test_write_and_patch_preserve_bom_crlf_and_refuse_ambiguous_match(
    hermes_tools, tmp_path
):
    target = tmp_path / "note.txt"
    target.write_bytes("\ufeffkeep\r\n    alpha   \r\nend\r\n".encode())
    result = call(
        hermes_tools,
        "patch",
        path="note.txt",
        old_string="alpha",
        new_string="ALPHA_NEW",
    )
    assert result["success"]
    assert "+    ALPHA" in result["diff"]
    assert target.read_bytes() == "\ufeffkeep\r\n    ALPHA_NEW   \r\nend\r\n".encode()
    repeated = call(
        hermes_tools,
        "patch",
        path="note.txt",
        old_string="alpha",
        new_string="ALPHA_NEW",
    )
    assert repeated["success"] and repeated["no_change"]
    target.write_text("same\nsame\n")
    duplicate = call(
        hermes_tools,
        "patch",
        path="note.txt",
        old_string="same",
        new_string="changed",
    )
    assert not duplicate["success"]
    assert target.read_text() == "same\nsame\n"


def test_whole_file_write_requires_complete_current_view(hermes_tools, tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("one\ntwo\nthree\n")
    assert call(hermes_tools, "write_file", path="note.txt", content="bad")[
        "stale_write_blocked"
    ]
    call(hermes_tools, "read_file", path="note.txt", offset=1, limit=1)
    assert call(hermes_tools, "write_file", path="note.txt", content="bad")[
        "stale_write_blocked"
    ]
    call(hermes_tools, "read_file", path="note.txt", offset=2, limit=2)
    assert call(hermes_tools, "write_file", path="note.txt", content="new\n")[
        "verified"
    ]
    target.write_text("external\n")
    assert call(hermes_tools, "write_file", path="note.txt", content="lost\n")[
        "stale_write_blocked"
    ]
    assert target.read_text() == "external\n"


def test_display_truncation_never_counts_unseen_lines_as_read(hermes_tools, tmp_path):
    target = tmp_path / "large.txt"
    target.write_text("".join("a" * 100 + "\n" for _ in range(1500)))
    first = call(hermes_tools, "read_file", path="large.txt")
    assert first["truncated_by"] == "bytes"
    # A duplicate partial page must not turn the hidden suffix into a full view.
    call(hermes_tools, "read_file", path="large.txt", offset=1, limit=1)
    assert call(hermes_tools, "write_file", path="large.txt", content="lost")[
        "stale_write_blocked"
    ]
    call(hermes_tools, "read_file", path="large.txt", offset=first["next_offset"])
    assert call(hermes_tools, "write_file", path="large.txt", content="complete")[
        "verified"
    ]


def test_syntax_gates_and_nonblocking_python_lint(hermes_tools, tmp_path):
    for filename, content in [("bad.json", "{"), ("bad.toml", "broken = [")]:
        assert (
            "syntax validation"
            in call(hermes_tools, "write_file", path=filename, content=content)["error"]
        )
        assert not (tmp_path / filename).exists()
    assert (
        "not valid JSON"
        in call(hermes_tools, "write_file", path="nan.json", content='{"value":NaN}')[
            "error"
        ]
    )
    python = call(
        hermes_tools, "write_file", path="bad.py", content="def incomplete(\n"
    )
    assert python["verified"]
    assert python["lint"]["status"] == "error"
    assert (tmp_path / "bad.py").read_text() == "def incomplete(\n"
    surrogate = call(hermes_tools, "write_file", path="invalid.txt", content="\ud800")
    assert "lone surrogate" in surrogate["error"]
    assert not (tmp_path / "invalid.txt").exists()


def test_clamped_line_does_not_authorize_whole_file_overwrite(hermes_tools, tmp_path):
    (tmp_path / "long.txt").write_text("a" * 3000 + "\nlast\n")
    first = call(hermes_tools, "read_file", path="long.txt", limit=1)
    assert first["truncated_lines"]
    call(hermes_tools, "read_file", path="long.txt", offset=2)
    assert call(hermes_tools, "write_file", path="long.txt", content="lost")[
        "stale_write_blocked"
    ]


def test_terminal_bash_state_cwd_and_transient_workdir(hermes_tools, tmp_path):
    directory = tmp_path / "sub"
    directory.mkdir()
    (directory / "note.txt").write_text("inside\n")
    changed = call(
        hermes_tools,
        "terminal",
        command="export HERMES_TEST_VALUE='a b'; cd sub; printf '%s' ${HERMES_TEST_VALUE// /_}",
    )
    assert changed["output"] == "a_b" and changed["exit_code"] == 0
    assert Path(changed["cwd"]) == directory.resolve()
    assert call(hermes_tools, "read_file", path="note.txt")["content"] == "1|inside"
    persisted = call(
        hermes_tools,
        "terminal",
        command="printf '%s\n' \"$HERMES_TEST_VALUE\"; pwd",
    )
    assert persisted["output"] == f"a b\n{directory.resolve()}"
    call(hermes_tools, "terminal", command="pwd", workdir=str(tmp_path.resolve()))
    assert hermes_tools.cwd == directory.resolve()
    assert (
        "foreground"
        in call(hermes_tools, "terminal", command="true", background=True)["error"]
    )


def test_terminal_timeout_kills_child_before_delayed_write(hermes_tools, tmp_path):
    marker = tmp_path / "after-timeout"
    result = call(
        hermes_tools,
        "terminal",
        command=f"sleep 2; touch {marker}",
        timeout=0.05,
    )
    assert result["exit_code"] == 124 and result["error"] is None
    assert "timed out" in result["output"] and "timeout" in result["hint"]
    assert not marker.exists()


def test_close_cancels_terminal_and_waits_for_calls(hermes_tools, tmp_path):
    started = tmp_path / "started"
    with ThreadPoolExecutor() as executor:
        pending = executor.submit(
            call,
            hermes_tools,
            "terminal",
            command=f"touch {started}; sleep 2; touch {tmp_path / 'after-close'}",
        )
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        with hermes_tools._process_lock:
            processes = tuple(hermes_tools._processes)
        assert processes
        hermes_tools.close()
        pending.result(timeout=1)
        assert all(process.poll() is not None for process in processes)
        assert hermes_tools._active_calls == 0
    assert not (tmp_path / "after-close").exists()
    assert (
        call(hermes_tools, "read_file", path="missing")["error"]
        == "Hermes tools are closed"
    )


def test_independent_file_calls_run_concurrently(hermes_tools, tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    barrier = threading.Barrier(2)
    original = hermes_tools.files.read_file

    def synchronized(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    hermes_tools.files.read_file = synchronized
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(call, hermes_tools, "read_file", path=name)
            for name in ("a.txt", "b.txt")
        ]
        assert [future.result()["content"] for future in futures] == [
            "1|a.txt",
            "1|b.txt",
        ]


def test_tool_selection_and_search_contract(tmp_path):
    (tmp_path / "a.txt").write_text("first\nhit one\nhit two\n")
    tools = HermesTools(tmp_path, tmp_path, ["read_file", "search_files"])
    try:
        assert [schema["function"]["name"] for schema in tools.schemas] == [
            "read_file",
            "search_files",
        ]
        assert "disabled" in call(tools, "terminal", command="true")["error"]
        result = call(tools, "search_files", pattern="hit", path=".", limit=1)
        assert result["matches"][0]["line"] == 2
        assert result["total_count"] == 1 and "truncated" not in result
        assert call(
            tools, "search_files", pattern="hit", path=".", output_mode="count"
        )["counts"] == {"./a.txt": 2}
    finally:
        tools.close()


def test_snapshot_output_settings_are_isolated_between_concurrent_tools(tmp_path):
    (tmp_path / "long.txt").write_text("x" * 100 + "\nsecond\nthird\n")
    small = HermesTools(tmp_path, tmp_path, ["read_file"])
    large = HermesTools(tmp_path, tmp_path, ["read_file"])
    small.configure_settings({"tool_output": {"max_lines": 1, "max_line_length": 10}})
    large.configure_settings({"tool_output": {"max_lines": 3, "max_line_length": 200}})
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(call, small, "read_file", path="long.txt")
            b = executor.submit(call, large, "read_file", path="long.txt")
            short, full = a.result(), b.result()
        assert short["content"] == "1|" + "x" * 10 + "... [truncated]"
        assert short["truncated_lines"] and short["truncated"]
        assert full["content"] == "1|" + "x" * 100 + "\n2|second\n3|third"
    finally:
        small.close()
        large.close()


def test_configured_read_budget_cannot_authorize_hidden_first_line(
    hermes_tools, tmp_path
):
    target = tmp_path / "budget.txt"
    original = "x" * 100 + "\nend\n"
    target.write_text(original)
    hermes_tools.configure_settings({"file_read_max_chars": 20})
    first = call(hermes_tools, "read_file", path="budget.txt")
    assert first["truncated_by"] == "bytes"
    assert len(first["content"]) == 20 and first["next_offset"] == 2
    assert first["truncated_lines"]
    assert "20-char read budget" in first["hint"]
    call(hermes_tools, "read_file", path="budget.txt", offset=2)
    written = call(hermes_tools, "write_file", path="budget.txt", content="replacement")
    assert written.get("error")
    assert target.read_text() == original


def test_configured_terminal_output_cap_is_applied(hermes_tools):
    hermes_tools.configure_settings({"tool_output": {"max_bytes": 10}})
    result = call(hermes_tools, "terminal", command="printf 'abcdefghijklmno'")
    assert len(result["output"]) <= 10
    assert Path(result["full_output_path"]).read_text().startswith("abcdefghijklmno")
    assert result["output_total_chars"] >= 15


def test_terminal_spill_preserves_omitted_middle_and_can_be_read(hermes_tools):
    result = call(hermes_tools, "terminal", command="printf '%060000d' 0")
    assert len(result["output"]) <= 50_000
    assert "TRUNCATED" in result["output"]
    spill = Path(result["full_output_path"])
    assert spill.read_text().startswith("0" * 60_000)
    assert spill.stat().st_mode & 0o777 == 0o600
    recovered = call(hermes_tools, "read_file", path=str(spill))
    assert recovered["content"].startswith("1|0000")
    assert not recovered.get("error")
