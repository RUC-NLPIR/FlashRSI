"""Run the two-harness SkillOpt/SearchQA experiment with replayable requests.

From FlashRSI-Lite: .venv/bin/python scripts/run_searchqa_experiment.py --execute
No model requests are made without --execute. Secrets come from .env or the
process environment, never command-line arguments or checked-in YAML files.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import fcntl
import hashlib
import json
import os
import random
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flashrsi._records import _config_record, _redact, _secrets  # noqa: E402
from flashrsi._run_summary import _finish_summary  # noqa: E402
from flashrsi.algorithms import SkillOpt  # noqa: E402
from flashrsi.config import load_config, prepare_run_dir  # noqa: E402
from scripts._experiment_runtime import (  # noqa: E402
    CachedClaudeCode,
    CachedLLM,
    CachedMiniAgent,
)
from scripts._searchqa_experiment_support import (  # noqa: E402
    UPSTREAM_REVISION,
    ExperimentSearchQA,
    create_seed,
)

PROFILES = {
    "smoke": {"counts": (4, 4, 8), "num_epochs": 1, "max_steps": 1},
    "pilot": {"counts": (40, 40, 100), "num_epochs": 1, "max_steps": 1},
    "full": {"counts": (400, 200, 1400), "num_epochs": 4, "max_steps": None},
}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _credentials(path):
    values = {}
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise ValueError(f"Private credential file must have mode 0600: {path}")
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key in ("FLASHRSI_BASE_URL", "FLASHRSI_API_KEY"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    if not values.get("FLASHRSI_API_KEY") or not values.get("FLASHRSI_BASE_URL"):
        raise ValueError(
            "Set FLASHRSI_BASE_URL and FLASHRSI_API_KEY in .env or environment"
        )
    values["FLASHRSI_BASE_URL"] = values["FLASHRSI_BASE_URL"].rstrip("/")
    return values


def _prepare_data(source, destination, profile):
    """Validate frozen source bytes, preserve split membership, then sample."""
    import pyarrow.parquet as pq

    manifest = json.loads((source / "manifest.json").read_text())
    result = {}
    source_ids = set()
    destination.mkdir(parents=True, exist_ok=True)
    for split, count in zip(("train", "dev", "test"), PROFILES[profile]["counts"]):
        path = source / f"{split}.parquet"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = manifest["splits"][split]
        if digest != expected["sha256"]:
            raise ValueError(f"Source checksum mismatch: {split}")
        rows = pq.read_table(path).to_pylist()
        if len(rows) != expected["count"] or len(rows) < count:
            raise ValueError(f"Source count mismatch: {split}")
        for row in rows:
            if row["id"] in source_ids:
                raise ValueError("Data splits overlap in full source")
            source_ids.add(row["id"])
        if count < len(rows):
            # The same predetermined tasks are used by both harnesses.
            indices = sorted(random.Random(42).sample(range(len(rows)), count))
            rows = [rows[index] for index in indices]
        payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        target = destination / f"{split}.jsonl"
        if target.exists() and target.read_text() != payload:
            raise ValueError(f"Prepared data changed; use a new run root: {target}")
        if not target.exists():
            target.write_text(payload)
        result[split] = {
            "count": len(rows),
            "source_sha256": digest,
            "sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "ids": [row["id"] for row in rows],
        }
    all_ids = [task_id for split in result.values() for task_id in split["ids"]]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("Data splits overlap")
    return {"source_manifest": manifest, "selected": result}


def _fingerprint(config, data, initial_id):
    # Freeze the recipe, not just its model names. This prevents replay across
    # source/config changes, including changes to the optimizer prompt templates.
    source_paths = list((ROOT / "flashrsi").rglob("*.py")) + [
        Path(__file__),
        ROOT / "scripts/_experiment_runtime.py",
        ROOT / "scripts/_searchqa_experiment_support.py",
    ]
    sources = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_paths)
    }
    material = {
        "config": _config_record(config),
        "data": data,
        "initial_snapshot": initial_id,
        "sources": sources,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


@contextmanager
def _exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"Another experiment process owns {path}") from None
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()) + "\n")
        stream.flush()
        yield


def _scores(trajectories):
    return {
        "tasks": len(trajectories),
        "finished": sum(t.status == "finished" for t in trajectories),
        **{
            metric: mean(t.metrics[metric] for t in trajectories)
            for metric in ("hard", "f1", "exact_match", "lite_f1")
        },
    }


def _paired(before, after):
    if [t.task.task_id for t in before] != [t.task.task_id for t in after]:
        raise ValueError("Before/after test task IDs differ")
    differences = [
        b.metrics["hard"] - a.metrics["hard"]
        for a, b in zip(before, after, strict=True)
    ]
    rng = random.Random(42)
    samples = sorted(
        mean(rng.choices(differences, k=len(differences))) for _ in range(2000)
    )
    return {
        "delta_percentage_points": mean(differences) * 100,
        "improved_tasks": differences.count(1.0),
        "regressed_tasks": differences.count(-1.0),
        "paired_bootstrap_95pct_pp": [samples[49] * 100, samples[1949] * 100],
    }


async def _run_one(args, harness, credentials, data):
    experiment = args.run_root / args.profile / harness
    experiment.mkdir(parents=True, exist_ok=True)
    with _exclusive(experiment / "process.lock"):
        seed = experiment / "seed"
        if not seed.exists():
            create_seed(harness, seed)
        base = credentials["FLASHRSI_BASE_URL"]
        endpoint = base.removesuffix("/v1") if harness == "claude_code" else base
        config = load_config(
            ROOT / f"examples/searchqa_deepseek/{harness}.yaml",
            overrides={
                "run": {"output_dir": str(experiment / "attempts")},
                "benchmark": {"data_path": str(args.run_root / args.profile / "data")},
                "agent": {
                    "source_dir": str(seed),
                    "llm": {
                        "api_key": credentials["FLASHRSI_API_KEY"],
                        "base_url": endpoint,
                    },
                },
                "algorithm": {
                    "num_epochs": PROFILES[args.profile]["num_epochs"],
                    "max_steps": PROFILES[args.profile]["max_steps"],
                    "worker": {
                        "llm": {
                            "api_key": credentials["FLASHRSI_API_KEY"],
                            "base_url": base,
                        }
                    },
                },
            },
        )
        target_type = CachedMiniAgent if harness == "miniagent" else CachedClaudeCode
        target = target_type(config.agent).configure_experiment(
            experiment / "cache", concurrency=args.concurrency
        )
        worker = CachedLLM(config.algorithm.worker).configure_experiment(
            experiment / "cache"
        )
        benchmark = ExperimentSearchQA(config.benchmark)
        algorithm = SkillOpt(
            config.algorithm, target=target, worker=worker, benchmark=benchmark
        )
        initial = target.snapshot
        config.algorithm = copy.deepcopy(algorithm.config)
        fingerprint = _fingerprint(config, data, initial.id)
        plan = {
            "profile": args.profile,
            "harness": harness,
            "fingerprint": fingerprint,
            "config": _config_record(config),
            "split_counts": {k: len(v) for k, v in benchmark.load().items()},
            "concurrency": args.concurrency,
            "official_revision": UPSTREAM_REVISION,
            "recipe": "FlashRSI-Lite SkillOpt constant-edit-budget migration",
            "primary_metric": "official hard (normalized EM with answer extraction)",
            "initial_snapshot": initial.id,
        }
        state_path = experiment / "plan.json"
        if state_path.exists():
            previous = json.loads(state_path.read_text())
            if previous["fingerprint"] != fingerprint:
                raise ValueError(
                    "Recipe changed; choose a new --run-root to prevent mixed results"
                )
        _write_json(state_path, plan)
        print(
            json.dumps(
                {
                    k: plan[k]
                    for k in ("profile", "harness", "split_counts", "concurrency")
                }
            ),
            flush=True,
        )
        if not args.execute:
            return {"status": "prepared", "plan": str(state_path)}
        result_path = experiment / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if result.get("status") == "finished":
                print(
                    f"[{harness}] completed result already exists: {result_path}",
                    flush=True,
                )
                _finish_summary(experiment)
                return result
        run_dir = prepare_run_dir(config)
        algorithm._run_dir = run_dir
        status_path = experiment / "status.json"
        status = {
            "status": "running",
            "pid": os.getpid(),
            "attempt": str(run_dir),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(status_path, status)
        print(f"[{harness}] experiment attempt: {run_dir}", flush=True)
        try:
            final = await algorithm.evolve()
            # Selection is complete before either test score is computed.
            before = await algorithm._evaluate(
                initial, benchmark.test, label="initial-test"
            )
            after = await algorithm._evaluate(final, benchmark.test, label="final-test")
            decisions = [
                json.loads(p.read_text())
                for p in sorted((run_dir / "trajectories").glob("*-decision.json"))
            ]
            result = {
                **plan,
                "status": "finished",
                "attempt": str(run_dir),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "final_snapshot": final.id,
                "baseline_test": _scores(before),
                "evolved_test": _scores(after),
                "paired_comparison": _paired(before, after),
                "accepted_candidates": sum(bool(d.get("accepted")) for d in decisions),
                "candidate_decisions": len(decisions),
                "test_used_for_selection": False,
            }
            _write_json(result_path, result)
            _write_json(run_dir / "result.json", result)
            _write_json(status_path, {**status, "status": "finished"})
            final_skill_dir = experiment / "final_skills"
            for name, entry in final.files.items():
                if entry.component == "skill":
                    output = final_skill_dir / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(entry.content)
            print(
                json.dumps(
                    {
                        "harness": harness,
                        "baseline": result["baseline_test"],
                        "evolved": result["evolved_test"],
                        "paired": result["paired_comparison"],
                    }
                ),
                flush=True,
            )
            return result
        except BaseException as error:
            message = _redact(str(error) or type(error).__name__, _secrets(config))
            _write_json(status_path, {**status, "status": "error", "error": message})
            _write_json(run_dir / "error.json", {"status": "error", "error": message})
            raise RuntimeError(message) from None
        finally:
            _finish_summary(experiment)


async def _main(args):
    credentials = _credentials(args.env_file)
    data = _prepare_data(
        args.data_source, args.run_root / args.profile / "data", args.profile
    )
    _write_json(args.run_root / args.profile / "data-manifest.json", data)
    results = []
    for harness in args.harness:
        results.append(await _run_one(args, harness, credentials, data))
    _write_json(args.run_root / args.profile / "summary.json", results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="smoke")
    parser.add_argument(
        "--harness",
        nargs="+",
        choices=("miniagent", "claude_code"),
        default=["miniagent", "claude_code"],
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--run-root", type=Path, default=ROOT / "runs/skillopt-searchqa-deepseek"
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--data-source", type=Path, default=ROOT / ".cache/searchqa/publish/searchqa"
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.run_root = args.run_root.expanduser().resolve()
    try:
        asyncio.run(_main(args))
    except (Exception, KeyboardInterrupt) as error:
        print(f"Experiment stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
