"""Full SkillOpt loops use actual harnesses and SDKs against localhost only."""
# ruff: noqa: F811

import asyncio
import json

import pytest

from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import SkillOpt
from flashrsi.benchmarks import SearchQA

pytest.importorskip("openai")
pytest.importorskip("claude_agent_sdk")

# Reuse the protocol servers already used to verify these native adapters.
from test_claude_code_native import (  # noqa: E402, F401
    _message_events,
    anthropic_server,
)
from test_miniagent import _chat_reply, model_server  # noqa: E402, F401


def benchmark(tmp_path):
    data = tmp_path / "qa.json"
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
    return SearchQA({"data_path": str(data), "split": "auto"})


def proposal(path):
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "op": "append",
                    "content": "---\nname: evidence\ndescription: Apply evidence checks to factual questions.\n---\nUse the supplied evidence to verify the answer. SOLVED_NATIVE",
                }
            ]
        }
    )


def test_miniagent_and_llm_worker_complete_native_loop(model_server, tmp_path):
    def reply(request):
        body = request["body"]
        if body["model"] == "local-worker":
            text = proposal("skills/main.md")
        else:
            text = (
                "Paris" if "SOLVED_NATIVE" in json.dumps(body["messages"]) else "Rome"
            )
        return 200, _chat_reply(body, text)

    model_server.reply = reply
    target = MiniAgent(
        {
            "llm": {
                "model_name": "local-target",
                "api_key": "local-key",
                "base_url": model_server.base_url,
            },
            "timeout": 30,
            "max_turns": 1,
        }
    )
    worker = LLM(
        {
            "llm": {
                "model_name": "local-worker",
                "api_key": "local-key",
                "base_url": model_server.base_url,
            }
        }
    )
    baseline = target.snapshot
    algo = SkillOpt(
        {"num_epochs": 1}, target=target, worker=worker, benchmark=benchmark(tmp_path)
    )
    final = asyncio.run(algo.evolve())
    assert final.id != baseline.id
    assert final.parent_id == baseline.id
    assert b"SOLVED_NATIVE" in final.files["skills/main.md"].content
    assert (
        len([r for r in model_server.requests if r["body"]["model"] == "local-worker"])
        == 1
    )


def test_claude_target_and_agent_worker_create_native_skill(anthropic_server, tmp_path):
    def reply(request):
        body = request["body"]
        serialized = json.dumps(body["messages"])
        worker_prompt = any(
            isinstance(m.get("content"), str)
            and m["content"].startswith("[SkillOpt:")
            or isinstance(m.get("content"), list)
            and any(
                isinstance(block, dict)
                and block.get("type") == "text"
                and "[SkillOpt: failure]" in block.get("text", "")
                for block in m["content"]
            )
            for m in body["messages"]
        )
        tool = None
        if (
            not worker_prompt
            and "SOLVED_NATIVE" not in serialized
            and "flashrsi:evidence" in json.dumps(body)
        ):
            tool = ("Skill", {"skill": "flashrsi:evidence"})
        text = (
            proposal("skills/evidence/SKILL.md")
            if worker_prompt
            else "Paris"
            if "SOLVED_NATIVE" in serialized
            else "Rome"
        )
        return _message_events(
            body, text, tool=tool, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    anthropic_server.reply = reply
    config = {
        "llm": {
            "model_name": "claude-sonnet-4-6",
            "api_key": "local-key",
            "base_url": anthropic_server.base_url,
        },
        "tools": ["Skill"],
        "timeout": 30,
    }
    target, worker = ClaudeCode(config), ClaudeCode(config)
    baseline, worker_baseline = target.snapshot, worker.snapshot
    algo = SkillOpt(
        {"num_epochs": 1}, target=target, worker=worker, benchmark=benchmark(tmp_path)
    )
    final = asyncio.run(algo.evolve())
    assert final.id != baseline.id
    assert b"SOLVED_NATIVE" in final.files["skills/evidence/SKILL.md"].content
    assert worker.snapshot.id == worker_baseline.id
    assert any(
        "SOLVED_NATIVE" in json.dumps(r["body"]) for r in anthropic_server.requests
    )
