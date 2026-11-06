"""WebShop text episodes with the published FlashRSI task membership.

Upstream: princeton-nlp/WebShop@64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd.
The full native catalog and scorer stay outside the target harness.
"""

import hashlib
import json
import math
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._native import NativeBenchmark

REVISION = "64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd"
HF_REVISION = "3d89e1589deeb3215c468849ba1b268beb9b0eba"
GOAL_ORDER_SHA256 = "5e43737b4c9bced8f15e41b78b4036c7947744023b96c3aa67d36c7d7d359b86"
_COUNTS = {"train": 150, "dev": 75, "test": 150}
_RANGES = {"train": range(1500, 12087), "dev": range(500, 1500), "test": range(500)}


def _validate(split_bytes, selection_bytes):
    selection = json.loads(selection_bytes)
    if (
        not isinstance(selection, dict)
        or selection.get("profile") != "webshop"
        or selection.get("status") != "task_ids_only"
        or selection.get("counts") != _COUNTS
        or selection.get("upstream_revision") != REVISION
        or selection.get("upstream_goal_order_sha256") != GOAL_ORDER_SHA256
    ):
        raise ValueError("Unexpected WebShop profile, upstream revision or goal order")
    if hashlib.sha256(split_bytes).hexdigest() != selection.get(
        "experiment_split_ids_sha256"
    ):
        raise ValueError("WebShop split_ids SHA-256 mismatch")
    splits = json.loads(split_bytes)
    if not isinstance(splits, dict) or splits.keys() != _COUNTS.keys():
        raise ValueError("WebShop requires train/dev/test splits")
    for role, ids in splits.items():
        if (
            not isinstance(ids, list)
            or len(ids) != _COUNTS[role]
            or any(
                not isinstance(task_id, str)
                or not re.fullmatch(r"webshop-[0-9]{5}", task_id)
                or int(task_id.removeprefix("webshop-")) not in _RANGES[role]
                for task_id in ids
            )
            or len(set(ids)) != len(ids)
        ):
            raise ValueError(f"Invalid WebShop task membership for {role}")
    return splits


def _check_native(root, selection):
    files = (
        "data/items_shuffle.json",
        "data/items_ins_v2.json",
        "data/items_human_ins.json",
    )
    missing = [name for name in files if not (root / name).is_file()]
    if not any(
        p.is_file() for p in (root / "search_engine/indexes").glob("segments_*")
    ):
        missing.append("search_engine/indexes/segments_*")
    if missing:
        raise ValueError("Missing full WebShop resources: " + ", ".join(missing))
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != selection["upstream_revision"]:
        raise ValueError("WebShop checkout must match the pinned upstream revision")
    if subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", head, "--", "web_agent_site"],
        check=False,
    ).returncode:
        raise ValueError(
            "WebShop native source has local changes; use the pinned source"
        )
    baseline = root / "baseline_models/data/human_goals.json"
    if (
        hashlib.sha256(baseline.read_bytes()).hexdigest()
        != selection["upstream_goal_order_sha256"]
    ):
        raise ValueError("WebShop baseline goal order SHA-256 mismatch")


def _prepare(config, download):
    from huggingface_hub import hf_hub_download

    source = config.pop("dataset")
    payload = {
        name: Path(hf_hub_download(filename="webshop/" + name, **download)).read_bytes()
        for name in ("experiment_split_ids.json", "experiment_selection.json")
    }
    config["_prepared_splits"] = _validate(
        payload["experiment_split_ids.json"], payload["experiment_selection.json"]
    )
    config["_prepared_source"] = {
        **source,
        "counts": _COUNTS,
        "selection": json.loads(payload["experiment_selection.json"]),
        "resources": "full local native catalog and Lucene index",
    }
    return config


class WebShop(NativeBenchmark):
    name = "webshop"
    description = "WebShop text shopping with native search, click and reward."
    primary_metric = "reward"
    metadata = MappingProxyType(
        {
            "source": "https://github.com/princeton-nlp/WebShop",
            "revision": REVISION,
            "scoring": "native-reward",
            "observation_mode": "text",
            "catalog": "full",
        }
    )

    def __init__(self, config):
        super().__init__(config)
        self.max_steps = self.config.get("max_steps", 100)
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("WebShop max_steps must be a positive integer")
        self.seed = self.config.get("seed", 42)
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError("WebShop seed must be an integer in [0, 2**32)")
        for key in ("native_root", "native_python"):
            value = self.config.get(key)
            if not isinstance(value, (str, Path)) or not str(value).strip():
                raise ValueError(
                    f"WebShop requires benchmark.{key}; see docs/webshop.md"
                )
            setattr(self, key, Path(value).expanduser().resolve())
        if (
            self.config.get("split", "auto") != "auto"
            or self.config.get("split_counts") is not None
        ):
            raise ValueError(
                "WebShop preserves published HF split membership; use split: auto"
            )

    def _iter_tasks(self):
        splits = self.config.get("_prepared_splits")
        if splits is None:
            path = self.config.get("data_path")
            if not isinstance(path, (str, Path)):
                raise ValueError(
                    "Select the HF webshop profile or a prepared data_path directory"
                )
            root = Path(path).expanduser().resolve()
            splits = _validate(
                (root / "experiment_split_ids.json").read_bytes(),
                (root / "experiment_selection.json").read_bytes(),
            )
        _check_native(
            self.native_root,
            {
                "upstream_revision": REVISION,
                "upstream_goal_order_sha256": GOAL_ORDER_SHA256,
            },
        )
        goals = json.loads(
            (self.native_root / "baseline_models/data/human_goals.json").read_bytes()
        )
        self.metadata = MappingProxyType(
            {
                **self.metadata,
                "seed": self.seed,
                "max_steps": self.max_steps,
                "goal_order_sha256": GOAL_ORDER_SHA256,
            }
        )
        for role, ids in splits.items():
            for task_id in ids:
                index = int(task_id.removeprefix("webshop-"))
                yield self._register(
                    {"instruction": goals[index], "index": index, "revision": REVISION},
                    role,
                    task_id,
                    "Complete this WebShop shopping task. The environment provides the instruction and current page.",
                    env=self.name,
                    goal_index=index,
                )

    def grade(self, trajs):
        graded = []
        for trajectory in trajs:
            self._row_for(trajectory)
            reward = 0.0
            if trajectory.status == "finished":
                event = trajectory.messages[-1] if trajectory.messages else {}
                expected = {
                    "type": "WebShopVerifier",
                    "revision": REVISION,
                    "task_id": trajectory.task.task_id,
                    "task_checksum": trajectory.task.metadata["task_checksum"],
                    "seed": self.seed,
                    "max_steps": self.max_steps,
                }
                if any(event.get(k) != v for k, v in expected.items()):
                    raise ValueError(
                        "WebShop requires a final native host verifier event"
                    )
                reward = event.get("reward")
                if (
                    type(reward) not in (int, float)
                    or not math.isfinite(reward)
                    or not 0 <= reward <= 1
                    or type(event.get("steps")) is not int
                    or not 0 <= event["steps"] <= self.max_steps
                    or type(event.get("purchased")) is not bool
                    or (reward > 0 and not event["purchased"])
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(event.get("goal_checksum", ""))
                    )
                ):
                    raise ValueError("Invalid WebShop native result")
            graded.append(
                replace(
                    trajectory,
                    metrics={
                        **trajectory.metrics,
                        "reward": float(reward),
                        "success": float(reward == 1),
                    },
                )
            )
        return tuple(graded)
