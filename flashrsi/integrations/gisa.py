"""Bind GISA to the shared per-task web tools; grading stays on the host."""

from flashrsi.integrations import _web_tools


def bind(agent, benchmark):
    retrieval = _web_tools.settings(agent, benchmark.config, "GISA")

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("GISA requires a loaded benchmark Task")
        return await _web_tools.run(target, task, retrieval, "GISA")

    agent._env_runner = run
