import asyncio
import hashlib
import json

import pytest

from flashrsi.agents import LLM
from flashrsi.core import Trajectory
from scripts._protocol_safe_worker import ProtocolSafeLLM
from scripts.summarize_searchqa_experiment import _cache_usage

PROMPT = "[SkillOpt: failure]\nSame original input"
VALID = '{"reasoning":"general guidance", "edits":[]}'


def _worker(tmp_path):
    return ProtocolSafeLLM({"llm": {"model_name": "offline"}}).configure_experiment(
        tmp_path / "cache"
    )


def _hashes(tmp_path):
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (tmp_path / "cache/worker").rglob("*.json")
    }


def test_retries_same_prompt_preserves_cache_ordinals_and_replays(
    tmp_path, monkeypatch
):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(
            output='{"reasoning": "broken")}' if len(calls) == 1 else VALID,
            messages=({"type": "RunInput", "prompt": prompt},),
            usage={"prompt_tokens": 11, "completion_tokens": 7},
        )

    monkeypatch.setattr(LLM, "_run", fake)
    worker = _worker(tmp_path)
    result = asyncio.run(worker.run(PROMPT))
    assert result.output == VALID
    assert calls == [PROMPT, PROMPT]
    assert worker._experiment_worker_ordinal == 1
    assert result.messages[-1]["type"] == "ProtocolRecovery"
    original = next((tmp_path / "cache/worker").rglob("*.json"))
    assert json.loads(original.read_text())["trajectory"]["output"] != VALID
    hashes = _hashes(tmp_path)
    replay = asyncio.run(_worker(tmp_path).run(PROMPT))
    assert replay == result
    assert calls == [PROMPT, PROMPT]
    assert _hashes(tmp_path) == hashes
    assert _cache_usage(tmp_path)["worker_protocol_retry"] == {
        "finished_requests": 1,
        "input_tokens": 11,
        "output_tokens": 7,
        "failed_attempt_records": 0,
    }


def test_exhaustion_is_bounded_across_restarts(tmp_path, monkeypatch):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(output="invalid JSON")

    monkeypatch.setattr(LLM, "_run", fake)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="exhausted after 2 attempts"):
            asyncio.run(_worker(tmp_path).run(PROMPT))
    assert calls == [PROMPT] * 3
    assert len(list((tmp_path / "cache/protocol_retries").rglob("*.json"))) == 2


def test_parallel_retry_does_not_consume_sibling_ordinal(tmp_path, monkeypatch):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        await asyncio.sleep(0.001)
        return Trajectory(output="bad" if calls.count(prompt) == 1 else VALID)

    monkeypatch.setattr(LLM, "_run", fake)

    async def run():
        worker = _worker(tmp_path)
        rows = await asyncio.gather(worker.run(PROMPT), worker.run(PROMPT + " 2"))
        assert worker._experiment_worker_ordinal == 2
        return rows

    result = asyncio.run(run())
    assert [row.messages[-1]["run_ordinal"] for row in result] == [0, 1]
    assert len(calls) == 4
    assert asyncio.run(run()) == result
    assert len(calls) == 4


@pytest.mark.parametrize(
    "prompt, output",
    [(PROMPT, VALID), ("[SkillOpt: slow]", "malformed"), ("[SkillOpt: meta]", "bad")],
)
def test_valid_calls_and_sequential_rejection_remain_unchanged(
    tmp_path, monkeypatch, prompt, output
):
    calls = []

    async def fake(self, prompt, working_dir=None):
        calls.append(prompt)
        return Trajectory(output=output)

    monkeypatch.setattr(LLM, "_run", fake)
    assert asyncio.run(_worker(tmp_path).run(prompt)).output == output
    assert calls == [prompt]
    assert not (tmp_path / "cache/protocol_retries").exists()


def test_retry_errors_preserve_evidence_then_use_remaining_attempt(
    tmp_path, monkeypatch
):
    outputs = iter(
        [
            Trajectory(output="bad"),
            Trajectory(status="error", error_message="HTTP 502"),
            Trajectory(output=VALID),
        ]
    )

    async def fake(self, prompt, working_dir=None):
        return next(outputs)

    monkeypatch.setattr(LLM, "_run", fake)
    row = asyncio.run(_worker(tmp_path).run(PROMPT))
    assert row.messages[-1]["completed_retries"] == 2
    assert (
        _cache_usage(tmp_path)["worker_protocol_retry"]["failed_attempt_records"] == 1
    )
