"""Use JobBench's native separate verifier with independent judge credentials."""

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType


def bind(agent, benchmark):
    from flashrsi.integrations import harbor

    judge = benchmark.config.get("judge", {})
    if not isinstance(judge, Mapping) or not isinstance(judge.get("llm", {}), Mapping):
        raise ValueError("JobBench benchmark.judge.llm must be a mapping")
    llm = judge.get("llm", {})
    for key in ("model_name", "api_key"):
        if not isinstance(llm.get(key), str) or not llm[key].strip():
            raise ValueError(f"JobBench requires benchmark.judge.llm.{key}")
    if set(llm) - {"model_name", "api_key", "base_url"}:
        raise ValueError(
            "JobBench native judge supports model_name, api_key and base_url"
        )
    verifier_env = {
        "JUDGE_MODEL": llm["model_name"],
        "JUDGE_API_KEY": llm["api_key"],
        "JUDGE_API_BASE": llm.get("base_url") or "https://api.x.ai/v1",
    }
    for option in ("max_workers", "max_retries", "timeout_per_rubric"):
        if option in judge:
            value = judge[option]
            if type(value) is not int or value < 1:
                raise ValueError(f"benchmark.judge.{option} must be a positive integer")
            verifier_env["JUDGE_" + option.upper()] = str(value)
    if agent.config.get("harbor", {}).get("integrity_review") is not None:
        raise ValueError(
            "JobBench uses its official judge; Terminal integrity_review is unsupported"
        )
    environment = agent.config.get("harbor", {}).get("environment_env", {})
    if isinstance(environment, Mapping) and any(
        key.startswith("JUDGE_") for key in environment
    ):
        raise ValueError(
            "JobBench judge variables belong only to benchmark.judge, not agent.harbor.environment_env"
        )
    harbor.bind(agent)
    benchmark.metadata = MappingProxyType(
        {
            **benchmark.metadata,
            "judge": {
                "model_name": verifier_env["JUDGE_MODEL"],
                "base_url": verifier_env["JUDGE_API_BASE"],
            },
        }
    )

    async def run(target, task):
        # Never place the judge in Agent.config: Harbor stages that config inside
        # the solver image. Its native verifier override is a separate channel.
        result = await harbor._run(target, task, verifier_env=dict(verifier_env))
        event = {**result.messages[-1], "judge": dict(benchmark.metadata["judge"])}
        return replace(result, messages=(*result.messages[:-1], event))

    agent._env_runner = run
