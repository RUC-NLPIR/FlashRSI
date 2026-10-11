"""Native SDK/process editing and usage through runner, using local model servers."""
# ruff: noqa: F811

import asyncio
import json

import pytest

from flashrsi import runner
from flashrsi.agents import ClaudeCode
from flashrsi.algorithms.rrsi import _tokens as tokens
from flashrsi.config import load_config
from flashrsi.core import Snapshot

pytest.importorskip("openai")
pytest.importorskip("claude_agent_sdk")

from test_claude_code_native import (  # noqa: E402, F401
    _config,
    _message_events,
    anthropic_server,
)
from test_miniagent import _chat_reply, model_server  # noqa: E402, F401


def test_native_subagent_tokens_include_delegated_work(anthropic_server):
    def reply(request):
        body = request["body"]
        encoded = json.dumps(body["messages"])
        message_id = f"msg_{len(anthropic_server.requests)}"
        if "ROOT_RRSI_ACCOUNTING" in encoded:
            if "tool_use" not in encoded:
                return _message_events(
                    body,
                    tool=(
                        "Agent",
                        {
                            "description": "Check evidence",
                            "prompt": "CHILD_RRSI_ACCOUNTING",
                            "subagent_type": "general-purpose",
                            "run_in_background": False,
                        },
                    ),
                    message_id=message_id,
                )
            assert "CHILD_EVIDENCE_CHECKED" in encoded
            return _message_events(body, "Paris", message_id=message_id)
        assert "CHILD_RRSI_ACCOUNTING" in encoded
        return _message_events(body, "CHILD_EVIDENCE_CHECKED", message_id=message_id)

    anthropic_server.reply = reply
    trajectory = asyncio.run(
        ClaudeCode(
            _config(
                anthropic_server,
                tools=["Agent"],
                allowed_tools=["Agent"],
                max_turns=4,
            )
        ).run("ROOT_RRSI_ACCOUNTING: Delegate an evidence check, then answer")
    )
    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Paris"
    assert len(anthropic_server.requests) == 3
    # Each local model response reports 20 input and 3 output tokens.
    assert tokens(trajectory.usage) == 69
    assert trajectory.usage["input_tokens"] + trajectory.usage["output_tokens"] == 46


@pytest.mark.parametrize("harness", ["miniagent", "claude_code"])
def test_runner_edits_native_harness_and_freezes_test(
    harness, model_server, anthropic_server, tmp_path
):
    worker_requests = []
    trace_tasks = []
    writes = []
    path = "skills/main.md" if harness == "miniagent" else "CLAUDE.md"
    solution = "SOLVED_NATIVE: inspect supplied evidence before answering.\n"

    def reply(request):
        body = request["body"]
        messages = body["messages"]
        if body["model"] != "local-worker":
            answer = "Paris" if "SOLVED_NATIVE" in json.dumps(messages) else "Rome"
            return 200, _chat_reply(body, answer)
        worker_requests.append(body)
        prompt = next(
            message["content"] for message in messages if message["role"] == "user"
        )
        if prompt.startswith("[RRSI: analyze]"):
            tasks = json.loads(prompt.split("first): ")[1].split("\nPrior")[0])
            trace_tasks[:] = [task["task_id"] for task in tasks]
            action = (
                {
                    "action": "digest_many",
                    "requests": [{"task_id": trace_tasks[0], "lens": "failure"}],
                }
                if "Interaction log: []" in prompt
                else {
                    "action": "report",
                    "failure_modes": [
                        {
                            "mode": "evidence_check",
                            "description": "Inspect supplied evidence",
                            "n_tasks": len(tasks),
                        }
                    ],
                    "capability_gaps": [],
                    "success_habits": [],
                }
            )
            return 200, _chat_reply(body, f"<ANALYSIS>{json.dumps(action)}</ANALYSIS>")
        if prompt.startswith("[RRSI: digest]"):
            if not any(message["role"] == "tool" for message in messages):
                return 200, _chat_reply(
                    body, tool=("read_file", {"path": "trace.json"})
                )
            # The real file tool must expose the selected graded incumbent trial.
            assert "Rome" in json.dumps(messages)
            digest = {
                "task_id": trace_tasks[0],
                "lens": "failure",
                "blocker": "Ignored evidence",
                "narrative": "Evidence was supplied",
                "evidence": [{"where": "trajectory.output", "quote": "Rome"}],
                "verifier_evidence": "Answer was incorrect",
                "needed_instead": "Read evidence",
            }
            return 200, _chat_reply(body, f"<DIGEST>{json.dumps(digest)}</DIGEST>")
        if prompt.startswith("[RRSI: critic]"):
            assert solution.strip() in prompt
            return 200, _chat_reply(
                body, '<REVIEW>{"verdict":"accept","reasons":[]}</REVIEW>'
            )
        assert prompt.startswith("[RRSI: propose]")
        if not any(message["role"] == "tool" for message in messages):
            writes.append(path)
            return 200, _chat_reply(
                body, tool=("write_file", {"path": path, "content": solution})
            )
        edits = {
            "edits": [
                {
                    "component": "skill" if harness == "miniagent" else "prompt",
                    "id": "C1",
                    "hypothesis": "Reusable evidence checking.",
                    "targets_mode": "evidence_check",
                    "predicted_affected": [trace_tasks[0]],
                    "retroactive_check": "Would have read the provided evidence.",
                    "paths": [path],
                }
            ]
        }
        return 200, _chat_reply(body, f"<EDITS>{json.dumps(edits)}</EDITS>")

    def claude_reply(request):
        body = request["body"]
        answer = "Paris" if "SOLVED_NATIVE" in json.dumps(body) else "Rome"
        return _message_events(
            body, answer, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    model_server.reply = reply
    anthropic_server.reply = claude_reply
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": f"task-{i}",
                    "question": f"Question {i}: capital?",
                    "context": "Paris.",
                    "answers": ["Paris"],
                }
                for i in range(5)
            ]
        )
    )
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "benchmark": {
                "name": "searchqa",
                "data_path": str(data),
                "seed": 42,
                "split": "auto",
            },
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
                "max_turns": 5,
            },
            "algorithm": {
                "name": "rrsi",
                "T": 1,
                "k": 2,
                "m": 1,
                "delta": None,
                "repair_rounds": 0,
                "worker": {
                    "type": "agent",
                    "name": "miniagent",
                    "llm": {
                        "model_name": "local-worker",
                        "api_key": "local-worker-secret",
                        "base_url": model_server.base_url,
                    },
                    "timeout": 30,
                    "max_turns": 6,
                },
            },
        }
    )
    run_dir, result = asyncio.run(runner._run(config))
    assert result["test_score"] == 1.0 and result["test_tasks"] == 1
    assert writes == [path]
    final = Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    assert final.files[path].content.decode() == solution
    assert not any(path.startswith("rrsi-evidence-") for path in final.files)
    assert not list((run_dir / "working").iterdir())
    assert len(list((run_dir / "trajectories").glob("*-test.json"))) == 1
    baseline, candidate = [
        json.loads(p.read_text())
        for p in sorted((run_dir / "trajectories").glob("*-measurement.json"))
    ]
    assert baseline["score"] == 0 and candidate["score"] == 1
    assert baseline["cost"] > 0 and candidate["cost"] > 0
    assert load_config(run_dir / "config.yaml").algorithm.name == "rrsi"
    assert all(
        "Question" not in request["messages"][0]["content"]
        for request in worker_requests
    )
    text = "".join(p.read_text() for p in run_dir.rglob("*") if p.is_file())
    assert "local-target-secret" not in text and "local-worker-secret" not in text
