"""Offline adapters illustrating an open process and a closed SDK boundary.

Run with: uv run python examples/agents/native_adapters.py
The closed example injects a fake SDK; it never calls Claude Code or a model.
"""

import asyncio

from closed_harness import SDKAgent
from open_harness import ProcessAgent

from flashrsi.core import Task, Trajectory


class FakeSDK:
    """Example-only stand-in, not a claim about the Claude SDK method signature."""

    async def execute(self, *, prompt, instructions, skills_dir, cwd, model):
        skill = (skills_dir / "answer/SKILL.md").read_text().strip().splitlines()[-1]
        if cwd is not None:
            (cwd / "skills/main.md").write_text(skill + "\n")
        return Trajectory(
            output=skill,
            messages=({"role": "user", "content": prompt},),
            usage={"example_calls": 1},
        )


async def main():
    target = ProcessAgent({})
    target.set_scope({"skill": "rw", "code": "rw"})
    worker = SDKAgent({"llm": {"model_name": "offline"}}, sdk=FakeSDK())
    for agent in (target, worker):
        assert "components.yaml" not in agent.snapshot.files
        assert "__init__.py" not in agent.snapshot.files
    original = target.snapshot
    print("Initial:", (await target.run("capital?")).output)
    with original.check_out() as directory:
        edit_result = await worker.run("Improve the answer", working_dir=directory)
        (directory / "skills/main.md").write_text("Paris, France\n")
        source = directory / "runtime/main.py"
        source.write_text(
            source.read_text().replace('print(f"{answer}', 'print(f"Updated: {answer}')
        )
        candidate = original.commit(directory)
    (evaluated,) = await target.rollout(
        (Task("capital", "capital?"),), snapshot=candidate
    )
    assert evaluated.output == "Updated: Paris, France (capital?)"
    assert target.snapshot is original
    target.update(candidate)
    assert (await target.run("capital?")).output == evaluated.output
    print("Candidate:", evaluated.output)
    print("Worker trace retained:", edit_result.output, dict(edit_result.usage))


if __name__ == "__main__":
    asyncio.run(main())
