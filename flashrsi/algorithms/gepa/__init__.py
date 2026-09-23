"""GEPA: reflect on a parent's own failures, screen cheaply, keep the frontier."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping

from flashrsi.algorithms.gepa import _population as pop
from flashrsi.algorithms.gepa import _prompts as prompts
from flashrsi.algorithms.gepa._population import Member
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
            Member(
                index=0,
                snapshot=current,
                text=self._read_text(current).get(self._path, ""),
                per_task=self._per_task(results),
                score=self._score(results),
            )
        ]
        self._metric_calls = len(dev)

        iteration = 0
        while self._metric_calls + cost <= budget:
            await self._iterate(train, dev, iteration)
            iteration += 1

        best = self._population[pop.best_index(self._population)]
        return self._promote(
            current,
            best.snapshot,
            path=self._path,
            score=best.score,
            baseline_score=self._population[0].score,
            metric_calls=self._metric_calls,
            population=[
                {
                    "index": member.index,
                    "snapshot_id": member.snapshot.id,
                    "parents": list(member.parents),
                    "text": member.text,
                    "score": member.score,
                    "per_task": dict(member.per_task),
                }
                for member in self._population
            ],
        )

    async def _iterate(self, train, dev, iteration: int) -> None:
        """One reflective mutation: select, propose, screen, admit."""
        rng = random.Random(self.config.seed + iteration)
        parent = self._select(rng)
        minibatch = tuple(
            rng.sample(
                list(train), min(self.config.reflection_minibatch_size, len(train))
            )
        )
        details = {"iteration": iteration, "parent_index": parent.index}

        # One rollout serves both purposes: it screens the parent and is the
        # evidence the reflection reads.
        before = await self._evaluate(parent.snapshot, minibatch, label="parent")
        self._metric_calls += len(minibatch)

        text = await self._propose(parent, before)
        # An empty reply is a Worker or parsing problem, not a search outcome;
        # keep it distinct from a proposal that simply repeated the parent.
        if not text:
            return self._reject(details, "empty_proposal")
        if text == parent.text:
            return self._reject(details, "unchanged_instruction")
        if any(text == member.text for member in self._population):
            return self._reject(details, "duplicate_instruction")

        candidate = self._candidate(parent.snapshot, {self._path: text})
        after = await self._evaluate(candidate, minibatch, label="candidate_minibatch")
        self._metric_calls += len(minibatch)
        metric = self.benchmark.primary_metric
        # Screen on the minibatch before spending a whole validation pass.
        if sum(item.metrics[metric] for item in after) <= sum(
            item.metrics[metric] for item in before
        ):
            return self._reject(details, "failed_minibatch_screen")

        results = await self._evaluate(candidate, dev, label="candidate_dev")
        self._metric_calls += len(dev)
        self._admit(candidate, text, parent, results, details)

    async def _propose(self, parent: Member, evidence) -> str:
        """Reflect on the parent's own trajectories and rewrite the instruction."""
        reply = await self._ask(
            prompts.REFLECT.format(
                path=self._path,
                instruction=parent.text,
                evidence=self._render_evidence(evidence),
            ),
            label="propose",
        )
        return _instruction(reply)

    def _select(self, rng: random.Random) -> Member:
        """Pick the parent to mutate: the aggregate best, or from the frontier."""
        population = self._population
        if self.config.candidate_selection_strategy == "current_best":
            return population[pop.best_index(population)]
        front = pop.prune(pop.frontier(population), population)
        # Sampling the union weights a member by how many tasks it owns.
        weighted = [index for members in front.values() for index in sorted(members)]
        if not weighted:
            return population[pop.best_index(population)]
        return population[rng.choice(weighted)]

    def _admit(self, snapshot, text, parent, results, details) -> None:
        """Add a candidate to the population.

        Admission is not promotion: GEPA promotes the aggregate best once, after
        the budget is spent, so the population holds members that never became
        the current version.
        """
        member = Member(
            index=len(self._population),
            snapshot=snapshot,
            text=text,
            per_task=self._per_task(results),
            score=self._score(results),
            parents=(parent.index,),
        )
        self._population.append(member)
        self._record(
            "decision",
            {
                **details,
                "kind": "admit",
                "parent_id": parent.snapshot.id,
                "candidate_id": snapshot.id,
                "score": member.score,
                "parent_score": parent.score,
                "accepted": True,
            },
        )

    def _reject(self, details, reason: str) -> None:
        self._record("decision", {**details, "kind": "reject", "reason": reason})

    def _per_task(self, results) -> Mapping[str, float]:
        metric = self.benchmark.primary_metric
        return {item.task.task_id: item.metrics[metric] for item in results}

    def _render_evidence(self, results) -> str:
        """Show what the parent's instruction actually produced, as JSON.

        Upstream shows each input, the assistant's response and the feedback on
        it; FlashRSI has trajectories, so the scores are that feedback. Bounded
        because one long task would otherwise fill the whole context.
        """
        text = json.dumps(
            [
                {
                    "task": item.task.question,
                    "output": item.output,
                    "metrics": dict(item.metrics),
                }
                for item in results
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        limit = self.config.max_evidence_chars
        return text if len(text) <= limit else text[:limit] + "…"

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


def _instruction(reply: str) -> str:
    """Read the new instruction out of a fenced reply.

    Upstream asks for it "within ``` blocks"; providers prepend a preamble
    anyway, so the last *closed* block wins. Closed matters: the sentence asking
    for one ends in a lone ``` of its own, and a reply that quotes the request
    back would otherwise be read from that dangling marker.

    An opening fence may carry a language tag — one word on its own line, which
    is what tells it apart from prose that began on the fence line itself. The
    text becomes a file's whole content, so it ends with a newline.
    """
    blocks = reply.split("```")
    closed = range(1, len(blocks) - 1, 2)
    if not closed:
        text = reply.strip()
    else:
        body = blocks[closed[-1]]
        tag, newline, rest = body.partition("\n")
        text = (rest if newline and len(tag.split()) <= 1 else body).strip()
    return text + "\n" if text else text


__all__ = ["GEPA"]
