"""Responses Lite request parity with the pinned CLI, using localhost only."""

import asyncio
import json

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-sol"])
def test_lite_complete_request_matches_native(
    model, parity_source, upstream_codex, tmp_path
):
    observed = []
    with _responses_server() as replay:
        for binary in (upstream_codex, None):
            replay.reset([(200, _events("LITE_READY"))])
            config = {
                "source_dir": parity_source,
                "llm": {
                    "model_name": model,
                    "api_key": "local-key",
                    "base_url": replay.base_url,
                },
                "sandbox": "danger-full-access",
                "timeout": 30,
            }
            if binary:
                config["cli_path"] = binary
            result = asyncio.run(
                Codex(config).run("Check your tools, then report ready.")
            )
            assert result.status == "finished", result.error_message
            assert result.output == "LITE_READY"
            assert len(replay.requests) == 1 and not replay.steps and not replay.errors
            observed.append(_normalize(replay.requests, tmp_path))
            (tmp_path / ("native.json" if binary else "python.json")).write_text(
                json.dumps(observed[-1], indent=2, ensure_ascii=False)
            )
    assert observed[0] == observed[1]
