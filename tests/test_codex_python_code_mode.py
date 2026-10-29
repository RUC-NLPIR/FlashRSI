"""V8 cell lifecycle and native task traces; no remote model calls."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex
from flashrsi.agents.codex.python_core.code_mode import CodeMode, parse_exec_source
from flashrsi.agents.codex.python_core.shell import ToolError


class Router:
    settings = {}

    def __init__(self):
        self.calls = []
        self.extras = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    def code_mode_definitions(self):
        return [
            {
                "name": "echo",
                "global_name": "echo",
                "tool_name": {"name": "echo"},
                "description": "Echo tool",
                "kind": "function",
            },
            {
                "name": "block",
                "global_name": "block",
                "tool_name": {"name": "block"},
                "description": "Blocking tool",
                "kind": "function",
            },
        ]

    async def execute_nested(self, call):
        self.calls.append(call)
        if call["name"] == "block":
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
        return json.loads(call["arguments"])

    def append(self, item):
        self.extras.append(item)


def _exec(source, index=1):
    return {
        "type": "custom_tool_call",
        "name": "exec",
        "call_id": f"exec_test_{index}",
        "input": source,
    }


def _wait(cell_id, **args):
    return {
        "type": "function_call",
        "name": "wait",
        "call_id": "wait_test",
        "arguments": json.dumps({"cell_id": cell_id, **args}),
    }


def _text(response):
    output = response["output"]
    return (
        "\n".join(item["text"] for item in output if item["type"] == "input_text")
        if isinstance(output, list)
        else output
    )


def test_cells_have_fresh_modules_json_storage_and_v8_globals():
    async def run():
        router = Router()
        mode = CodeMode(router)
        first = await mode.execute_call(
            _exec(
                'let secret=1; const value=await tools.echo({answer:42}); store("saved",value); text(value); text([typeof process,typeof require,typeof console,typeof Atomics,typeof WebAssembly,typeof __transport,typeof __cellFinish]); text(text.constructor("return typeof process")());'
            )
        )
        assert "Script completed" in _text(first)
        assert '{"answer":42}' in _text(first)
        assert (
            '["undefined","undefined","undefined","undefined","undefined","undefined","undefined"]'
            in _text(first)
        )
        assert router.calls[0]["_source"] == "code_mode"
        second = await mode.execute_call(
            _exec(
                'const value=load("saved"); value.answer=0; text(load("saved")); text(typeof secret);',
                2,
            )
        )
        assert '{"answer":42}' in _text(second)
        assert "undefined" in _text(second)
        await mode.close()

    asyncio.run(run())


def test_explicit_yield_timer_wait_notifications_and_missing_cell():
    async def run():
        router = Router()
        mode = CodeMode(router)
        first = await mode.execute_call(
            _exec(
                'text("before"); yield_control(); await new Promise(resolve=>setTimeout(resolve,20)); notify("progress"); text("after"); store("finished",true);'
            )
        )
        assert "Script running with cell ID 1" in _text(first)
        assert "before" in _text(first) and "after" not in _text(first)
        final = await mode.execute_call(_wait("1"))
        assert "Script completed" in _text(final) and "after" in _text(final)
        assert mode.stored["finished"] is True
        assert final["extra_items"] == [
            {
                "type": "custom_tool_call_output",
                "call_id": "exec_test_1",
                "name": "exec",
                "output": "progress",
            }
        ]
        assert "exec cell 1 not found" in _text(await mode.execute_call(_wait("1")))
        await mode.close()

    asyncio.run(run())


def test_termination_cancels_nested_work_and_discards_uncommitted_storage():
    async def run():
        router = Router()
        mode = CodeMode(router)
        first = await mode.execute_call(
            _exec(
                '// @exec: {"yield_time_ms": 10}\nstore("cancelled",true); await tools.block({});'
            )
        )
        assert "Script running" in _text(first)
        await asyncio.wait_for(router.started.wait(), 2)
        terminated = await mode.execute_call(_wait("1", terminate=True))
        assert "Script terminated" in _text(terminated)
        assert router.cancelled.is_set()
        assert "cancelled" not in mode.stored
        await mode.close()

    asyncio.run(run())


def test_notification_is_injected_while_cell_is_still_running():
    async def run():
        router = Router()
        delivered = asyncio.Event()

        def inject(item):
            router.extras.append(item)
            delivered.set()

        router.inject = inject
        mode = CodeMode(router)
        result = await mode.execute_call(
            _exec('notify("live"); yield_control(); await new Promise(()=>{});')
        )
        assert "Script running" in _text(result)
        await asyncio.wait_for(delivered.wait(), 2)
        assert router.extras[0]["output"] == "live"
        assert not mode.cells["1"].done
        await mode.close()

    asyncio.run(run())


def test_completion_cancels_unawaited_work_and_timers_do_not_keep_cell_alive():
    async def run():
        router = Router()
        mode = CodeMode(router)
        result = await mode.execute_call(
            _exec(
                'tools.block({}); setTimeout(()=>text("late"),10000); text("done"); store("complete",true);'
            )
        )
        assert "Script completed" in _text(result)
        assert "late" not in _text(result)
        assert mode.stored["complete"] is True
        assert not any(
            not task.done() for cell in mode.cells.values() for task in cell.nested
        )
        await mode.close()

    asyncio.run(run())


def test_cancellation_during_worker_startup_closes_child(monkeypatch):
    async def run():
        mode = CodeMode(Router())
        started = asyncio.Event()

        async def hold_startup(cell):
            started.set()
            await cell.process.wait()

        monkeypatch.setattr(mode, "_read", hold_startup)
        task = asyncio.create_task(mode.execute_call(_exec('text("unused")')))
        await asyncio.wait_for(started.wait(), 2)
        cell = mode.cells["1"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cell.process.returncode is not None
        assert cell.reader.done()
        assert not mode.cells
        await mode.close()

    asyncio.run(run())


def test_output_helpers_truncation_errors_exit_and_import_rejection():
    async def run():
        mode = CodeMode(Router())
        result = await mode.execute_call(
            _exec('// @exec: {"max_output_tokens": 4}\ntext("0123456789".repeat(5));')
        )
        assert "Warning: truncated output" in _text(result)
        image = await mode.execute_call(
            _exec(
                'image({type:"image",data:"AA==",mimeType:"image/png",_meta:{"codex/imageDetail":"original"}}); generatedImage({image_url:"data:image/png;base64,AA==",output_hint:"hint"}); audio({type:"audio",data:"AA==",mimeType:"audio/wav"});'
            )
        )
        assert image["output"][1] == {
            "type": "input_image",
            "image_url": "data:image/png;base64,AA==",
            "detail": "original",
        }
        assert image["output"][-1] == {
            "type": "input_audio",
            "audio_url": "data:audio/wav;base64,AA==",
        }
        rejected = await mode.execute_call(_exec('image("https://example.com/a.png")'))
        assert "remote image URLs are not supported" in _text(rejected)
        imported = await mode.execute_call(_exec('import fs from "node:fs";'))
        assert "Unsupported import in exec: node:fs" in _text(imported)
        exited = await mode.execute_call(
            _exec('text("before"); exit(); text("after");')
        )
        assert "Script completed" in _text(exited)
        assert "after" not in _text(exited)
        failed = await mode.execute_call(
            _exec('store("failure_write",true); throw "plain failure";')
        )
        assert "Script failed" in _text(failed)
        assert "plain failure" in _text(failed)
        assert mode.stored["failure_write"] is True
        await mode.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "source",
    [
        "",
        "// @exec: {}",
        "// @exec: []\ntext(1)",
        '// @exec: {"unknown":1}\ntext(1)',
        '// @exec: {"yield_time_ms":9007199254740992}\ntext(1)',
    ],
)
def test_exec_rejects_invalid_source_and_pragmas(source):
    with pytest.raises(ToolError):
        parse_exec_source(source)


def _stream(source, index):
    events = [
        {"type": "response.created", "response": {"id": f"resp_exec_{index}"}},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "id": f"ctc_exec_{index}",
                "call_id": f"call_exec_{index}",
                "name": "exec",
                "input": source,
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": f"resp_exec_{index}",
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


def test_code_mode_native_and_python_match_complete_local_task(
    parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        config_file.read_text()
        + "shell_snapshot=false\ncode_mode=true\ncode_mode_host=true\n"
    )
    task = tmp_path / "task"
    task.mkdir()
    (task / "probe.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
        )
    )
    sources = [
        'text([typeof process,typeof require,typeof console,typeof Atomics,typeof WebAssembly]); const result=await tools.shell_command({command:"printf CODE_MODE_TASK"}); text(result); store("evidence",{ok:result.includes("CODE_MODE_TASK")});',
        'text(load("evidence")); text(ALL_TOOLS.filter(tool=>tool.name === "shell_command")); text({value:42});',
        '// @exec: {"max_output_tokens":5}\ntext("0123456789".repeat(5));',
        'text("before_exit"); exit(); text("unreachable");',
        'text(await tools.apply_patch("*** Begin Patch\\n*** Add File: mode-created.txt\\n+CODE_MODE_PATCH\\n*** End Patch")); image(await tools.view_image({path:"probe.png"}));',
    ]
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            (task / "mode-created.txt").unlink(missing_ok=True)
            replay.reset(
                [(200, _stream(source, index)) for index, source in enumerate(sources)]
                + [(200, _events("CODE_MODE_VERIFIED"))]
            )
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 60,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Complete the supplied local task with Code Mode.", working_dir=task
                )
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors and not replay.steps
            assert result.output == "CODE_MODE_VERIFIED"
            assert (task / "mode-created.txt").read_text() == "CODE_MODE_PATCH\n"
            assert "CODE_MODE_TASK" in json.dumps(replay.requests[-1])
            observed.append(
                _normalize(
                    {
                        "requests": replay.requests,
                        "output": result.output,
                        "usage": dict(result.usage),
                    },
                    tmp_path,
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / f"code-mode-{label}.json").write_text(json.dumps(trace, indent=2))
    assert observed[0] == observed[1]


def test_code_mode_native_and_python_match_yield_wait_notify_cancel_and_errors(
    parity_source, upstream_codex, tmp_path
):
    config_file = parity_source / "config.toml"
    config_file.write_text(
        config_file.read_text()
        + "shell_snapshot=false\ncode_mode=true\ncode_mode_host=true\n"
    )
    task = tmp_path / "task"
    task.mkdir()
    steps = [
        _stream(
            'text("before_yield"); yield_control(); await new Promise(resolve=>setTimeout(resolve,250)); text("after_wait"); store("completed",true);',
            1,
        ),
        _events(call=("wait", {"cell_id": "1"}), response_id="resp_wait_1"),
        _events(call=("wait", {"cell_id": "1"}), response_id="resp_wait_missing"),
        _stream(
            'store("cancelled",true); text("before_cancel"); yield_control(); await new Promise(()=>{});',
            2,
        ),
        _events(
            call=("wait", {"cell_id": "2", "terminate": True}),
            response_id="resp_terminate",
        ),
        _stream(
            'text([load("completed"),load("cancelled")]); store("failed_write",true); throw "native script failure";',
            3,
        ),
        _stream(
            'text(load("failed_write")); try { image("https://example.com/a.png"); } catch(e) { text(e); } try { await tools.shell_command("wrong"); } catch(e) { text(e); } notify("CODE_MODE_NOTICE");',
            4,
        ),
        _stream(
            'try { exit(); } catch(e) { text(e); } text("caught_exit_continues");', 5
        ),
        _stream('throw new Error("native stack failure");', 6),
        _stream("const cycle={}; cycle.self=cycle; text(cycle);", 7),
        _events("CODE_MODE_LIFECYCLE_VERIFIED"),
    ]
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, step) for step in steps])
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "timeout": 60,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run(
                    "Check Code Mode cell lifecycle and helper failures.",
                    working_dir=task,
                )
            )
            assert result.status == "finished", result.error_message
            assert result.output == "CODE_MODE_LIFECYCLE_VERIFIED"
            assert not replay.errors and not replay.steps
            history = json.dumps(replay.requests[-1])
            for evidence in (
                "CODE_MODE_NOTICE",
                "Script terminated",
                "after_wait",
                "native script failure",
                "native stack failure",
            ):
                assert evidence in history
            observed.append(
                _normalize(
                    {
                        "requests": replay.requests,
                        "output": result.output,
                        "usage": dict(result.usage),
                    },
                    tmp_path,
                )
            )
    for label, trace in zip(("native", "python"), observed, strict=True):
        (tmp_path / f"code-mode-lifecycle-{label}.json").write_text(
            json.dumps(trace, indent=2)
        )
    assert observed[0] == observed[1]
