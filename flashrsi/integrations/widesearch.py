"""Native web execution, followed by host-only official WideSearch grading."""

import asyncio
import copy
import math
import threading
from dataclasses import replace

from flashrsi._records import _redact, _secrets
from flashrsi.benchmarks.widesearch import REVISION, _scores
from flashrsi.integrations import _web_tools, _widesearch_grade


def bind(agent, benchmark):
    benchmark._check()
    retrieval = _web_tools.settings(agent, benchmark.config, "WideSearch")
    judge = copy.deepcopy(dict(benchmark.config.get("judge", {})))
    llm = judge.setdefault("llm", {})
    llm.setdefault("model_name", "gpt-4.1-2025-04-14")
    if not llm.get("model_name") or not llm.get("api_key"):
        raise ValueError(
            "WideSearch requires independent benchmark.judge.llm.api_key and model_name"
        )
    if set(llm) & {"tools", "tool_choice", "messages", "model", "stream", "functions"}:
        raise ValueError(
            "WideSearch judge.llm must not override messages, tools, model or streaming"
        )
    judge.setdefault("timeout", 300)
    timeout = judge["timeout"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("WideSearch judge.timeout must be positive and finite")
    if type(judge.get("max_retries", 1)) is not int or judge.get("max_retries", 1) < 0:
        raise ValueError("WideSearch judge.max_retries must be a nonnegative integer")
    secrets = sorted(set(_secrets(retrieval) + _secrets(judge)), key=len, reverse=True)

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("WideSearch requires a loaded benchmark Task")
        result = await _web_tools.run(target, task, retrieval, "WideSearch")
        result = replace(
            result,
            messages=tuple(
                message
                for message in result.messages
                if message.get("type") not in ("WideSearchVerifier", "WideSearchJudge")
            ),
        )
        if result.status == "finished":
            cancelled = threading.Event()
            try:
                scores, usage = await asyncio.to_thread(
                    _widesearch_grade.evaluate,
                    benchmark._queries_by_id[task.task_id],
                    result.output,
                    judge,
                    cancelled=cancelled,
                )
                scores = _scores(scores)
                result = replace(
                    result,
                    usage={**result.usage, "benchmark_judge": usage},
                    messages=(
                        *result.messages,
                        {
                            "type": "WideSearchVerifier",
                            "task_id": task.task_id,
                            "task_checksum": task.metadata["task_checksum"],
                            "snapshot_id": target.snapshot.id,
                            "judge_revision": REVISION,
                            "judge_model": llm["model_name"],
                            "scores": scores,
                        },
                    ),
                )
            except asyncio.CancelledError:
                cancelled.set()
                raise
            except Exception as exc:
                if isinstance(exc, _widesearch_grade._JudgeError):
                    result = replace(
                        result,
                        usage={**result.usage, "benchmark_judge": exc.usage},
                        messages=(
                            *result.messages,
                            {
                                "type": "WideSearchJudge",
                                "task_id": task.task_id,
                                "task_checksum": task.metadata["task_checksum"],
                                "snapshot_id": target.snapshot.id,
                                "status": "error",
                                "judge_revision": REVISION,
                                "judge_model": llm["model_name"],
                                "responses": exc.responses,
                                "error": str(exc),
                            },
                        ),
                    )
                result = replace(
                    result,
                    status="error",
                    error_message=f"WideSearch judge failed ({type(exc).__name__})",
                )
        return replace(
            result,
            output=_redact(result.output, secrets),
            messages=_redact(result.messages, secrets),
            usage=_redact(result.usage, secrets),
            error_message=_redact(result.error_message, secrets),
        )

    agent._env_runner = run
