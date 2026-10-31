"""Bind native MiniAgent / Claude Code web execution and host-only autorating."""

import copy
import importlib.util
import math
from dataclasses import replace

from flashrsi._records import _redact, _secrets
from flashrsi.benchmarks.deepsearchqa._official import MODEL, REVISION, metrics
from flashrsi.integrations import _deepsearchqa_judge, _web_tools


def bind(agent, benchmark):
    retrieval = _web_tools.settings(agent, benchmark.config, "DeepSearchQA")
    judge = copy.deepcopy(dict(benchmark.config.get("judge", {})))
    provider = judge.setdefault("provider", "google")
    if provider not in ("google", "openai"):
        raise ValueError("DeepSearchQA judge.provider must be google or openai")
    try:
        available = (
            importlib.util.find_spec(
                "google.genai" if provider == "google" else "openai"
            )
            is not None
        )
    except ModuleNotFoundError:
        available = False
    if not available:
        raise ValueError("Install flashrsi-lite[all] for DeepSearchQA judging")
    llm = judge.setdefault("llm", {})
    if provider == "google":
        llm.setdefault("model_name", MODEL)
    if not llm.get("model_name") or not llm.get("api_key"):
        raise ValueError(
            "DeepSearchQA requires independent benchmark.judge.llm configuration"
        )
    if provider == "google" and llm["model_name"] != MODEL:
        raise ValueError(
            "DeepSearchQA requires independent benchmark.judge.llm.api_key and model_name: gemini-2.5-flash"
        )
    if set(llm) - {"model_name", "api_key", "base_url"}:
        raise ValueError(
            "DeepSearchQA judge.llm only accepts model_name, api_key and base_url; official generation defaults are preserved"
        )
    judge.setdefault("timeout", 300)
    timeout = judge["timeout"]
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or timeout < 0.001
    ):
        raise ValueError(
            "DeepSearchQA judge.timeout must be finite and at least 0.001 seconds"
        )
    retries = judge.get("max_retries", 4)
    if type(retries) is not int or retries < 0:
        raise ValueError("DeepSearchQA judge.max_retries must be a nonnegative integer")
    secrets = sorted(set(_secrets(retrieval) + _secrets(judge)), key=len, reverse=True)

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("DeepSearchQA requires a loaded benchmark Task")
        result = await _web_tools.run(target, task, retrieval, "DeepSearchQA")
        if result.status == "finished":
            try:
                counts, usage = await _deepsearchqa_judge.judge(
                    benchmark._rows_by_id[task.task_id], result.output, judge
                )
                metrics(counts)
                result = replace(
                    result,
                    usage={**result.usage, "benchmark_judge": usage},
                    messages=(
                        *result.messages,
                        {
                            "type": "DeepSearchQAVerifier",
                            "task_id": task.task_id,
                            "task_checksum": task.metadata["task_checksum"],
                            "snapshot_id": target.snapshot.id,
                            "judge_revision": REVISION,
                            "judge_model": llm["model_name"],
                            "judge_provider": provider,
                            "judge_profile": "official"
                            if provider == "google"
                            else "custom",
                            "counts": counts,
                        },
                    ),
                )
            except Exception as exc:
                result = replace(
                    result,
                    status="error",
                    error_message=f"DeepSearchQA judge failed ({type(exc).__name__})",
                )
        return replace(
            result,
            output=_redact(result.output, secrets),
            messages=_redact(result.messages, secrets),
            usage=_redact(result.usage, secrets),
            error_message=_redact(result.error_message, secrets),
        )

    agent._env_runner = run
