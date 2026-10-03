"""Instantiate components, run evolution, and save the final held-out result."""

from __future__ import annotations

import copy
import importlib.util
import logging
from statistics import mean

from flashrsi._records import _write_record
from flashrsi._run_summary import _finish_summary
from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.algorithms import (
    ACE,
    ADAS,
    AHE,
    GEPA,
    OPRO,
    DarwinX,
    EvoPrompt,
    MetaHarness,
    SkillOpt,
)
from flashrsi.benchmarks import HotpotQA, SearchQA, Tau3Banking, TerminalBench
from flashrsi.config import prepare_run_dir

_AGENTS = {"miniagent": MiniAgent, "claude_code": ClaudeCode}
_BENCHMARKS = {
    "searchqa": SearchQA,
    "hotpotqa": HotpotQA,
    "terminal_bench": TerminalBench,
    "tau3_banking": Tau3Banking,
}
_ALGORITHMS = {
    "ace": ACE,
    "adas": ADAS,
    "darwinx": DarwinX,
    "meta_harness": MetaHarness,
    "ahe": AHE,
    "skillopt": SkillOpt,
    "opro": OPRO,
    "gepa": GEPA,
    "evoprompt": EvoPrompt,
}
_LOGGER = logging.getLogger(__name__)


async def _run(config):
    target_type = _lookup(_AGENTS, config.agent.name, "agent")
    benchmark_type = _lookup(_BENCHMARKS, config.benchmark.name, "benchmark")
    algorithm_type = _lookup(_ALGORITHMS, config.algorithm.name, "algorithm")
    worker_config = config.algorithm.worker
    worker_type = (
        LLM
        if worker_config.type == "llm"
        else _lookup(_AGENTS, worker_config.name, "worker")
    )
    dependencies = {
        MiniAgent: (("openai", "requests"), "miniagent"),
        ClaudeCode: (("claude_agent_sdk",), "claude-code"),
        LLM: (("openai",), "llm"),
    }
    for cls in (target_type, worker_type):
        for module in dependencies.get(cls, ((), ""))[0]:
            if importlib.util.find_spec(module) is None:
                extra = dependencies[cls][1]
                raise ValueError(f"Missing {module}; install flashrsi-lite[{extra}]")
    target, worker = target_type(config.agent), worker_type(worker_config)
    benchmark = benchmark_type(config.benchmark)
    if isinstance(benchmark, TerminalBench):
        from flashrsi.integrations.harbor import bind

        bind(target)
    if isinstance(benchmark, Tau3Banking):
        from flashrsi.integrations.tau2 import bind

        bind(target, config.benchmark.get("user_simulator"))
    algorithm = algorithm_type(
        config.algorithm, target=target, worker=worker, benchmark=benchmark
    )
    resolved = copy.deepcopy(config)
    resolved.algorithm = algorithm.config
    run_dir = prepare_run_dir(resolved)
    algorithm._run_dir = run_dir
    _LOGGER.info("Experiment: %s", run_dir)
    try:
        if worker.component_rules:
            worker.snapshot.save(run_dir / "snapshots" / "worker.json")
        final = await algorithm.evolve()
        results = await algorithm._evaluate(final, benchmark.test, label="test")
        summary = {
            "status": "finished",
            "snapshot_id": final.id,
            "primary_metric": benchmark.primary_metric,
            "test_score": mean(
                item.metrics[benchmark.primary_metric] for item in results
            )
            if results
            else None,
            "test_tasks": len(results),
            "benchmark": dict(benchmark.metadata),
        }
        _write_record(run_dir / "result.json", summary, config)
    except BaseException as exc:
        _write_record(
            run_dir / "error.json",
            {"status": "error", "error": str(exc) or type(exc).__name__},
            config,
        )
        raise
    finally:
        _finish_summary(run_dir)
    return run_dir, summary


def _lookup(choices, name, role):
    try:
        return choices[name]
    except KeyError:
        raise ValueError(
            f"Unsupported {role}: {name}; available: {', '.join(choices)}"
        ) from None
