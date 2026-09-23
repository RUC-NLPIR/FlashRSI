"""Run ACE through runner, real harnesses and local model protocol servers."""
# ruff: noqa: F811

import asyncio
import json

import pytest

from flashrsi import runner
from flashrsi.config import load_config
from flashrsi.core import Snapshot

pytest.importorskip("openai")
pytest.importorskip("claude_agent_sdk")

from test_claude_code_native import (  # noqa: E402, F401
    _message_events,
    anthropic_server,
)
from test_miniagent import _chat_reply, model_server  # noqa: E402, F401


@pytest.mark.parametrize("harness", ["miniagent", "claude_code"])
def test_runner_native_playbook_loading(
    harness, model_server, anthropic_server, tmp_path
):
    run_dir, result = _run_ace(harness, model_server, anthropic_server, tmp_path)
    assert result["test_score"] == 1.0
    assert result["test_tasks"] == 1
    final = Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    path = "prompts/system.md" if harness == "miniagent" else "CLAUDE.md"
    assert b"SOLVED_NATIVE" in final.files[path].content
    validations = [
        json.loads(p.read_text())
        for p in sorted((run_dir / "trajectories").glob("*-validation.json"))
    ]
    metric = result["primary_metric"]
    assert [row["trajectories"][0]["metrics"][metric] for row in validations] == [
        0.0,
        1.0,
    ]
    assert (run_dir / "end-summary.json").is_file()
    assert load_config(run_dir / "config.yaml").algorithm.eval_steps == 100
    worker_requests = [
        r for r in model_server.requests if r["body"]["model"] == "local-worker"
    ]
    assert len(worker_requests) == 2
    assert not model_server.errors and not anthropic_server.errors
    assert not list((run_dir / "working").iterdir())
    records = "".join(p.read_text() for p in run_dir.rglob("*") if p.is_file())
    assert "local-target-secret" not in records and "local-worker-secret" not in records


def test_runner_online_stream_scores_before_the_final_test(
    model_server, anthropic_server, tmp_path
):
    """Online grows the same playbook, without ever touching the dev split."""
    run_dir, result = _run_ace(
        "miniagent", model_server, anthropic_server, tmp_path, mode="online"
    )
    final = Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    assert b"SOLVED_NATIVE" in final.files["prompts/system.md"].content
    assert not list((run_dir / "trajectories").glob("*-validation.json"))
    (stream,) = [
        row
        for path in sorted((run_dir / "trajectories").glob("*-decision.json"))
        if (row := json.loads(path.read_text()))["kind"] == "stream"
    ]
    # The stream scored the one task it saw on the seed playbook; the runner's
    # test then measures the grown one. Two different numbers, both reported.
    assert (stream["online_score"], stream["online_tasks"]) == (0.0, 1)
    assert result["test_score"] == 1.0
    assert load_config(run_dir / "config.yaml").algorithm.mode == "online"


def _run_ace(harness, model_server, anthropic_server, tmp_path, **algorithm):
    def reply(request):
        body = request["body"]
        if body["model"] == "local-worker":
            prompt = json.dumps(body["messages"])
            text = (
                json.dumps(
                    {
                        "operations": [
                            {
                                "type": "ADD",
                                "section": "general",
                                "content": "SOLVED_NATIVE: verify the supplied evidence.",
                            }
                        ]
                    }
                )
                if "[ACE: curate]" in prompt
                else "Use evidence to verify the answer."
            )
        else:
            text = (
                "Paris" if "SOLVED_NATIVE" in json.dumps(body["messages"]) else "Rome"
            )
        return 200, _chat_reply(body, text)

    def claude_reply(request):
        body = request["body"]
        # Only the actual loaded system instructions can earn the score.
        text = "Paris" if "SOLVED_NATIVE" in json.dumps(body.get("system")) else "Rome"
        return _message_events(
            body, text, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    model_server.reply = reply
    anthropic_server.reply = claude_reply
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": str(i),
                    "question": "Capital of France?",
                    "context": "Paris is the capital of France.",
                    "answers": ["Paris"],
                }
                for i in range(3)
            ]
        )
    )
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "benchmark": {"name": "searchqa", "data_path": str(data), "split": "auto"},
            "agent": {
                "name": harness,
                "llm": {
                    "model_name": "local-target"
                    if harness == "miniagent"
                    else "claude-sonnet-4-6",
                    "api_key": "local-target-secret",
                    "base_url": model_server.base_url
                    if harness == "miniagent"
                    else anthropic_server.base_url,
                },
                "tools": [],
                "timeout": 30,
                "max_turns": 1,
            },
            "algorithm": {
                "name": "ace",
                "max_steps": 1,
                "max_reflection_rounds": 1,
                **algorithm,
                "worker": {
                    "type": "llm",
                    "llm": {
                        "model_name": "local-worker",
                        "api_key": "local-worker-secret",
                        "base_url": model_server.base_url,
                    },
                },
            },
        }
    )
    return asyncio.run(runner._run(config))
