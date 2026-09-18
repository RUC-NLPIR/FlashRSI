"""Live Claude Code smoke test; makes model calls using native authentication.

uv run --extra claude-code python examples/claude_code.py --model YOUR_MODEL
This example explicitly selects llm.auth: login and uses the local Claude login.
For API authentication, set llm.api_key (or auth_token/oauth_token) in config.
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.config import load_config, prepare_run_dir
from flashrsi.core import Task


def _json_default(value):
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


async def main(model, *, timeout=180, max_turns=10, max_budget_usd=1.0):
    config = load_config(
        overrides={
            "agent": {
                "name": "claude_code",
                "llm": {"model_name": model, "auth": "login"},
                "timeout": timeout,
                "max_turns": max_turns,
                "max_budget_usd": max_budget_usd,
            },
            "algorithm": {
                "name": "smoke",
                "worker": {"llm": {"model_name": model}},
            },
            "benchmark": {"name": "local"},
        }
    )
    run_dir = prepare_run_dir(config)
    print(f"Artifacts: {run_dir}", flush=True)

    def save(name, result):
        (run_dir / "trajectories" / f"{name}.json").write_text(
            json.dumps(result, default=_json_default, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{name}: {result.status} — {result.output}", flush=True)
        assert result.status == "finished", (
            f"{name}: {result.error_message}; saved trajectory in "
            f"{run_dir / 'trajectories' / f'{name}.json'}"
        )

    agent = ClaudeCode(config.agent)
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    assert "CLAUDE.md" not in baseline.files
    assert not any(path.startswith("skills/") for path in baseline.files)
    baseline.save(run_dir / "snapshots" / "baseline.json")
    question = "What is 19 + 23? Reply with only the answer and no explanation."
    answer = await agent.run(question)
    save("answer", answer)
    assert answer.output.strip() == "42", (
        f"answer: expected '42', got {answer.output!r}; error={answer.error_message!r}"
    )

    # Native Claude tools edit the target without loading its instructions.
    target = MiniAgent({"llm": {"model_name": model}})
    target.set_scope({"skill": "rw"})
    mini_baseline = target.snapshot
    mini_baseline.save(run_dir / "snapshots" / "miniagent-baseline.json")
    with mini_baseline.check_out(working_dir=run_dir / "working") as directory:
        edited = await agent.run(
            "Read skills/main.md, then replace it with exactly the following line "
            "and a trailing newline. Change no other files:\n"
            "Answer concisely using the supplied evidence.",
            working_dir=directory,
        )
        save("edit", edited)
        assert (directory / "skills/main.md").read_text().strip() == (
            "Answer concisely using the supplied evidence."
        ), (
            f"edit: unexpected skills/main.md content; "
            f"output={edited.output!r}; error={edited.error_message!r}"
        )
        mini_candidate = mini_baseline.commit(directory)
    mini_candidate.save(run_dir / "snapshots" / "miniagent-candidate.json")
    assert target.snapshot is mini_baseline, "edit selected the target candidate"

    # Add a test-only native skill to a candidate; the baseline has no skills.
    with baseline.check_out(working_dir=run_dir / "working") as directory:
        skill = directory / "skills/smoke-response/SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            "---\nname: smoke-response\n"
            "description: Return a marker when explicitly invoked by this smoke test.\n"
            "---\nReply with exactly CLAUDE_SKILL_OK.\n",
            encoding="utf-8",
        )
        candidate = baseline.commit(directory)
    candidate.save(run_dir / "snapshots" / "candidate.json")
    skill_question = (
        "Use the flashrsi:smoke-response skill and follow its response instruction."
    )
    (trial,) = await agent.rollout(
        [Task("candidate", skill_question)], snapshot=candidate
    )
    save("candidate", trial)
    assert trial.output.strip() == "CLAUDE_SKILL_OK", (
        f"candidate: expected 'CLAUDE_SKILL_OK', got {trial.output!r}; "
        f"error={trial.error_message!r}"
    )
    assert agent.snapshot is baseline, "rollout selected the candidate"
    unchanged = await agent.run(question)
    save("baseline_after", unchanged)
    assert unchanged.output.strip() == "42", (
        f"baseline_after: expected '42', got {unchanged.output!r}; "
        f"error={unchanged.error_message!r}"
    )
    agent.update(candidate)
    selected = await agent.run(skill_question)
    save("selected", selected)
    assert selected.output.strip() == "CLAUDE_SKILL_OK", (
        f"selected: expected 'CLAUDE_SKILL_OK', got {selected.output!r}; "
        f"error={selected.error_message!r}"
    )
    print("PASS: answer, edit, skill candidate, baseline isolation, and update.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--max-budget-usd", type=float, default=1.0)
    arguments = parser.parse_args()
    asyncio.run(
        main(
            arguments.model,
            timeout=arguments.timeout,
            max_turns=arguments.max_turns,
            max_budget_usd=arguments.max_budget_usd,
        )
    )
