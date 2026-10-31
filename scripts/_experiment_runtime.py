"""Run-local concurrency and request replay for the SearchQA experiment runner.

These adapters deliberately stay outside the public framework. Construct them
with the usual role config, including an explicit ``source_dir`` for either
harness, then call ``configure_experiment(run_dir / "cache")``. Replaying an
evolution run from its initial snapshot reuses finished target and Worker calls.
Call ordinals preserve fresh sampling when a run evaluates the same input again.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import yaml

from flashrsi._records import _config_record, _trajectory_record, _write_record
from flashrsi.agents import LLM, ClaudeCode, MiniAgent
from flashrsi.core import Task, Trajectory
from flashrsi.core.agent import _Execution

_CACHE_VERSION = 2


def _encode(value):
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Path):
        return str(value)
    return {"type": "yaml", "value": yaml.safe_dump(value)}


def _digest(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_encode,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _restore(record, task):
    """Use the caller's Task so JSON conversion cannot alter its metadata types."""
    return Trajectory(
        task=task,
        status=record["status"],
        output=record["output"],
        messages=tuple(record["messages"]),
        metrics=record["metrics"],
        error_message=record["error_message"],
        usage=record["usage"],
    )


def _read_cache(path, key, task):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if record["version"] != _CACHE_VERSION or record["key"] != key:
        raise ValueError(f"Incompatible experiment cache: {path}")
    result = _restore(record["trajectory"], task)
    return result if result.status == "finished" else None


def _save_cache(path, record, config):
    """An interrupted write leaves only an ignored temporary file, never a hit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        _write_record(temporary, record, config)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class _LoopState:
    semaphore: asyncio.Semaphore
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)


@dataclass
class _Progress:
    label: str
    total: int
    completed: int = 0
    cached: int = 0

    def finish(self, *, cached):
        self.completed += 1
        self.cached += int(cached)
        # Every real completion is visible; a replay reports only every 50 hits.
        if not cached or self.completed == self.total or self.completed % 50 == 0:
            print(
                f"[{self.label}] {self.completed}/{self.total} finished "
                f"(cached={self.cached}, fresh={self.completed - self.cached})",
                flush=True,
            )


class _ExperimentCache:
    def configure_experiment(self, cache_dir, concurrency=4):
        """Require an explicit experiment-owned directory; no shared default."""
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("experiment concurrency must be a positive integer")
        self._experiment_cache_dir = Path(cache_dir).expanduser().resolve()
        self._experiment_cache_dir.mkdir(parents=True, exist_ok=True)
        self._experiment_concurrency = concurrency
        self._experiment_retry_delay = 3.0
        self._experiment_loop = None
        self._experiment_rollout_ordinal = 0
        self._experiment_worker_ordinal = 0
        self._experiment_worker_calls = 0
        self._experiment_worker_hits = 0
        return self

    def _cache_state(self):
        if not hasattr(self, "_experiment_cache_dir"):
            raise RuntimeError("call configure_experiment with a run-local cache_dir")
        loop = asyncio.get_running_loop()
        if loop is not self._experiment_loop:
            self._experiment_loop = loop
            self._experiment_state = _LoopState(
                asyncio.Semaphore(self._experiment_concurrency)
            )
        return self._experiment_state

    @contextmanager
    def _pinned_execution(self, selected):
        token = self._execution.set(
            _Execution(selected, None, copy.deepcopy(self.config))
        )
        try:
            yield
        finally:
            self._execution.reset(token)

    async def _cached_request(self, *, role, identity, task, invoke):
        state = self._cache_state()
        config = self.config
        config_hash = _digest(_config_record(config))
        snapshot = self._execution.get().snapshot
        snapshot_id = snapshot.id if snapshot is not None else None
        key = _digest(
            {
                "version": _CACHE_VERSION,
                "role": role,
                "agent": self.name,
                "snapshot_id": snapshot_id,
                "config_hash": config_hash,
                "input": identity,
            }
        )
        path = self._experiment_cache_dir / role / self.name / f"{key}.json"
        async with state.locks.setdefault(key, asyncio.Lock()):
            result = _read_cache(path, key, task)
            if result is not None:
                return result, True
            async with state.semaphore:
                for attempt in (1, 2):
                    try:
                        result = await invoke()
                    except Exception as error:
                        result = Trajectory(
                            task=task,
                            status="error",
                            error_message=str(error) or type(error).__name__,
                            messages=(
                                {
                                    "type": "RunConfig",
                                    "config": _config_record(config),
                                    "snapshot_id": snapshot_id,
                                },
                            ),
                        )
                    record = {
                        "version": _CACHE_VERSION,
                        "key": key,
                        "config_hash": config_hash,
                        "snapshot_id": snapshot_id,
                        "trajectory": _trajectory_record(result),
                    }
                    if result.status == "finished":
                        _save_cache(path, record, config)
                        return result, False
                    failure_path = (
                        self._experiment_cache_dir
                        / "errors"
                        / role
                        / self.name
                        / f"{key}-{attempt}-{uuid4().hex}.json"
                    )
                    _save_cache(failure_path, record, config)
                    if attempt == 1:
                        print(
                            f"[{self.name}] request failed; retrying once", flush=True
                        )
                        await asyncio.sleep(self._experiment_retry_delay)
                raise RuntimeError(
                    f"{self.name} request failed twice; trajectory: {failure_path}"
                )


class CachedRollout(_ExperimentCache):
    """Parallelize through the existing single-task Agent rollout contract."""

    async def rollout(self, tasks, *, snapshot=None):
        tasks = tuple(tasks)
        if any(not isinstance(task, Task) for task in tasks):
            raise ValueError("rollout tasks must be Task instances")
        if self._env_runner is None and any(task.env is not None for task in tasks):
            raise NotImplementedError("tasks with env require an execution integration")
        execution = self._execution.get()
        baseline = execution.snapshot if execution is not None else self._snapshot
        if baseline is None:
            raise ValueError("experiment target config requires an explicit source_dir")
        selected = baseline if snapshot is None else snapshot
        self._validate_snapshot(selected, baseline=baseline)
        selected = selected._with_scope(baseline._scope)
        self._cache_state()
        ordinal = self._experiment_rollout_ordinal
        self._experiment_rollout_ordinal += 1
        parent_rollout = super().rollout
        progress = _Progress(self.name, len(tasks))

        async def one(position, task):
            async def invoke():
                return (await parent_rollout((task,), snapshot=selected))[0]

            result, cached = await self._cached_request(
                role="target",
                identity={
                    "rollout_ordinal": ordinal,
                    "position": position,
                    "task": _trajectory_record(Trajectory(task=task))["task"],
                },
                task=task,
                invoke=invoke,
            )
            progress.finish(cached=cached)
            return result

        with self._pinned_execution(selected):
            pending = [
                asyncio.create_task(one(position, task))
                for position, task in enumerate(tasks)
            ]
            try:
                return tuple(await asyncio.gather(*pending))
            except BaseException:
                # Do not leave subprocesses running after a failure/cancellation.
                for future in pending:
                    future.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise


class CachedMiniAgent(CachedRollout, MiniAgent):
    pass


class CachedClaudeCode(CachedRollout, ClaudeCode):
    pass


class CachedLLM(_ExperimentCache, LLM):
    async def run(self, prompt, working_dir=None):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if working_dir is not None:
            raise NotImplementedError("LLM Worker generates text; cannot edit files")
        self._cache_state()
        ordinal = self._experiment_worker_ordinal
        self._experiment_worker_ordinal += 1
        execution = self._execution.get()
        selected = execution.snapshot if execution is not None else self._snapshot
        parent_run = super().run

        async def invoke():
            return await parent_run(prompt)

        with self._pinned_execution(selected):
            result, cached = await self._cached_request(
                role="worker",
                identity={"run_ordinal": ordinal, "prompt": prompt},
                task=None,
                invoke=invoke,
            )
        self._experiment_worker_calls += 1
        self._experiment_worker_hits += int(cached)
        if not cached or self._experiment_worker_calls % 50 == 0:
            print(
                f"[worker] {self._experiment_worker_calls} finished "
                f"(cached={self._experiment_worker_hits})",
                flush=True,
            )
        return result
