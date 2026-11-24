"""Execute each instruction's cases independently, then combine their verdicts."""

from dataclasses import replace

from flashrsi.benchmarks._harbor import _grade
from flashrsi.core import Trajectory


def bind(agent, benchmark):
    from flashrsi.integrations.harbor import bind as bind_harbor

    bind_harbor(agent)
    run_case = agent._env_runner

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("SpreadsheetBench requires a loaded benchmark Task")
        messages, outputs, rewards, usages, errors = [], [], [], [], []
        for case in benchmark._cases[task.task_id]:
            result = replace(await run_case(target, case), task=case)
            graded = _grade((result,), {case.task_id: case}, "SpreadsheetBench")[0]
            rewards.append(graded.metrics["reward"])
            messages.append({"type": "SpreadsheetBenchCase", "case_id": case.task_id})
            messages.extend(result.messages)
            outputs.append(f"Case {case.task_id}:\n{result.output}")
            usages.append(dict(result.usage))
            if result.status == "error":
                errors.append(f"Case {case.task_id}: {result.error_message}")
        messages.append(
            {
                "type": "SpreadsheetBenchVerifier",
                "task_id": task.task_id,
                "task_checksum": task.metadata["task_checksum"],
                "snapshot_id": target.snapshot.id,
                "case_rewards": rewards,
            }
        )
        return Trajectory(
            status="error" if errors else "finished",
            output="\n\n".join(outputs),
            messages=tuple(messages),
            usage={"samples": usages},
            error_message="\n".join(errors) or None,
        )

    agent._env_runner = run
