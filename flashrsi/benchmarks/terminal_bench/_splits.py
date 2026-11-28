"""Load an explicit Terminal task partition without resampling or reordering."""

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType


def _manifest_splits(tasks, config):
    if (
        config.get("split", "auto") != "auto"
        or config.get("split_counts") is not None
        or config.get("limit") is not None
        or config.get("_prepared_splits") is not None
        or any(k.startswith("evolution_") and v is not None for k, v in config.items())
    ):
        raise ValueError(
            "Terminal split_manifest requires split: auto without split_counts, "
            "limit, prepared dataset splits, or evolution_* overrides"
        )
    value = config["split_manifest"]
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("benchmark.split_manifest must be a JSON file path")
    path = Path(value).expanduser()
    try:
        membership = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read Terminal split_manifest: {path}") from exc
    roles = ("train", "dev", "test")
    if not isinstance(membership, Mapping) or set(membership) != set(roles):
        raise ValueError("Terminal split_manifest must declare train, dev and test")
    seen = set()
    for role in roles:
        ids = membership[role]
        if not isinstance(ids, list) or any(
            not isinstance(task_id, str) or not task_id.strip() for task_id in ids
        ):
            raise ValueError(
                f"Terminal split_manifest.{role} must be a list of task IDs"
            )
        for task_id in ids:
            if task_id in seen:
                raise ValueError(
                    f"Duplicate task ID in Terminal split_manifest: {task_id}"
                )
            seen.add(task_id)
    if not seen:
        raise ValueError("Terminal split_manifest must select at least one task")

    selected = {}
    for task in tasks:
        if task.task_id in seen:
            if task.task_id in selected:
                raise ValueError(f"Duplicate Terminal task in dataset: {task.task_id}")
            selected[task.task_id] = task
    missing = seen - selected.keys()
    if missing:
        raise ValueError(
            "Terminal split_manifest tasks are missing: " + ", ".join(sorted(missing))
        )
    return MappingProxyType(
        {
            role: tuple(
                replace(
                    selected[task_id],
                    metadata={**selected[task_id].metadata, "source_split": role},
                )
                for task_id in membership[role]
            )
            for role in roles
        }
    )
