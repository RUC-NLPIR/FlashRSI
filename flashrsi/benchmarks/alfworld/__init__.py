"""ALFWorld text tasks, using native game files and environment success.

Upstream: https://github.com/alfworld/alfworld (PyPI alfworld==0.4.2).
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from flashrsi.benchmarks._native import NativeBenchmark

VERSION = "0.4.2"
TEXTWORLD_VERSION = "1.7.0"
TASK_TYPES = (
    "pick_and_place_simple",
    "look_at_obj_in_light",
    "pick_clean_then_place_in_recep",
    "pick_heat_then_place_in_recep",
    "pick_cool_then_place_in_recep",
    "pick_two_obj_and_place",
)
SPLITS = {"train": "train", "valid_seen": "dev", "valid_unseen": "test"}


class ALFWorld(NativeBenchmark):
    name = "alfworld"
    description = "ALFWorld text-only interactive planning with native success scoring."
    primary_metric = "success"
    metadata = MappingProxyType(
        {
            "source": "https://github.com/alfworld/alfworld",
            "version": VERSION,
            "textworld_version": TEXTWORLD_VERSION,
            "execution": "native-textworld-local-tools",
            "scoring": "native-won",
        }
    )

    def __init__(self, config):
        super().__init__(config)
        self.max_steps = self.config.get("max_steps", 50)
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("ALFWorld max_steps must be a positive integer")
        self.admissible_commands = self.config.get("admissible_commands", False)
        if type(self.admissible_commands) is not bool:
            raise ValueError("ALFWorld admissible_commands must be a boolean")
        self.task_types = self.config.get("task_types", list(TASK_TYPES))
        if (
            not isinstance(self.task_types, list)
            or not self.task_types
            or any(t not in TASK_TYPES for t in self.task_types)
            or len(set(self.task_types)) != len(self.task_types)
        ):
            raise ValueError(
                "ALFWorld task_types must be unique native task type names"
            )
        if self.config.get("mode", "text") != "text":
            raise ValueError("ALFWorld only supports mode: text")
        seed = self.config.get("seed", 0)
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("ALFWorld seed must be an integer in [0, 2**32)")
        self._games = {}

    def _iter_tasks(self):
        data = self.config.get("data_path")
        if not isinstance(data, (str, Path)) or not str(data).strip():
            raise ValueError(
                "ALFWorld requires local benchmark.data_path; see docs/alfworld.md"
            )
        root = Path(data).expanduser().resolve()
        if (root / "json_2.1.1").is_dir():
            root /= "json_2.1.1"
        if not any((root / split).is_dir() for split in SPLITS):
            raise ValueError(
                "ALFWorld data_path must contain native train/valid_seen/valid_unseen directories"
            )
        self.metadata = MappingProxyType(
            {
                **self.metadata,
                "data_path": str(root),
                "data_mode": "local-native",
                "native_split_roles": SPLITS,
                "max_steps": self.max_steps,
                "seed": self.config.get("seed", 0),
                "admissible_commands": self.admissible_commands,
                "domain_randomization": False,
                "task_types": tuple(self.task_types),
            }
        )
        for native_split, role in SPLITS.items():
            for trajectory in sorted((root / native_split).rglob("traj_data.json")):
                relative = trajectory.parent.relative_to(root).as_posix()
                # Match AlfredTWEnv's supported, prevalidated game selection.
                if "movable" in relative or "Sliced" in relative:
                    continue
                row = json.loads(trajectory.read_text(encoding="utf-8"))
                if row["task_type"] not in self.task_types:
                    continue
                game = trajectory.with_name("game.tw-pddl")
                if not game.is_file():
                    continue
                game_bytes = game.read_bytes()
                if not json.loads(game_bytes).get("solvable", False):
                    continue
                checksum = hashlib.sha256(game_bytes).hexdigest()
                task_id = "alfworld/" + relative
                self._games[task_id] = (game, checksum)
                # The environment supplies the goal and initial observation at
                # reset; trajectory annotations/plans never enter the prompt.
                yield self._register(
                    {"trajectory": row, "game_sha256": checksum},
                    role,
                    task_id,
                    f"Complete ALFWorld text task {task_id}. "
                    "The environment provides the goal and initial observation.",
                    env=self.name,
                    native_split=native_split,
                    task_type=row["task_type"],
                    game_sha256=checksum,
                )

    def grade(self, trajs):
        graded = []
        for trajectory in trajs:
            self._row_for(trajectory)
            success = 0.0
            if trajectory.status == "finished":
                task = trajectory.task
                event = trajectory.messages[-1] if trajectory.messages else {}
                expected = {
                    "type": "ALFWorldVerifier",
                    "task_id": task.task_id,
                    "task_checksum": task.metadata["task_checksum"],
                    "game_sha256": task.metadata["game_sha256"],
                    "version": VERSION,
                    "textworld_version": TEXTWORLD_VERSION,
                    "max_steps": self.max_steps,
                    "seed": self.config.get("seed", 0),
                    "admissible_commands": self.admissible_commands,
                }
                if any(event.get(k) != v for k, v in expected.items()):
                    raise ValueError(
                        "ALFWorld requires a final native host verifier event"
                    )
                if (
                    type(event.get("won")) is not bool
                    or type(event.get("steps")) is not int
                    or not 0 <= event["steps"] <= self.max_steps
                ):
                    raise ValueError("Invalid ALFWorld native result")
                success = float(event["won"])
            graded.append(
                replace(trajectory, metrics={**trajectory.metrics, "success": success})
            )
        return tuple(graded)
