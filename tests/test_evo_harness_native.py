"""Native file-editing Worker and solver skill loading over local protocols."""
# ruff: noqa: F811

import asyncio
import json

import pytest

from flashrsi import runner
from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.config import load_config
from flashrsi.core import Snapshot, Task

pytest.importorskip("openai")
pytest.importorskip("claude_agent_sdk")

from test_claude_code_native import (  # noqa: E402, F401
    _message_events,
    anthropic_server,
)
from test_evo_harness import MEMORY, PATH, skill  # noqa: E402
from test_miniagent import _chat_reply, model_server  # noqa: E402, F401


@pytest.mark.parametrize("harness", ["miniagent", "claude_code"])
def test_runner_compiles_portable_native_skill(
    harness, model_server, anthropic_server, tmp_path
):
    learned = False
    worker_requests = []
    initial_solver_requests = []

    def reply(request):
        nonlocal learned
        body = request["body"]
        messages = body["messages"]
        if body["model"] == "local-worker":
            worker_requests.append(body)
            prompt = next(m["content"] for m in messages if m["role"] == "user")
            if prompt.startswith("[EvoHarness: reflect]"):
                return 200, _chat_reply(body, MEMORY)
            assert "[EvoHarness: compile" in prompt
            if "[EvoHarness: compile general]" in prompt:
                return 200, _chat_reply(body, "No supported cross-task lesson.")
            memories = json.loads(
                prompt.split("Candidate memories from this batch:\n")[1]
            )
            writes = [
                (
                    PATH,
                    skill(
                        "SOLVED_NATIVE: verify the evidence.",
                        sources=(memories[0]["task_id"],),
                    ),
                )
            ]
            count = sum(m["role"] == "tool" for m in messages)
            if count < len(writes):
                path, content = writes[count]
                return 200, _chat_reply(
                    body, tool=("write_file", {"path": path, "content": content})
                )
            learned = True
            return 200, _chat_reply(body, "Compiled the native skill.")
        tools = [m for m in messages if m["role"] == "tool"]
        if not tools:
            initial_solver_requests.append(body)
            assert "SOLVED_NATIVE" not in json.dumps(messages)
        if "Available skill: verify" not in messages[0]["content"]:
            return 200, _chat_reply(body, "Rome")
        if not tools:
            return 200, _chat_reply(body, tool=("read_skill", {"skill": "verify"}))
        assert "SOLVED_NATIVE" in tools[-1]["content"]
        assert "source_task_ids" not in tools[-1]["content"]
        return 200, _chat_reply(body, "Paris")

    def claude_reply(request):
        body = request["body"]
        messages = json.dumps(body["messages"])
        if not learned:
            text, tool = "Rome", None
        elif "SOLVED_NATIVE" in messages:
            text, tool = "Paris", None
        else:
            text, tool = "", ("Skill", {"skill": "flashrsi:verify"})
        return _message_events(
            body, text, tool=tool, message_id=f"msg_{len(anthropic_server.requests)}"
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
                    "context": "Paris.",
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
                "tools": ["Skill"] if harness == "claude_code" else [],
                "timeout": 30,
                "max_turns": 5,
            },
            "algorithm": {
                "name": "evo_harness",
                "max_steps": 1,
                "worker": {
                    "type": "agent",
                    "name": "miniagent",
                    "llm": {
                        "model_name": "local-worker",
                        "api_key": "local-worker-secret",
                        "base_url": model_server.base_url,
                    },
                    "max_turns": 6,
                    "timeout": 30,
                },
            },
        }
    )
    run_dir, result = asyncio.run(runner._run(config))
    assert result["test_score"] == 1.0 and result["test_tasks"] == 1
    final = Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    assert b"SOLVED_NATIVE" in final.files[PATH].content
    path = "prompts/system.md" if harness == "miniagent" else "CLAUDE.md"
    if path in final.files:
        assert b"SOLVED_NATIVE" not in final.files[path].content
    assert not list((run_dir / "trajectories").glob("*-selection.json"))
    assert not list((run_dir / "trajectories").glob("*-validation.json"))
    decisions = [
        json.loads(p.read_text())
        for p in (run_dir / "trajectories").glob("*-decision.json")
    ]
    stream = next(row for row in decisions if row["kind"] == "stream")
    assert stream["online_score"] == 0.0 and stream["online_tasks"] == 1
    (test_record,) = [
        json.loads(p.read_text())
        for p in (run_dir / "trajectories").glob("*-test.json")
    ]
    assert test_record["snapshot_id"] == final.id
    calls = len(worker_requests)
    restored = (MiniAgent if harness == "miniagent" else ClaudeCode)(config.agent)
    restored.update(final)
    (ordinary,) = asyncio.run(
        restored.rollout([Task("held-out", "Capital of France? Evidence: Paris.")])
    )
    assert ordinary.status == "finished", ordinary.error_message
    assert ordinary.output == "Paris"
    assert len(worker_requests) == calls
    if harness == "miniagent":
        assert len(initial_solver_requests) == 3
    assert (run_dir / "end-summary.json").is_file()
    assert not model_server.errors and not anthropic_server.errors
    assert not list((run_dir / "working").iterdir())
    records = "".join(p.read_text() for p in run_dir.rglob("*") if p.is_file())
    assert "local-target-secret" not in records and "local-worker-secret" not in records
