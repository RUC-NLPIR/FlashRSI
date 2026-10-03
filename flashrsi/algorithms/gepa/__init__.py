"""GEPA: reflect on a parent's own failures, screen cheaply, keep the frontier."""

from __future__ import annotations

import random

from flashrsi.algorithms import _replies
from flashrsi.algorithms.gepa import _pareto as pareto
from flashrsi.algorithms.gepa import _prompts as prompts
from flashrsi.core import Algorithm, Snapshot


class GEPA(Algorithm):
    """Genetic-Pareto search over one instruction file.

    Evolving only the aggregate best gets stuck, so a candidate that wins a
    *single* validation task stays selectable: every admission here reads the
    per-task scores rather than their mean. A candidate must first beat its
    parent on the reflection minibatch, which keeps the expensive validation
    pass for proposals that already showed an improvement.

    Upstream rotates over the modules of a compound system. Each harness here
    names a single instruction file, so this port rewrites that one file and
    leaves the rotation out rather than shipping an unused generalisation.
    """

    name = "gepa"
    description = "Evolve instructions by Pareto search over per-task scores."
    evolve_scope = {"prompt"}
    observation_scope = {"prompt"}
    _defaults = {
        # None scales the budget to the data; see _budget. One fixed number is
        # either wasteful or far too small depending on the validation split.
        "max_metric_calls": None,
        "reflection_minibatch_size": 3,
        "candidate_selection_strategy": "pareto",
        "max_evidence_chars": 24000,
        "seed": 42,
        # Upstream's system-aware merge is not part of this migration.
        "use_merge": False,
    }
    _ranges = {
        "max_metric_calls": (int | None, 1),
        "reflection_minibatch_size": (int, 1),
        "candidate_selection_strategy": ("pareto", "current_best"),
        "max_evidence_chars": (int, 1),
        "seed": int,
        "use_merge": bool,
    }

    async def evolve(self) -> Snapshot:
        train, dev = self.benchmark.train, self.benchmark.dev
        current = self.target.snapshot
        budget, cost = self._resolved_budget

        results = await self._evaluate(current, dev, label="baseline")
        self._population = [
            {
                "snapshot_id": current.id,
                "text": self._read_text(current).get(self._path, ""),
                "per_task": dict(results.per_task),
                "score": results.score,
            }
        ]
        self._snapshots = {current.id: current}
        self._metric_calls = len(dev)

        iteration = 0
        while self._metric_calls + cost <= budget:
            await self._iterate(train, dev, iteration)
            iteration += 1

        best = max(self._population, key=lambda row: row["score"])
        indices = {row["snapshot_id"]: i for i, row in enumerate(self._population)}
        # Legacy indices are a log format, not a second version graph.
        population = []
        for i, row in enumerate(self._population):
            parent_id = self._snapshots[row["snapshot_id"]].parent_id
            population.append(
                {
                    "index": i,
                    "snapshot_id": row["snapshot_id"],
                    "parents": [indices[parent_id]] if parent_id in indices else [],
                    "text": row["text"],
                    "score": row["score"],
                    "per_task": row["per_task"],
                }
            )
        return self._promote(
            current,
            self._snapshots[best["snapshot_id"]],
            path=self._path,
            score=best["score"],
            baseline_score=self._population[0]["score"],
            metric_calls=self._metric_calls,
            population=population,
        )

    async def _iterate(self, train, dev, iteration: int) -> None:
        """One reflective mutation: select, propose, screen, admit."""
        rng = random.Random(self.config.seed + iteration)
        parent_index = self._select(rng)
        parent = self._population[parent_index]
        snapshot = self._snapshots[parent["snapshot_id"]]
        minibatch = tuple(
            rng.sample(
                list(train), min(self.config.reflection_minibatch_size, len(train))
            )
        )
        details = {"iteration": iteration, "parent_index": parent_index}

        # One rollout serves both purposes: it screens the parent and is the
        # evidence the reflection reads.
        before = await self._evaluate(snapshot, minibatch, label="parent")
        self._metric_calls += len(minibatch)

        text = await self._propose(parent, before)
        # An empty reply is a Worker or parsing problem, not a search outcome;
        # keep it distinct from a proposal that simply repeated the parent.
        reason = None
        if not text:
            reason = "empty_proposal"
        elif text == parent["text"]:
            reason = "unchanged_instruction"
        elif any(text == row["text"] for row in self._population):
            reason = "duplicate_instruction"
        if reason:
            self._record("decision", {**details, "kind": "reject", "reason": reason})
            return

        candidate = self._candidate(snapshot, {self._path: text})
        after = await self._evaluate(candidate, minibatch, label="candidate_minibatch")
        self._metric_calls += len(minibatch)
        # Screen on the minibatch before spending a whole validation pass. Both
        # ran the same tasks, so comparing the means compares the sums.
        if after.score <= before.score:
            self._record(
                "decision",
                {**details, "kind": "reject", "reason": "failed_minibatch_screen"},
            )
            return

        results = await self._evaluate(candidate, dev, label="candidate_dev")
        self._metric_calls += len(dev)
        self._snapshots[candidate.id] = candidate
        self._population.append(
            {
                "snapshot_id": candidate.id,
                "text": text,
                "per_task": dict(results.per_task),
                "score": results.score,
            }
        )
        self._record(
            "decision",
            {
                **details,
                "kind": "admit",
                "parent_id": snapshot.id,
                "candidate_id": candidate.id,
                "score": results.score,
                "parent_score": parent["score"],
                "accepted": True,
            },
        )

    async def _propose(self, parent: dict, evidence) -> str:
        """Reflect on the parent's own trajectories and rewrite the instruction.

        Upstream shows each input, the assistant's response and the feedback on
        it; FlashRSI has trajectories, so the scores are that feedback. It asks
        for the rewrite "within ``` blocks", which is what ``fenced`` reads.
        """
        reply = await self.worker.ask(
            prompts.REFLECT.format(
                path=self._path,
                instruction=parent["text"],
                evidence=self._evidence(
                    {
                        "task": item.task.question,
                        "output": item.output,
                        "metrics": dict(item.metrics),
                    }
                    for item in evidence
                ),
            ),
        )
        return _replies.fenced(reply)

    def _select(self, rng: random.Random) -> int:
        """Pick a population slot: the aggregate best, or from the frontier."""
        population = self._population
        if self.config.candidate_selection_strategy == "pareto":
            front = pareto.prune(pareto.frontier(population), population)
            # Keep the original task order and sorted slots: RNG draws depend on it.
            weighted = [i for members in front.values() for i in sorted(members)]
            if weighted:
                return rng.choice(weighted)
        return max(range(len(population)), key=lambda i: population[i]["score"])

    def _check(self) -> None:
        if not self.benchmark.train or not self.benchmark.dev:
            raise ValueError("GEPA requires non-empty train and dev splits")
        seen = set()
        for task in self.benchmark.dev:
            if task.task_id in seen:
                raise ValueError(
                    "GEPA scores dev tasks individually and needs unique "
                    f"task_id values: {task.task_id}"
                )
            seen.add(task.task_id)
        self._path = self._instruction_path()
        if self.config.use_merge:
            raise ValueError(
                "GEPA's system-aware merge is not implemented; set "
                "algorithm.use_merge to false"
            )
        # Resolved here, before the runner creates an experiment directory, so
        # an unusable budget is reported like any other configuration error.
        self._resolved_budget = self._budget(self.benchmark.train, self.benchmark.dev)

    def _budget(self, train, dev) -> tuple[int, int]:
        """Resolve the rollout budget and check that one iteration fits in it.

        An iteration screens the parent on the minibatch, screens the candidate
        on the same tasks, then evaluates it on the whole dev split.
        """
        minibatch = min(self.config.reflection_minibatch_size, len(train))
        cost = 2 * minibatch + len(dev)
        needed = len(dev) + cost
        budget = self.config.max_metric_calls
        if budget is None:
            # The budget is a property of how much data there is, so one fixed
            # number is wrong for every split but one: the baseline pass plus
            # ten reflective iterations.
            budget = max(100, len(dev) + 10 * cost)
        if budget < needed:
            raise ValueError(
                f"algorithm.max_metric_calls={budget} cannot complete one "
                f"iteration; this run needs at least {needed}"
            )
        return budget, cost


__all__ = ["GEPA"]
