"""Audit an explicit serial-to-parallel scheduling migration under process.lock.

The caller owns the experiment's existing exclusive lock. This helper preserves
the serial plan and writes migration evidence before returning an adopted plan;
the caller then atomically publishes that plan. No cache or trajectory is edited.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flashrsi._records import _config_record

PARALLEL_KEYS = (
    "worker_concurrency",
    "parallel_skillopt_sha256",
    "parallel_entrypoint_sha256",
    "parallel_migration_sha256",
    "context_recovery_sha256",
)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def adopt_serial_plan(experiment, config, data, initial_id, fingerprint):
    """Return a new plan only when *all* old recipe material is unchanged."""
    experiment = Path(experiment)
    current = json.loads((experiment / "plan.json").read_text())
    if (experiment / "result.json").exists():
        raise ValueError(
            "Cannot migrate a completed result; preserve its serial recipe"
        )
    baseline = copy.deepcopy(config)
    for key in PARALLEL_KEYS:
        if key not in baseline.algorithm or key in current["config"]["algorithm"]:
            raise ValueError(
                "Expected an unchanged serial recipe and parallel metadata"
            )
        del baseline.algorithm[key]
    old_fingerprint = fingerprint(baseline, data, initial_id)
    if (
        old_fingerprint != current["fingerprint"]
        or _config_record(baseline) != current["config"]
        or initial_id != current["initial_snapshot"]
    ):
        raise ValueError("Serial recipe/source/data changed; migration refused")
    adopted = {
        **current,
        "fingerprint": fingerprint(config, data, initial_id),
        "config": _config_record(config),
    }
    archive = experiment / "serial-plan.json"
    if archive.exists():
        if json.loads(archive.read_text()) != current:
            raise ValueError("Existing serial plan archive differs; migration refused")
    else:
        atomic_json(archive, current)
    evidence = {
        "version": 1,
        "reason": (
            "Parallel independent Worker waits with identical invocation order; "
            "only after context overflow, retry without numeric thinking_tokens "
            "progress events. Successful serial requests and raw traces are unchanged."
        ),
        "serial_plan": current,
        "parallel_plan": adopted,
        "cache_policy": "Reuse only original matching invocation keys; no cache edits",
        "allowed_added_algorithm_fields": list(PARALLEL_KEYS),
    }
    audit = experiment / "parallel-migration.json"
    if audit.exists():
        saved = json.loads(audit.read_text())
        saved.pop("created_at", None)
        if saved != evidence:
            raise ValueError("Existing scheduling migration differs; migration refused")
    else:
        atomic_json(
            audit,
            {**evidence, "created_at": datetime.now(timezone.utc).isoformat()},
        )
    return adopted
