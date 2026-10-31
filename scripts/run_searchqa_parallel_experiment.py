"""Use the same SearchQA recipe with bounded parallel optimizer requests.

This defaults to a separate run root. An explicit --adopt-serial-plan can migrate
an interrupted serial run after verifying that only scheduling metadata differs.
The original plan and migration evidence are retained. No model calls occur
without --execute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_searchqa_experiment as runner  # noqa: E402
from scripts._context_safe_worker import ContextSafeLLM  # noqa: E402
from scripts._parallel_plan_migration import (  # noqa: E402
    adopt_serial_plan,
    atomic_json,
)
from scripts._parallel_skillopt import ParallelSkillOpt  # noqa: E402


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker-concurrency", type=int, default=4)
    parser.add_argument("--adopt-serial-plan", action="store_true")
    options, remaining = parser.parse_known_args()

    class ExperimentSkillOpt(ParallelSkillOpt):
        _defaults = {
            **ParallelSkillOpt._defaults,
            "worker_concurrency": options.worker_concurrency,
            "parallel_entrypoint_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "parallel_migration_sha256": hashlib.sha256(
                (ROOT / "scripts/_parallel_plan_migration.py").read_bytes()
            ).hexdigest(),
            "context_recovery_sha256": hashlib.sha256(
                (ROOT / "scripts/_context_safe_worker.py").read_bytes()
            ).hexdigest(),
        }

    if not any(
        arg == "--run-root" or arg.startswith("--run-root=") for arg in remaining
    ):
        remaining += ["--run-root", str(ROOT / "runs/skillopt-searchqa-deepseek")]
    original_argv, original_algorithm = sys.argv, runner.SkillOpt
    original_fingerprint, original_writer = runner._fingerprint, runner._write_json
    original_worker = runner.CachedLLM

    def fingerprint(config, data, initial_id):
        # _run_one calls this only while holding its existing process.lock.
        value = original_fingerprint(config, data, initial_id)
        experiment = Path(config.run.output_dir).parent
        plan_path = experiment / "plan.json"
        if options.adopt_serial_plan and plan_path.exists():
            previous = json.loads(plan_path.read_text())
            if previous["fingerprint"] != value:
                adopted = adopt_serial_plan(
                    experiment, config, data, initial_id, original_fingerprint
                )
                atomic_json(plan_path, adopted)
        return value

    sys.argv = [str(Path(__file__)), *remaining]
    runner.SkillOpt = ExperimentSkillOpt
    runner.CachedLLM = ContextSafeLLM
    runner._fingerprint = fingerprint
    # Independent harness processes may publish the same data manifest at once.
    runner._write_json = atomic_json
    try:
        return runner.main()
    finally:
        sys.argv, runner.SkillOpt = original_argv, original_algorithm
        runner._fingerprint, runner._write_json = original_fingerprint, original_writer
        runner.CachedLLM = original_worker


if __name__ == "__main__":
    raise SystemExit(main())
