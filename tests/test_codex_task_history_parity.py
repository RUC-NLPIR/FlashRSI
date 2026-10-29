"""A file-editing task with parallel evidence, truncated history and real checks."""

import asyncio
import json
import shutil

from test_codex_core_parity import _normalize
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_native import _events
from test_codex_native import responses_server as responses_server
from test_codex_task_parity import _patch, _python, _shell

from flashrsi.agents import Codex


def _parallel_evidence():
    commands = []
    for own, peer, output in (
        (
            "left.ready",
            "right.ready",
            "LEFT_BEGIN: change VALUE to 42\n"
            + "ordinary log line 你好\n" * 1600
            + "LEFT_END: enable settings and rename the old file\n",
        ),
        (
            "right.ready",
            "left.ready",
            "RIGHT_EVIDENCE: delete obsolete.txt; add executable regression checks\n",
        ),
    ):
        commands.append(
            _python(
                "from pathlib import Path\nimport time\n"
                f"Path({own!r}).write_text('ready')\n"
                "deadline=time.monotonic()+5\n"
                f"while not Path({peer!r}).exists():\n"
                "    if time.monotonic()>deadline: raise RuntimeError('parallel peer never started')\n"
                "    time.sleep(0.01)\n"
                f"print({output!r},end='')\n"
            )
        )
    events = [{"type": "response.created", "response": {"id": "resp_parallel"}}]
    for name, command in zip(("left", "right"), commands, strict=True):
        events.append(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": f"fc_parallel_{name}",
                    "call_id": f"call_parallel_{name}",
                    "name": "shell_command",
                    "arguments": json.dumps({"command": command, "login": False}),
                },
            }
        )
    events.append(
        {
            "type": "response.completed",
            "response": {
                "id": "resp_parallel",
                "usage": {
                    "input_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 5},
                    "output_tokens": 3,
                    "output_tokens_details": {"reasoning_tokens": 1},
                    "total_tokens": 23,
                },
            },
        }
    )
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


def test_native_and_python_preserve_parallel_truncated_evidence_through_file_task(
    parity_source, upstream_codex, responses_server, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        "tool_output_token_limit=256\n"
        + config_file.read_text()
        + "shell_snapshot=false\n"
    )
    initial = {
        "service.py": "VALUE = 0\n",
        "settings.ini": "enabled=false\n",
        "old_name.txt": "old contents\n",
        "obsolete.txt": "delete me\n",
    }
    checks = (
        "from pathlib import Path\n"
        "from service import VALUE\n"
        "assert VALUE == 42\n"
        "assert Path('settings.ini').read_text() == 'enabled=true\\n'\n"
        "assert Path('archive/renamed.txt').read_text() == 'renamed contents\\n'\n"
        "assert not Path('old_name.txt').exists()\n"
        "assert not Path('obsolete.txt').exists()\n"
        "for marker in ('left.ready', 'right.ready'):\n"
        "    assert Path(marker).read_text() == 'ready'\n"
        "    Path(marker).unlink()\n"
        "print('HISTORY_TASK_CHECKS_PASSED: value, settings, rename, deletion, parallel evidence')\n"
    )
    patch = (
        "*** Begin Patch\n"
        "*** Update File: service.py\n@@\n-VALUE = 0\n+VALUE = 42\n"
        "*** Update File: settings.ini\n@@\n-enabled=false\n+enabled=true\n"
        "*** Update File: old_name.txt\n*** Move to: archive/renamed.txt\n"
        "@@\n-old contents\n+renamed contents\n"
        "*** Delete File: obsolete.txt\n"
        "*** Add File: verify.py\n"
        + "".join("+" + line + "\n" for line in checks.splitlines())
        + "*** End Patch\n"
    )
    expected = {
        "service.py": "VALUE = 42\n",
        "settings.ini": "enabled=true\n",
        "archive/renamed.txt": "renamed contents\n",
        "verify.py": checks,
    }
    evidence = _parallel_evidence()
    task = tmp_path / "task"
    observed = []

    def reply(request):
        body = request["body"]
        assert body["parallel_tool_calls"] is True
        outputs = {
            item["call_id"]: item["output"]
            for item in body["input"]
            if item["type"] in {"function_call_output", "custom_tool_call_output"}
        }
        if not outputs:
            return evidence
        left, right = (outputs[f"call_parallel_{name}"] for name in ("left", "right"))
        assert "Exit code: 0" in left and "Exit code: 0" in right
        assert "LEFT_BEGIN: change VALUE to 42" in left
        assert "LEFT_END: enable settings and rename the old file" in left
        assert "tokens truncated" in left
        assert "RIGHT_EVIDENCE: delete obsolete.txt" in right
        assert len(left) < 3000, (
            "The large output must be truncated before the next request"
        )
        if "call_task_2" not in outputs:
            return _patch(patch, 2)
        patched = outputs["call_task_2"]
        assert "Success. Updated the following files:" in patched
        assert all(name in patched for name in expected)
        assert "obsolete.txt" in patched
        if "call_resp_task_3" not in outputs:
            return _shell(_python("exec(open('verify.py').read())"), 3)
        verified = outputs["call_resp_task_3"]
        assert "Exit code: 0" in verified and "HISTORY_TASK_CHECKS_PASSED" in verified
        return _events(
            "HISTORY_TASK_FIXED_AND_VERIFIED", response_id="resp_history_done"
        )

    responses_server.reply = reply
    for label, binary in (("native", upstream_codex), ("python", None)):
        shutil.rmtree(task, ignore_errors=True)
        task.mkdir()
        for name, text in initial.items():
            (task / name).write_text(text)
        responses_server.requests.clear()
        responses_server.errors.clear()
        config = {
            "source_dir": parity_source,
            "llm": {
                "model_name": "gpt-5.4",
                "api_key": "local-parity-test-key",
                "base_url": responses_server.base_url,
            },
            "sandbox": "danger-full-access",
            "timeout": 30,
        }
        if binary:
            config["cli_path"] = binary
        result = asyncio.run(
            Codex(config).run(
                "Inspect both independent evidence sources, preserve the beginning and end "
                "of the long report, then update the existing service and settings, rename "
                "the old file, remove the obsolete file, and add and run regression checks.",
                working_dir=task,
            )
        )
        assert result.status == "finished", (
            result.error_message,
            responses_server.errors,
        )
        assert result.output == "HISTORY_TASK_FIXED_AND_VERIFIED"
        assert not responses_server.errors and len(responses_server.requests) == 4
        files = {
            path.relative_to(task).as_posix(): path.read_text()
            for path in task.rglob("*")
            if path.is_file()
        }
        assert files == expected
        assert result.usage["prompt_tokens"] == 80
        assert result.usage["completion_tokens"] == 12
        assert result.usage["prompt_tokens_details"]["cached_tokens"] == 20
        trace = _normalize(
            {
                "requests": responses_server.requests,
                "files": files,
                "status": result.status,
                "output": result.output,
                "usage": dict(result.usage),
            },
            tmp_path,
        )
        (tmp_path / f"{label}-history-task.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2)
        )
        observed.append(trace)
    assert observed[0] == observed[1], f"Full history/file task traces in {tmp_path}"
