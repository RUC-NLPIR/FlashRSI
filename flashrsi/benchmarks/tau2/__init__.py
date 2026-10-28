"""tau² text domains on sierra-research/tau2-bench v1.0.1.

Runtime and data are pinned to fc0055dc4e0a316c3f83133267fbd6faaa770992,
the same maintained release used by tau3_banking. Native task splits and
reward criteria are preserved; this is not the original 2025 data revision.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._git import _download_git
from flashrsi.benchmarks._tau import (
    _GIT_URL,
    _UPSTREAM_REVISION,
    _UPSTREAM_TAG,
    _TauBenchmark,
)
from flashrsi.core import Task


class Tau2Benchmark(_TauBenchmark):
    name = "tau2"
    description = "tau² airline, retail and telecom native text simulations."
    metadata = MappingProxyType(
        {"source": _GIT_URL, "revision": _UPSTREAM_REVISION, "tag": _UPSTREAM_TAG}
    )

    def __init__(self, config):
        super().__init__()
        self.config = config["benchmark"] if "benchmark" in config else config
        if self.config.get("name", self.name) != self.name:
            raise ValueError("Tau2Benchmark requires benchmark.name: tau2")
        self.domain = self.config.get("domain", "telecom")
        if self.domain not in ("airline", "retail", "telecom"):
            raise ValueError("tau2 domain must be airline, retail or telecom")
        self.task_split = self.config.get("task_split", "base")
        if not isinstance(self.task_split, str) or not self.task_split:
            raise ValueError("tau2 task_split must name an upstream task set")
        if self.config.get("mode", "text") != "text":
            raise ValueError("tau2 currently supports mode: text only")
        self.metadata = MappingProxyType(
            {
                **self.metadata,
                "domain": self.domain,
                "task_split": self.task_split,
                "mode": "text",
                "aggregation": "single_trial_mean_reward",
            }
        )

    def _iter_tasks(self):
        data_path = self.config.get("data_path")
        if data_path is None:
            root = _download_git(_GIT_URL, _UPSTREAM_REVISION, ["data/tau2"])
            domain = root / "data" / "tau2" / "domains" / self.domain
        else:
            if not isinstance(data_path, (str, Path)) or not str(data_path).strip():
                raise ValueError("tau2 data_path must name one native domain directory")
            domain = Path(data_path).expanduser().resolve()
            self.metadata = MappingProxyType(
                {**self.metadata, "source": "local", "data_path": str(domain)}
            )
        database = "db.toml" if self.domain == "telecom" else "db.json"
        if not (domain / database).is_file():
            raise ValueError(f"tau2 {self.domain} domain is missing {database}")
        if self.domain == "telecom":
            if not (domain / "user_db.toml").is_file():
                raise ValueError("tau2 telecom domain is missing user_db.toml")
            main = (domain / "main_policy.md").read_text(encoding="utf-8")
            support = (domain / "tech_support_manual.md").read_text(encoding="utf-8")
            policy = f"<main_policy>\n{main}\n</main_policy>\n<tech_support_policy>\n{support}\n</tech_support_policy>"
        else:
            policy = (domain / "policy.md").read_text(encoding="utf-8")
        payload = (domain / "tasks.json").read_bytes()
        file_checksum = hashlib.sha256(payload).hexdigest()
        rows = json.loads(payload)
        splits = json.loads((domain / "split_tasks.json").read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not isinstance(splits, Mapping):
            raise ValueError("tau2 needs a task list and a split_tasks mapping")
        if self.task_split not in splits:
            raise ValueError(f"Unknown tau2 task_split; available: {', '.join(splits)}")
        selected = splits[self.task_split]
        if not isinstance(selected, list) or any(
            not isinstance(i, str) for i in selected
        ):
            raise ValueError("tau2 task split must contain string IDs")
        selected = set(selected)
        train_ids, test_ids = set(splits.get("train", ())), set(splits.get("test", ()))
        if train_ids & test_ids:
            raise ValueError("tau2 native train/test task IDs overlap")
        seen = set()
        for row in rows:
            task_id = row.get("id") if isinstance(row, Mapping) else None
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("tau2 task requires a nonempty string id")
            if task_id in seen:
                raise ValueError(f"tau2 contains duplicate task id: {task_id}")
            seen.add(task_id)
            if task_id not in selected:
                continue
            criteria = row.get("evaluation_criteria") or {}
            needs_judge = "NL_ASSERTION" in criteria.get("reward_basis", ()) and bool(
                criteria.get("nl_assertions")
            )
            if needs_judge and not self.config.get("judge", {}).get("llm", {}).get(
                "model_name"
            ):
                raise ValueError(
                    "Selected tau2 tasks require an independent "
                    "benchmark.judge.llm.model_name for native NL assertions"
                )
            yield Task(
                task_id=task_id,
                question=policy,
                env=str(domain),
                metadata={
                    "domain": self.domain,
                    "task_path": "tasks.json",
                    "task_file_checksum": file_checksum,
                    "task_checksum": hashlib.sha256(
                        json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                    "native_task_id": task_id,
                    "source_split": "train"
                    if task_id in train_ids
                    else "test"
                    if task_id in test_ids
                    else "unassigned",
                    "task_split": self.task_split,
                    "simulation_seed": self.config.get("seed", 0),
                    "reward_basis": tuple(criteria.get("reward_basis", ())),
                    "needs_judge": needs_judge,
                },
            )
        if selected - seen:
            raise ValueError("tau2 split references unknown task IDs")


__all__ = ["Tau2Benchmark"]
