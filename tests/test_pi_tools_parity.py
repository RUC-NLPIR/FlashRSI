"""Tool contract replay against executed Pi v1.4.0 source (offline)."""

import base64
import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.tools import (
    execute_tool,
    prepare_tool_arguments,
    tool_schemas,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/pi_tool_contract_upstream.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURE["validation"], ids=lambda case: case["name"])
def test_tool_validation_matches_original_source(case):
    arguments = copy.deepcopy(case["arguments"])
    if "error" in case:
        with pytest.raises(ValueError) as error:
            prepare_tool_arguments(case["tool"], arguments)
        assert str(error.value) == case["error"]
    else:
        assert prepare_tool_arguments(case["tool"], arguments) == case["result"]
    assert arguments == case["arguments"]


def test_all_model_visible_schemas_match_original_source():
    names = list(FIXTURE["manifest"])
    assert tool_schemas(names) == [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": FIXTURE["manifest"][name]["description"],
                "parameters": FIXTURE["manifest"][name]["parameters"],
            },
        }
        for name in names
    ]


def test_validation_prevents_object_path_and_coerces_write_bytes(tmp_path):
    rejected = execute_tool("write", {"path": {"bad": 1}, "content": "x"}, tmp_path)
    assert rejected.is_error
    assert not list(tmp_path.iterdir())
    accepted = execute_tool("write", {"path": "note.txt", "content": 123}, tmp_path)
    assert not accepted.is_error
    assert (tmp_path / "note.txt").read_bytes() == b"123"


@pytest.mark.parametrize("case", FIXTURE["execution"], ids=lambda case: case["name"])
def test_executed_tool_outputs_match_original_source(case, tmp_path):
    for relative, encoded in case["files"].items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(encoded))
    result = execute_tool(
        case["tool"],
        case["arguments"],
        tmp_path,
        model=(case.get("context") or {}).get("model"),
    )
    actual = {
        "content": result.content_blocks or [{"type": "text", "text": result.content}],
        "details": result.details,
        "is_error": result.is_error,
    }
    spill = result.details.get("fullOutputPath")
    if spill:
        data = Path(spill).read_bytes()
        actual["spill"] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        actual = json.loads(json.dumps(actual).replace(spill, "<OUTPUT>"))
        Path(spill).unlink()
    actual = json.loads(json.dumps(actual).replace(str(tmp_path), "<WORKDIR>"))
    assert actual == case["result"]


def test_bash_cancel_and_timeout_kill_descendants(tmp_path):
    for argument in [{"timeout": 0.03}, {}]:
        cancelled = threading.Event()
        timer = None
        if not argument:
            timer = threading.Timer(0.03, cancelled.set)
            timer.start()
        try:
            result = execute_tool(
                "bash",
                {
                    "command": "printf before; (sleep .2; printf escaped > escaped.txt) & wait",
                    **argument,
                },
                tmp_path,
                cancel_event=cancelled,
            )
        finally:
            if timer:
                timer.cancel()
        assert result.is_error
        assert result.content.startswith("before\n\nCommand ")
        time.sleep(0.25)
        assert not (tmp_path / "escaped.txt").exists()
