"""Real task regressions discovered by the 2026-10-29 native tools audit."""

import asyncio
import json
import shlex
import shutil
import sys

import pytest
from test_codex_core_parity import _events, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex
from test_codex_python_code_mode import _stream
from test_codex_task_exec_parity import _normalize_exec_trace

from flashrsi.agents import Codex


@pytest.mark.parametrize(
    "case",
    [
        "nested_error",
        "environment_policy",
        "shell_patch",
        "shell_patch_classic",
        "shell_patch_cd",
        "shell_patch_multiline",
        "shell_patch_compound",
        "shell_patch_compound_invalid",
        "shell_patch_compound_partial",
        "shell_patch_compound_binary_delete",
        "shell_patch_compound_empty",
        "shell_patch_compound_extra_args",
        "shell_patch_bad_body",
        "shell_patch_legacy",
        "shell_patch_raw",
        "shell_patch_budget",
        "repeated_patch",
        "null_output_budget",
        "delete_binary",
        "signal_exit",
        "signal_exit_classic",
        "null_timeout_classic",
    ],
)
def test_task_tools_follow_native_execution_mechanisms(
    case, parity_source, upstream_codex, tmp_path, monkeypatch
):
    options, initial = "unified_exec=true\n", {}
    if case == "nested_error":
        options = "unified_exec=false\ncode_mode=true\ncode_mode_host=true\n"
        event = _stream(
            'try { await tools.view_image({path:"missing.png"}); text("SUCCESS_BRANCH"); } catch(error) { text("CATCH_BRANCH"); text(error); }',
            1,
        )
    elif case == "environment_policy":
        monkeypatch.setenv("AUDIT_ENV_CANARY", "parent-visible")
        monkeypatch.setenv("AUDIT_ENV_OVERRIDE", "parent-value")
        options += '\n[shell_environment_policy]\ninherit="none"\nexclude=["AUDIT_ENV_CANARY"]\nset={PATH="/usr/bin:/bin",AUDIT_ENV_OVERRIDE="configured-value"}\n'
        probe = 'import os,json; names=["AUDIT_ENV_CANARY","AUDIT_ENV_OVERRIDE","CODEX_CI","TERM","PAGER"]; print(json.dumps({k:os.getenv(k) for k in names},sort_keys=True))'
        event = _events(
            call=(
                "exec_command",
                {
                    "cmd": shlex.quote(sys.executable) + " -c " + shlex.quote(probe),
                    "shell": "/bin/sh",
                    "login": False,
                },
            )
        )
    elif case.startswith("shell_patch"):
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        patch = "*** Begin Patch\n*** Add File: added.py\n+VALUE = 42\n*** End Patch"
        command = "apply_patch <<'PATCH'\n" + patch + "\nPATCH"
        if case == "shell_patch_cd":
            command = "cd 'sub dir'&&applypatch <<'PATCH'\n" + patch + "\nPATCH"
            initial = {"sub dir/keep": b"keep"}
        elif case == "shell_patch_multiline":
            command = "cd \"sub dir\" &&\napplypatch <<'PATCH'\n" + patch + "\nPATCH"
            initial = {"sub dir/keep": b"keep"}
        elif case.startswith("shell_patch_compound"):
            if case == "shell_patch_compound_invalid":
                command = "apply_patch <<'PATCH'\ninvalid patch\nPATCH"
            elif case == "shell_patch_compound_partial":
                initial = {"value.py": b"actual\n"}
                patch = "*** Begin Patch\n*** Add File: added.py\n+retained\n*** Update File: value.py\n@@\n-missing\n+value\n*** End Patch"
                command = "applypatch <<'PATCH'\n" + patch + "\nPATCH"
            elif case == "shell_patch_compound_binary_delete":
                initial = {"asset.bin": b"\xff\x00asset"}
                patch = "*** Begin Patch\n*** Delete File: asset.bin\n*** End Patch"
                command = "applypatch <<'PATCH'\n" + patch + "\nPATCH"
            elif case == "shell_patch_compound_empty":
                command = "applypatch </dev/null"
            elif case == "shell_patch_compound_extra_args":
                command = "apply_patch first second"
            command = "printf 'prefix\\n'; " + command
        elif case == "shell_patch_bad_body":
            command = "apply_patch <<'PATCH'\ninvalid patch\nPATCH"
        if case == "shell_patch_raw":
            command = patch
        arguments = {"cmd": command, "shell": "/bin/sh", "login": False}
        name = "exec_command"
        if case == "shell_patch_classic":
            name = "shell_command"
            arguments = {"command": command, "login": False}
            options = "unified_exec=false\n"
        elif case == "shell_patch_legacy":
            name = "shell"
            arguments = {"command": ["applypatch", patch]}
        elif case == "shell_patch_budget":
            arguments["max_output_tokens"] = 4
        event = _events(call=(name, arguments))
    elif case in {"repeated_patch", "delete_binary"}:
        if case == "repeated_patch":
            initial = {"value.py": b"a\n"}
            patch = "*** Begin Patch\n*** Update File: value.py\n@@\n-a\n+b\n*** Update File: value.py\n@@\n-a\n+c\n*** End Patch"
        else:
            initial = {"asset.bin": b"\xff\x00asset"}
            patch = "*** Begin Patch\n*** Delete File: asset.bin\n*** End Patch"
        event = _stream(patch, 1).replace(b'"name": "exec"', b'"name": "apply_patch"')
    else:
        arguments = {
            "cmd": "kill -TERM $$"
            if case.startswith("signal_exit")
            else "printf NULL_OPTION_OK",
            "shell": "/bin/sh",
            "login": False,
        }
        if case == "null_output_budget":
            arguments["max_output_tokens"] = None
        name = "exec_command"
        if case.endswith("_classic"):
            name = "shell_command"
            options = "unified_exec=false\n"
            arguments = {"command": arguments["cmd"], "login": False}
            if case == "null_timeout_classic":
                arguments["timeout_ms"] = None
        event = _events(call=(name, arguments))
    (parity_source / "config.toml").write_text(
        "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=false\n"
        + options
    )
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            shutil.rmtree(task)
            task.mkdir()
            for name, contents in initial.items():
                (task / name).parent.mkdir(parents=True, exist_ok=True)
                (task / name).write_bytes(contents)
            replay.reset([(200, event), (200, _events("TASK_TOOLS_VERIFIED"))])
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-regression-key",
                    "base_url": replay.base_url,
                },
                "timeout": 45,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Execute the supplied local programming task.", working_dir=task
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "TASK_TOOLS_VERIFIED"
            assert not replay.errors and not replay.steps
            observed.append(
                _normalize_exec_trace(
                    {
                        "requests": json.loads(json.dumps(replay.requests)),
                        "files": {
                            str(path.relative_to(task)): path.read_bytes().hex()
                            for path in task.rglob("*")
                            if path.is_file()
                        },
                        "output": result.output,
                        "usage": dict(result.usage),
                    },
                    tmp_path,
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / f"task-tools-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


@pytest.mark.parametrize("continuation", ["same_response", "none", "supported_tool"])
def test_legacy_local_shell_items_do_not_dispatch_or_request_followup(
    continuation, parity_source, upstream_codex, tmp_path
):
    legacy = {
        "type": "local_shell_call",
        "id": "lsh_legacy",
        "call_id": "call_legacy",
        "status": "completed",
        "action": {
            "type": "exec",
            "command": ["/bin/sh", "-c", "printf EXECUTED > legacy-must-not-exist"],
        },
    }
    items = [legacy]
    if continuation == "same_response":
        items.append(
            {
                "type": "message",
                "id": "msg_legacy_answer",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "LEGACY_ITEM_IGNORED"}],
            }
        )
    elif continuation == "supported_tool":
        items.append(
            {
                "type": "function_call",
                "id": "fc_plan",
                "call_id": "call_plan",
                "name": "update_plan",
                "arguments": json.dumps(
                    {"plan": [{"step": "Finish task", "status": "completed"}]}
                ),
            }
        )
    events = [
        {"type": "response.created", "response": {"id": "resp_legacy"}},
        *({"type": "response.output_item.done", "item": item} for item in items),
        {
            "type": "response.completed",
            "response": {
                "id": "resp_legacy",
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
    stream = "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()
    task = tmp_path / "task"
    task.mkdir()
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, stream), (200, _events("FOLLOWUP_ANSWER"))])
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-regression-key",
                    "base_url": replay.base_url,
                },
                "timeout": 45,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Inspect the legacy protocol item.", working_dir=task)
            )
            assert not replay.errors
            assert not (task / "legacy-must-not-exist").exists()
            observed.append(
                _normalize_exec_trace(
                    {
                        "requests": json.loads(json.dumps(replay.requests)),
                        "status": result.status,
                        "error": result.error_message,
                        "output": result.output,
                        "usage": dict(result.usage),
                        "unused_responses": len(replay.steps),
                    },
                    tmp_path,
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / f"local-shell-{label}.json").write_text(json.dumps(trace, indent=2))
    native = observed[0]
    expected_requests = 2 if continuation == "supported_tool" else 1
    assert len(native["requests"]) == expected_requests
    assert native["unused_responses"] == 2 - expected_requests
    assert (
        native["output"]
        == {
            "same_response": "LEGACY_ITEM_IGNORED",
            "none": "",
            "supported_tool": "FOLLOWUP_ANSWER",
        }[continuation]
    )
    assert observed[0] == observed[1]
