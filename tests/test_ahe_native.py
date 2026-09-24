"""Run AHE through runner with a real Agent Worker editing a real checkout.

Every other algorithm's Worker only produces text, so the algorithm writes the
files itself. AHE hands over the directory, which means a real harness process
runs its own file tools inside a real checkout and the commit has to survive
whatever that process leaves behind. That is the risk this file covers.
"""
# ruff: noqa: F811

import asyncio
import json

import pytest

from flashrsi import runner
from flashrsi.config import load_config
from flashrsi.core import Snapshot

pytest.importorskip("openai")

from test_miniagent import _chat_reply, model_server  # noqa: E402, F401

_SOLUTION = "SOLVED_NATIVE: the context names the capital; answer with it.\n"


def _manifest(prompt):
    """Declare a fix for the tasks the evidence actually named.

    A real Evolve Agent reads the task IDs out of the evidence it is shown, and
    so does this one -- the split decides which IDs exist, and a manifest that
    named the wrong one would be judged INEFFECTIVE for that reason alone.
    """
    evidence = json.loads(
        prompt[prompt.index("LAYERED EVIDENCE:\n") :].split("\n", 1)[1]
    )
    return {
        "failure_evidence": ["every train task answered Rome"],
        "root_cause": "the harness never tells the agent to read the supplied context",
        "targeted_fix": "add a skill that reads the context before answering",
        "changes": [
            {
                "path": "skills/main.md",
                "fix_tasks": evidence[0]["failures"],
                "risk_tasks": [],
            }
        ],
    }


def test_runner_edits_the_harness_through_a_real_agent_worker(model_server, tmp_path):
    run_dir, result = _run_ahe(model_server, tmp_path)

    # The edit reached the target: it scored 0 before and answers correctly now.
    assert result["test_score"] == 1.0
    final = Snapshot.load(run_dir / "snapshots" / f"{result['snapshot_id']}.json")
    assert final.files["skills/main.md"].content.decode() == _SOLUTION
    assert final.parent_id is not None

    (decision,) = [
        row
        for path in sorted((run_dir / "trajectories").glob("*-decision.json"))
        if (row := json.loads(path.read_text()))["kind"] == "keep"
    ]
    assert decision["accepted"] is True
    assert decision["parent_score"] == 0.0 and decision["candidate_score"] == 1.0
    assert decision["changes"][0]["verdict"] == "EFFECTIVE"
    assert decision["changes"][0]["path"] == "skills/main.md"
    # Every train task the edit was measured on flipped, and the manifest had
    # named each of them.
    assert {row["flip"] for row in decision["tasks"].values()} == {"fail_to_pass"}
    assert decision["changes"][0]["actually_fixed"] == sorted(decision["tasks"])
    assert decision["unattributed_regressions"] == []

    # The Worker ran as a separate role, against its own model and credentials.
    worker_requests = [
        r for r in model_server.requests if r["body"]["model"] == "local-worker"
    ]
    assert worker_requests and not model_server.errors
    assert load_config(run_dir / "config.yaml").algorithm.max_steps == 1
    # The checkout is cleaned up, and nothing leaked into the saved records.
    assert not list((run_dir / "working").iterdir())
    records = "".join(p.read_text() for p in run_dir.rglob("*") if p.is_file())
    assert "local-target-secret" not in records
    assert "local-worker-secret" not in records


def test_a_text_worker_is_refused_before_the_experiment_directory_exists(
    model_server, tmp_path
):
    """The unsupported combination is reported at startup, as mvp_doc requires."""
    with pytest.raises(ValueError, match="worker.type"):
        _run_ahe(model_server, tmp_path, worker={"type": "llm", "name": None})

    assert not (tmp_path / "runs").exists()
    assert model_server.requests == []


def _run_ahe(model_server, tmp_path, *, worker=None, **algorithm):
    def reply(request):
        body = request["body"]
        if body["model"] != "local-worker":
            # Only the harness the target actually loaded can earn the score.
            text = (
                "Paris" if "SOLVED_NATIVE" in json.dumps(body["messages"]) else "Rome"
            )
            return 200, _chat_reply(body, text)

        history = json.dumps(body["messages"])
        # The algorithm's prompt is the user turn; the rest is MiniAgent's own
        # conversation with itself.
        instruction = next(
            message["content"]
            for message in body["messages"]
            if message["role"] == "user"
        )
        if "[AHE: evolve]" not in instruction:
            return 200, _chat_reply(body, "The agent never read the context.")
        # The Worker edits through its own native file tool, then declares what
        # it did. The tool *result* is the signal that the write landed: the
        # request itself is echoed back in the history, and "write_file" is in
        # the editing system prompt from the very first call. The manifest is
        # then checked against the real diff, not against this text.
        if '"role": "tool"' in history:
            return 200, _chat_reply(
                body,
                f"Edited.\n<MANIFEST>{json.dumps(_manifest(instruction))}</MANIFEST>",
            )
        return 200, _chat_reply(
            body,
            "",
            tool=("write_file", {"path": "skills/main.md", "content": _SOLUTION}),
        )

    model_server.reply = reply
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
    role = {
        "type": "agent",
        "name": "miniagent",
        "llm": {
            "model_name": "local-worker",
            "api_key": "local-worker-secret",
            "base_url": model_server.base_url,
        },
        "timeout": 30,
        "max_turns": 3,
        "tools": [],
        **(worker or {}),
    }
    config = load_config(
        overrides={
            "run": {"output_dir": str(tmp_path / "runs")},
            "benchmark": {"name": "searchqa", "data_path": str(data), "split": "auto"},
            "agent": {
                "name": "miniagent",
                "llm": {
                    "model_name": "local-target",
                    "api_key": "local-target-secret",
                    "base_url": model_server.base_url,
                },
                "tools": [],
                "timeout": 30,
                "max_turns": 1,
            },
            "algorithm": {
                "name": "ahe",
                "max_steps": 1,
                "use_debugger": False,
                **algorithm,
                "worker": role,
            },
        }
    )
    return asyncio.run(runner._run(config))
