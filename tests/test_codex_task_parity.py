"""Real file-editing tasks through both pinned harnesses; only the model is replayed.

Compare every model request (including instructions, tools and tool feedback),
the final files, exit status and usage. These scenarios cover their exercised
task paths, not arbitrary tasks or real-model success rates.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import sys

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex


def _python(source):
    return f"{shlex.quote(sys.executable)} -B -c {shlex.quote(source)}"


def _shell(command, index):
    return _events(
        call=("shell_command", {"command": command}),
        response_id=f"resp_task_{index}",
    )


def _patch(patch, index):
    events = [
        {"type": "response.created", "response": {"id": f"resp_task_{index}"}},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "id": f"ctc_task_{index}",
                "call_id": f"call_task_{index}",
                "name": "apply_patch",
                "input": patch,
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": f"resp_task_{index}",
                "usage": {
                    "input_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 5},
                    "output_tokens": 3,
                    "output_tokens_details": {"reasoning_tokens": 1},
                    "total_tokens": 23,
                },
            },
        },
    ]
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


def _scenario(name):
    buggy = 'def slug(value):\n    return value.strip().lower().replace(" ", "-")\n'
    fixed = 'def slug(value):\n    return "-".join(value.split()).lower()\n'
    patch = (
        "*** Begin Patch\n*** Update File: maths.py\n@@\n"
        '-    return value.strip().lower().replace(" ", "-")\n'
        '+    return "-".join(value.split()).lower()\n'
        "*** Add File: verify.py\n"
        "+from maths import slug\n"
        '+assert slug(" A  B ") == "a-b"\n'
        '+assert slug("你好\\tWORLD") == "你好-world"\n'
        '+assert slug("") == ""\n'
        '+print("3 task checks passed")\n'
        "*** End Patch\n"
    )
    expected = {
        "maths.py": fixed,
        "verify.py": (
            "from maths import slug\n"
            'assert slug(" A  B ") == "a-b"\n'
            'assert slug("你好\\tWORLD") == "你好-world"\n'
            'assert slug("") == ""\n'
            'print("3 task checks passed")\n'
        ),
    }
    inspect = _shell("cat maths.py", 1)
    verify = _shell(f"{shlex.quote(sys.executable)} -B verify.py", 4)
    if name == "failing_test_then_fix":
        failing = _python(
            'from maths import slug; actual = slug(" A  B "); '
            'print("observed=" + repr(actual)); raise SystemExit(actual != "a-b")'
        )
        steps = [inspect, _shell(failing, 2), _patch(patch, 3), verify]
    elif name == "failed_patch_then_repair":
        invalid = (
            "*** Begin Patch\n*** Update File: maths.py\n@@\n"
            '-    return "missing context"\n+    return "incorrect"\n*** End Patch\n'
        )
        steps = [_patch(invalid, 0), inspect, _patch(patch, 3), verify]
    else:
        raise AssertionError(name)
    steps.append(_events("TASK_FIXED_AND_VERIFIED", response_id="resp_task_done"))
    return {"maths.py": buggy}, steps, expected


@pytest.mark.parametrize(
    "scenario", ["failing_test_then_fix", "failed_patch_then_repair"]
)
@pytest.mark.parametrize("sandbox", ["danger-full-access", "workspace-write"])
def test_native_and_python_complete_same_file_editing_task(
    scenario, sandbox, parity_source, upstream_codex, tmp_path
):
    if sandbox == "workspace-write" and sys.platform != "darwin":
        pytest.skip("The Python restricted sandbox is currently implemented on macOS")
    config_file = parity_source / "config.toml"
    config_file.write_text(config_file.read_text() + "shell_snapshot = false\n")
    task = tmp_path / "task"
    initial, steps, expected = _scenario(scenario)
    observed = []
    with _responses_server() as replay:
        for label, binary in (("native", upstream_codex), ("python", None)):
            shutil.rmtree(task, ignore_errors=True)
            task.mkdir()
            for name, content in initial.items():
                (task / name).write_text(content)
            replay.reset([(200, step) for step in steps])
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 30,
                "sandbox": sandbox,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Fix slug so it joins whitespace-separated words with one hyphen. "
                    "Add regression checks for repeated whitespace, Unicode, and empty input. "
                    "Run the checks before finishing.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "TASK_FIXED_AND_VERIFIED"
            assert not replay.errors and not replay.steps
            assert len(replay.requests) == len(steps)
            files = {
                path.relative_to(task).as_posix(): path.read_text()
                for path in task.rglob("*")
                if path.is_file()
            }
            assert files == expected
            final_inputs = replay.requests[-1]["body"]["input"]
            outputs = [
                item["output"]
                for item in final_inputs
                if item["type"] in {"function_call_output", "custom_tool_call_output"}
            ]
            assert "3 task checks passed" in outputs[-1]
            if scenario == "failing_test_then_fix":
                assert "Exit code: 1" in outputs[1] and "observed='a--b'" in outputs[1]
            else:
                assert "apply_patch verification failed" in outputs[0]
            trace = _normalize(
                {
                    "requests": replay.requests,
                    "files": files,
                    "status": result.status,
                    "output": result.output,
                    "usage": dict(result.usage),
                },
                tmp_path,
            )
            (tmp_path / f"{label}-task-trace.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2)
            )
            observed.append(trace)
    assert observed[0] == observed[1], f"Full task traces in {tmp_path}"
