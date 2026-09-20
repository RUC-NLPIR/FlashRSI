"""Resume the frozen recoverable recipe with bounded fast-reply protocol retries."""

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
from scripts import run_searchqa_recoverable_experiment as recoverable  # noqa: E402
from scripts._parallel_plan_migration import atomic_json  # noqa: E402
from scripts._protocol_safe_worker import POLICY, ProtocolSafeLLM  # noqa: E402

ADDED_KEYS = (
    "protocol_recovery_policy",
    "protocol_recovery_sha256",
    "protocol_recovery_entrypoint_sha256",
)


def adopt_protocol_recovery(experiment, config, data, initial_id, fingerprint):
    """The caller holds process.lock; all earlier recipe fields must match."""
    plan_path = experiment / "plan.json"
    old = json.loads(plan_path.read_text())
    if (experiment / "result.json").exists():
        raise ValueError("Cannot upgrade a completed result")
    previous = copy.deepcopy(config)
    for key in ADDED_KEYS:
        if key not in previous.algorithm or key in old["config"]["algorithm"]:
            raise ValueError("Expected unchanged recipe plus protocol recovery")
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
    archive = experiment / "pre-protocol-recovery-plan.json"
    if archive.exists() and json.loads(archive.read_text()) != old:
        raise ValueError("Previous plan archive conflicts")
    if not archive.exists():
        atomic_json(archive, old)
    evidence = {
        "previous_plan": old,
        "upgraded_plan": adopted,
        "added_algorithm_keys": list(ADDED_KEYS),
        "policy": POLICY,
        "reason": (
            "Retry malformed fast-stage replies at most twice using identical prompts "
            "and role configs inside the same logical Worker call. Keep original "
            "caches and separate retry evidence; preserve slow/meta rejection."
        ),
    }
    audit = experiment / "protocol-recovery-migration.json"
    if audit.exists():
        recorded = json.loads(audit.read_text())
        recorded.pop("created_at", None)
        if recorded != evidence:
            raise ValueError("Protocol recovery migration conflicts")
    else:
        atomic_json(
            audit, {**evidence, "created_at": datetime.now(timezone.utc).isoformat()}
        )
    atomic_json(plan_path, adopted)
    return adopted["fingerprint"]


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--adopt-protocol-recovery", action="store_true")
    options, remaining = parser.parse_known_args()
    original_fingerprint = runner._fingerprint
    original_class = recoverable.RecoverableSkillOpt
    original_worker, original_argv = parallel.ContextSafeLLM, sys.argv

    class ExperimentSkillOpt(original_class):
        _defaults = {
            **original_class._defaults,
            "protocol_recovery_policy": POLICY,
            "protocol_recovery_sha256": hashlib.sha256(
                (ROOT / "scripts/_protocol_safe_worker.py").read_bytes()
            ).hexdigest(),
            "protocol_recovery_entrypoint_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }

    def fingerprint(config, data, initial_id):
        value = original_fingerprint(config, data, initial_id)
        experiment = Path(config.run.output_dir).parent
        plan_path = experiment / "plan.json"
        if options.adopt_protocol_recovery and plan_path.exists():
            old = json.loads(plan_path.read_text())
            if old["fingerprint"] != value:
                return adopt_protocol_recovery(
                    experiment, config, data, initial_id, original_fingerprint
                )
        return value

    runner._fingerprint = fingerprint
    recoverable.RecoverableSkillOpt = ExperimentSkillOpt
    parallel.ContextSafeLLM = ProtocolSafeLLM
    sys.argv = [str(Path(__file__)), *remaining]
    try:
        return recoverable.main()
    finally:
        runner._fingerprint = original_fingerprint
        recoverable.RecoverableSkillOpt = original_class
        parallel.ContextSafeLLM, sys.argv = original_worker, original_argv


if __name__ == "__main__":
    raise SystemExit(main())
