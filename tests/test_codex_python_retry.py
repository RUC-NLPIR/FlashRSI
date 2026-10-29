"""A sampling request has one stream retry budget across partial/empty failures."""

import asyncio

from codex_test_support import _events, _responses_server
from codex_test_support import parity_source as parity_source
from codex_test_support import upstream_codex as upstream_codex

from flashrsi.agents import Codex


def _failed_stream(response_id, *, call=None):
    if call:
        prefix = _events(call=call, response_id=response_id).split(
            b"event: response.completed", 1
        )[0]
    else:
        prefix = b""
    return (
        prefix
        + b'data: {"type":"response.failed","response":{"error":{"code":"server_error","message":"shared retry budget exhausted"}}}\n\n'
    )


def test_native_shared_retry_budget_across_partial_empty_partial(
    parity_source, upstream_codex, tmp_path, monkeypatch
):
    import flashrsi.agents.codex as codex_module

    original = codex_module._settings

    def settings(*args, **kwargs):
        overrides, environment, native = original(*args, **kwargs)
        overrides["model_providers.flashrsi.request_max_retries"] = 0
        overrides["model_providers.flashrsi.stream_max_retries"] = 2
        return overrides, environment, native

    monkeypatch.setattr(codex_module, "_settings", settings)
    task = tmp_path / "task"
    task.mkdir()
    with _responses_server() as replay:
        for binary in (None,):
            counter = task / "counter"
            counter.unlink(missing_ok=True)
            call = ("shell_command", {"command": "printf x >> counter"})
            replay.reset(
                [
                    (200, _failed_stream("resp_partial_1", call=call)),
                    (200, _failed_stream("resp_empty_2")),
                    (200, _failed_stream("resp_partial_3", call=call)),
                    (200, _events()),
                ]
            )
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "test",
                    "base_url": replay.base_url,
                },
                "sandbox": "danger-full-access",
                "timeout": 20,
            }
            result = asyncio.run(
                Codex(config).run("Consume one shared retry budget.", working_dir=task)
            )
            assert result.status == "error", result.output
            assert "shared retry budget exhausted" in result.error_message
            assert len(replay.requests) == 3, result.error_message
            assert len(replay.steps) == 1 and not replay.errors
            assert counter.read_text() == "xx"
