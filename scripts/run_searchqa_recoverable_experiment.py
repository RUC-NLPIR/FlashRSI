"""Continue the frozen parallel recipe with explicit invalid-edit rejection.

Only --adopt-patch-recovery may upgrade an unfinished parallel plan. It verifies
the complete former fingerprint and preserves the former plan before publishing
the added policy. Successful calls keep the same prompts and cache identities.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flashrsi._records import _config_record  # noqa: E402
from scripts import run_searchqa_experiment as runner  # noqa: E402
from scripts import run_searchqa_parallel_experiment as parallel  # noqa: E402
from scripts._parallel_plan_migration import atomic_json  # noqa: E402
from scripts._recoverable_skillopt import RecoverableSkillOpt  # noqa: E402

ADDED_KEYS = (
    "invalid_patch_policy",
    "patch_recovery_sha256",
    "patch_recovery_entrypoint_sha256",
)


def adopt_patch_recovery(experiment, config, data, initial_id, fingerprint):
    """Caller holds the runner's process.lock throughout this operation."""
    plan_path = experiment / "plan.json"
    old = json.loads(plan_path.read_text())
    if (experiment / "result.json").exists():
        raise ValueError("Cannot upgrade a completed result")
    previous = copy.deepcopy(config)
    for key in ADDED_KEYS:
        if key not in previous.algorithm or key in old["config"]["algorithm"]:
            raise ValueError("Expected unchanged parallel recipe plus patch recovery")
        del previous.algorithm[key]
    if (
        fingerprint(previous, data, initial_id) != old["fingerprint"]
        or _config_record(previous) != old["config"]
        or initial_id != old["initial_snapshot"]
    ):
        raise ValueError("Previous recipe/source/data changed; upgrade refused")
    adopted = {
        **old,
        "fingerprint": fingerprint(config, data, initial_id),
        "config": _config_record(config),
    }
    archive = experiment / "pre-patch-recovery-plan.json"
    if archive.exists():
        if json.loads(archive.read_text()) != old:
            raise ValueError("Previous plan archive conflicts")
    else:
        atomic_json(archive, old)
    evidence = {
        "previous_plan": old,
        "upgraded_plan": adopted,
        "added_algorithm_keys": list(ADDED_KEYS),
        "reason": (
            "Reject unapplicable completed fast patches without a score; "
            "record malformed sequential slow/meta output without inventing evaluations. "
            "Concurrent reflection/merge parse errors remain terminal."
        ),
    }
    audit = experiment / "patch-recovery-migration.json"
    if audit.exists():
        recorded = json.loads(audit.read_text())
        recorded.pop("created_at", None)
        if recorded != evidence:
            raise ValueError("Patch recovery migration conflicts")
    else:
        atomic_json(
            audit, {**evidence, "created_at": datetime.now(timezone.utc).isoformat()}
        )
    atomic_json(plan_path, adopted)
    return adopted["fingerprint"]


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--adopt-patch-recovery", action="store_true")
    options, remaining = parser.parse_known_args()
    original_fingerprint = runner._fingerprint
    original_class, original_argv = parallel.ParallelSkillOpt, sys.argv

    class ExperimentSkillOpt(RecoverableSkillOpt):
        _defaults = {
            **RecoverableSkillOpt._defaults,
            "patch_recovery_entrypoint_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }

    def fingerprint(config, data, initial_id):
        value = original_fingerprint(config, data, initial_id)
        experiment = Path(config.run.output_dir).parent
        plan_path = experiment / "plan.json"
        if options.adopt_patch_recovery and plan_path.exists():
            old = json.loads(plan_path.read_text())
            if old["fingerprint"] != value:
                return adopt_patch_recovery(
                    experiment, config, data, initial_id, original_fingerprint
                )
        return value

    runner._fingerprint = fingerprint
    parallel.ParallelSkillOpt = ExperimentSkillOpt
    sys.argv = [str(Path(__file__)), *remaining]
    try:
        return parallel.main()
    finally:
        runner._fingerprint = original_fingerprint
        parallel.ParallelSkillOpt, sys.argv = original_class, original_argv


if __name__ == "__main__":
    raise SystemExit(main())
