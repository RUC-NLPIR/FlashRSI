"""Live Atria smoke: answer, edit a skill, evaluate a candidate, recheck baseline.

Run from FlashRSI-Lite: uv run --extra miniagent python examples/miniagent_atria.py
Reads ATRIA_API_KEY or prompts without echo. Makes paid model calls.
"""

import asyncio
import getpass
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass

from flashrsi.agents import MiniAgent
from flashrsi.config import load_config, prepare_run_dir
from flashrsi.core import Task


def _json_default(value):
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


async def main():
    key = os.environ.get("ATRIA_API_KEY") or getpass.getpass("Atria API key: ")
    config = load_config(
        overrides={
            # These labels organize smoke artifacts; no Algorithm/Benchmark runs.
            "algorithm": {
                "name": "smoke",
                "worker": {"model_name": "Atria-Dawn-Preview"},
            },
            "benchmark": {"name": "local"},
            "agent": {
                "model_name": "Atria-Dawn-Preview",
                "base_url": "https://api.atria-asi.ai/v1",
                "api_key": key,
            },
        }
    )
    run_dir = prepare_run_dir(config)
    print(f"Artifacts: {run_dir}", flush=True)

    def save(name, trajectory):
        text = json.dumps(
            trajectory, default=_json_default, ensure_ascii=False, indent=2
        )
        assert key not in text, "Credential found in trajectory"
        (run_dir / "trajectories" / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"{name}: {trajectory.status} — {trajectory.output}", flush=True)
        assert trajectory.status == "finished", trajectory.error_message

    agent = MiniAgent(config)
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    baseline.save(run_dir / "snapshots" / "baseline.json")
    question = "What is 19 + 23? Reply with only the integer."
    text = await agent.run(question)
    save("text", text)
    assert text.output.strip() == "42"

    skill = "For every question, reply with exactly ATRIA_SKILL_OK and nothing else.\n"
    with baseline.check_out(working_dir=run_dir / "working") as directory:
        edited = await agent.run(
            "Read skills/main.md, then replace its entire content with the following "
            "single line, including the trailing newline. Change no other files.\n\n"
            + skill,
            working_dir=directory,
        )
        save("edit", edited)
        assert (directory / "skills/main.md").read_text(encoding="utf-8") == skill
        tool_names = {
            call["function"]["name"]
            for message in edited.messages
            for call in message.get("tool_calls", ())
        }
        assert {"read_file", "write_file"} <= tool_names
        candidate = baseline.commit(directory)
    candidate.save(run_dir / "snapshots" / "candidate.json")

    (trial,) = await agent.rollout([Task("candidate", question)], snapshot=candidate)
    save("candidate", trial)
    assert trial.output.strip() == "ATRIA_SKILL_OK"
    assert agent.snapshot is baseline

    unchanged = await agent.run(question)
    save("baseline_after", unchanged)
    assert unchanged.output.strip() == "42"
    print("PASS: answer, file tools, candidate skill, and baseline isolation.")


if __name__ == "__main__":
    asyncio.run(main())
