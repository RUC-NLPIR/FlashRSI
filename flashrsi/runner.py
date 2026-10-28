"""Instantiate components, run evolution, and save the final held-out result."""

from __future__ import annotations

import copy
import importlib.util
import logging
from statistics import mean

from flashrsi._records import _write_record
from flashrsi._run_summary import _finish_summary
from flashrsi.agents import LLM, ClaudeCode, Codex, MiniAgent
from flashrsi.algorithms import (
    ACE,
    ADAS,
    AHE,
    GEPA,
    OPRO,
    RRSI,
    DarwinX,
    EvoHarness,
    EvoPrompt,
    MetaHarness,
    ModularRSI,
    SkillOpt,
)
from flashrsi.benchmarks import (
    AIME,
    BBEH,
    BFCL,
    HLE,
    MATH,
    NQ,
    ALFWorld,
    AppWorldBenchmark,
    BrowseComp,
    DeepSearchQA,
    DeepSWE,
    HarveyLAB,
    HotpotQA,
    JobBench,
    LiveMathBench,
    MuSiQue,
    OfficeQAPro,
    SearchQA,
    SpreadsheetBench2,
    SuperGPQA,
    SWEBench,
    SWEBenchPro,
    Tau2Benchmark,
    Tau3Banking,
    TerminalBench,
    TravelPlanner,
    TriviaQA,
    TwoWikiMultiHopQA,
    WideSearch,
    WorkBench,
)
from flashrsi.config import prepare_run_dir

_AGENTS = {"miniagent": MiniAgent, "claude_code": ClaudeCode, "codex": Codex}
_BENCHMARKS = {
    "alfworld": ALFWorld,
    "tau2": Tau2Benchmark,
    "aime": AIME,
    "bbeh": BBEH,
    "supergpqa": SuperGPQA,
    "twowiki_multihopqa": TwoWikiMultiHopQA,
    "travelplanner": TravelPlanner,
    "harvey_lab": HarveyLAB,
    "bfcl": BFCL,
    "browsecomp": BrowseComp,
    "deepsearchqa": DeepSearchQA,
    "deepswe": DeepSWE,
    "widesearch": WideSearch,
    "workbench": WorkBench,
    "appworld": AppWorldBenchmark,
    "searchqa": SearchQA,
    "hotpotqa": HotpotQA,
    "musique": MuSiQue,
    "triviaqa": TriviaQA,
    "nq": NQ,
    "math": MATH,
    "livemathbench": LiveMathBench,
    "hle": HLE,
    "officeqa_pro": OfficeQAPro,
    "swe_bench": SWEBench,
    "swe_bench_pro": SWEBenchPro,
    "terminal_bench": TerminalBench,
    "jobbench": JobBench,
    "spreadsheetbench2": SpreadsheetBench2,
    "tau3_banking": Tau3Banking,
}
_ALGORITHMS = {
    "adas": ADAS,
    "darwinx": DarwinX,
    "evo_harness": EvoHarness,
    "meta_harness": MetaHarness,
    "modular_rsi": ModularRSI,
    "rrsi": RRSI,
    "ace": ACE,
    "ahe": AHE,
    "skillopt": SkillOpt,
    "opro": OPRO,
    "gepa": GEPA,
    "evoprompt": EvoPrompt,
}
_LOGGER = logging.getLogger(__name__)


async def _prepare(config):
    """Use the same initialization for a check and a real run, without model calls."""
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
        Codex: (("codex_cli_bin",), "codex"),
        LLM: (("openai",), "llm"),
    }
    for cls in (target_type, worker_type):
        for module in dependencies.get(cls, ((), ""))[0]:
            if importlib.util.find_spec(module) is None:
                extra = dependencies[cls][1]
                raise ValueError(f"Missing {module}; install flashrsi-lite[{extra}]")
    from flashrsi._startup import _preflight, _role

    for cls, section, label in (
        (target_type, config.agent, "agent"),
        (worker_type, worker_config, "algorithm.worker"),
    ):
        if cls in (MiniAgent, ClaudeCode, Codex, LLM):
            _role(section, label, cls.name)
    await _preflight(config)
    target, worker = target_type(config.agent), worker_type(worker_config)
    benchmark = benchmark_type(config.benchmark)
    if isinstance(benchmark, ALFWorld):
        from flashrsi.integrations.alfworld import bind

        bind(target, benchmark)
    if isinstance(benchmark, WorkBench):
        from flashrsi.integrations.workbench import bind

        bind(target, benchmark)
    if isinstance(benchmark, TravelPlanner):
        from flashrsi.integrations.travelplanner import bind

        bind(target, benchmark)
    if isinstance(benchmark, HarveyLAB):
        from flashrsi.integrations.harvey_lab import bind

        bind(target, benchmark)
    if isinstance(benchmark, WideSearch):
        from flashrsi.integrations.widesearch import bind

        bind(target, benchmark)
    if isinstance(benchmark, DeepSearchQA):
        from flashrsi.integrations.deepsearchqa import bind

        bind(target, benchmark)
    if isinstance(benchmark, BrowseComp):
        from flashrsi.integrations.browsecomp import bind

        bind(target, benchmark)
    if isinstance(benchmark, HotpotQA) and benchmark.mode == "fullwiki":
        from flashrsi.integrations.hotpotqa import bind

        bind(target, benchmark)
    if isinstance(benchmark, MATH):
        benchmark._check()
    if isinstance(benchmark, LiveMathBench):
        from flashrsi.integrations.livemathbench import bind

        bind(target, benchmark)
    if isinstance(benchmark, HLE):
        from flashrsi.integrations.hle import bind

        bind(target, benchmark)
    if isinstance(benchmark, OfficeQAPro):
        from flashrsi.integrations.officeqa_pro import bind

        bind(target, benchmark)
    if isinstance(benchmark, SWEBench):
        from flashrsi.integrations.swe_bench import bind

        bind(target, benchmark)
    if isinstance(benchmark, BFCL):
        from flashrsi.integrations.bfcl import bind

        bind(target, config.benchmark)
    if isinstance(benchmark, AppWorldBenchmark):
        from flashrsi.integrations.appworld import bind

        bind(target, config.benchmark)
    if isinstance(benchmark, (TerminalBench, SpreadsheetBench2)):
        from flashrsi.integrations.harbor import bind

        bind(target)
    if isinstance(benchmark, DeepSWE):
        from flashrsi.integrations.deepswe import bind

        bind(target, benchmark)
    if isinstance(benchmark, JobBench):
        from flashrsi.integrations.jobbench import bind

        bind(target, benchmark)
    if isinstance(benchmark, SWEBenchPro):
        from flashrsi.integrations.swe_bench_pro import bind

        bind(target, benchmark)
    if isinstance(benchmark, (Tau2Benchmark, Tau3Banking)):
        from flashrsi.integrations.tau2 import bind

        bind(
            target,
            config.benchmark.get("user_simulator"),
            task_timeout=config.benchmark.get("task_timeout"),
            judge=config.benchmark.get("judge"),
        )
    algorithm = algorithm_type(
        config.algorithm, target=target, worker=worker, benchmark=benchmark
    )
    return algorithm


async def _run(config):
    algorithm = await _prepare(config)
    worker, benchmark = algorithm.worker, algorithm.benchmark
    resolved = copy.deepcopy(config)
    resolved.algorithm = algorithm.config
    run_dir = prepare_run_dir(resolved)
    if isinstance(benchmark, HarveyLAB) and benchmark._artifacts_dir is None:
        benchmark._artifacts_dir = run_dir / "artifacts" / "harvey_lab"
    if isinstance(
        benchmark, (TerminalBench, SpreadsheetBench2, DeepSWE, JobBench, SWEBenchPro)
    ):
        algorithm.target.config.setdefault("harbor", {}).setdefault(
            "artifacts_dir", str(run_dir / "artifacts" / "harbor")
        )
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
            "test_metrics": {
                name: mean(item.metrics[name] for item in results)
                for name in (results[0].metrics if results else ())
                if all(name in item.metrics for item in results)
            },
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
