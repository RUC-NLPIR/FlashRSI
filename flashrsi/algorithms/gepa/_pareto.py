"""GEPA's Pareto frontier and pruning over measured per-task scores.

These are the search rules; version identity and file contents belong to Snapshot.

Upstream: https://github.com/gepa-ai/gepa
Commit: 0632cdb5dcc052e690eab439e1b4a7e3e9cfe407
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def frontier(population: Sequence[Mapping]) -> dict[str, set[int]]:
    """Map each validation task to the members that score best on it."""
    front: dict[str, set[int]] = {}
    best: dict[str, float] = {}
    for index, member in enumerate(population):
        for task_id, value in member["per_task"].items():
            if task_id not in best or value > best[task_id]:
                best[task_id] = value
                front[task_id] = {index}
            elif value == best[task_id]:
                front[task_id].add(index)
    return front


def prune(
    front: Mapping[str, set[int]], population: Sequence[Mapping]
) -> dict[str, set[int]]:
    """Drop dominated members that no task uniquely depends on.

    Without this, a member that ties on every task it appears in inflates the
    sampling weight of a region of the frontier it does not actually own.
    """
    active = set().union(*front.values()) if front else set()
    weakest_first = sorted(
        active, key=lambda index: (population[index]["score"], index)
    )
    while True:
        for index in weakest_first:
            if index not in active:
                continue
            covering = [members for members in front.values() if index in members]
            if all((members & active) - {index} for members in covering):
                active.remove(index)
                break
        else:
            return {task: members & active for task, members in front.items()}
