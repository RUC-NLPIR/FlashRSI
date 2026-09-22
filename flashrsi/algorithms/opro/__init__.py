"""OPRO: accumulate scored instructions, re-rank them, promote the best once."""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from statistics import mean

from flashrsi.algorithms.opro import _prompts as prompts
from flashrsi.core import Algorithm, Snapshot
from flashrsi.core.snapshot import _matching_components, _validate_path


@dataclass(frozen=True, slots=True)
class _Scored:
    """One evaluated instruction: the unit OPRO accumulates and re-ranks."""

    text: str
    score: float
    snapshot: Snapshot


class OPRO(Algorithm):
    """Search one instruction file by showing the optimizer its own scores.

    The accumulated history is the point: OPRO never moves an incumbent during
    the search, so every instruction it has scored stays in the pool and is
    re-ranked on the next step. Only the final promotion changes the version.
    """

    name = "opro"
    description = "Optimize one instruction file from its scored history."
    evolve_scope = {"prompt"}
    observation_scope = {"prompt"}
    _defaults = {
        # Optional override; by default the target names its own instruction file.
        "instruction_path": None,
        # Published OPRO uses 200 optimizer steps proposing 8 instructions each.
        "max_steps": 200,
        "num_candidates": 8,
        "history_size": 20,
        "score_threshold": 0.1,
        "few_shot_size": 3,
        "max_evidence_chars": 24000,
        "seed": 42,
    }

    async def evolve(self) -> Snapshot:
        train, path = self.benchmark.train, self._path
        current = self.target.snapshot
        results = await self._evaluate(current, train, label="baseline")
        # The starting instruction is row zero of the history OPRO re-ranks.
        self._history = [
            _Scored(
                self._read_text(current).get(path, ""),
                _mean(results, self.benchmark.primary_metric),
                current,
            )
        ]
        self._evidence = results

        for step in range(self.config.max_steps):
            parent = self._best()
            for text in await self._propose(step):
                candidate = self._candidate(parent.snapshot, {path: text})
                # OPRO scores on the training split itself, not a held-out set.
                results = await self._evaluate(candidate, train, label="candidate")
                scored = _Scored(
                    text, _mean(results, self.benchmark.primary_metric), candidate
                )
                # Evaluated before appending, so the evidence follows exactly
                # the instruction _best() will return, ties included.
                if scored.score > self._best().score:
                    self._evidence = results
                self._history.append(scored)

        return self._promote(current)

    def _check(self) -> None:
        if not self.benchmark.train:
            raise ValueError("OPRO requires a non-empty train split")
        # The target names its own instruction file; configuration only overrides
        # it, so a run needs no knowledge of the harness's file layout.
        path = self.config.instruction_path or self.target.instruction_file
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"{self.target.name} declares no instruction_file; set "
                "algorithm.instruction_path to the prompt file OPRO should rewrite"
            )
        _validate_path(path)
        rules = self.target.component_rules
        if _matching_components(path, rules) != {"prompt"}:
            patterns = ", ".join(rules.get("prompt", ()))
            raise ValueError(
                "OPRO rewrites one file in the target's prompt component "
                f"({patterns}); this is not one of them: {path}"
            )
        for key in (
            "max_steps",
            "num_candidates",
            "history_size",
            "few_shot_size",
            "max_evidence_chars",
        ):
            value = self.config[key]
            if type(value) is not int or value < 1:
                raise ValueError(f"algorithm.{key} must be an integer >= 1")
        if type(self.config.seed) is not int:
            raise ValueError("algorithm.seed must be an integer")
        threshold = self.config.score_threshold
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
        ):
            raise ValueError("algorithm.score_threshold must be finite")
        self._path = path

    def _best(self) -> _Scored:
        """The global best so far; ties keep the earlier instruction."""
        return max(self._history, key=lambda item: item.score)

    def _promote(self, current: Snapshot) -> Snapshot:
        """Select once, at the end: the incumbent never moved during the search.

        Every candidate was therefore scored against the same baseline, which is
        why the whole pool is recorded rather than a sequence of accept/reject
        decisions.
        """
        best = self._best()
        self._record(
            "decision",
            {
                "kind": "promote",
                "parent_id": current.id,
                "candidate_id": best.snapshot.id,
                "score": best.score,
                "baseline_score": self._history[0].score,
                "accepted": best.snapshot.id != current.id,
                "history": [
                    {
                        "text": item.text,
                        "score": item.score,
                        "snapshot_id": item.snapshot.id,
                    }
                    for item in self._history
                ],
            },
        )
        if best.snapshot.id != current.id:
            self.target.update(best.snapshot)
        return self.target.snapshot

    async def _propose(self, step: int) -> tuple[str, ...]:
        """Sample this step's novel instructions from the scored history.

        A repeat is dropped rather than resampled, so a step may yield fewer
        than num_candidates instructions.
        """
        prompt = prompts.META.format(
            path=self._path,
            history=self._render_history(),
            evidence=self._render_evidence(step),
        )
        seen = {item.text for item in self._history}
        proposed = []
        for _ in range(self.config.num_candidates):
            text = _instruction(await self._ask(prompt, label="propose"))
            if text and text not in seen:
                seen.add(text)
                proposed.append(text)
        return tuple(proposed)

    def _render_history(self) -> str:
        """The ascending prompt/value trajectory the optimizer reads.

        Upstream hands the optimizer integer score buckets over 0--100 while
        FlashRSI keeps benchmark scores in the canonical 0--1 range, so the
        threshold stays in raw score space and only the rendering bucketizes.
        """
        rows = sorted(
            (
                item
                for item in self._history
                if item.score >= self.config.score_threshold
            ),
            key=lambda item: item.score,
        )[-self.config.history_size :]
        return (
            "".join(
                prompts.ROW.format(text=item.text, score=round(item.score * 100))
                for item in rows
            )
            or prompts.NO_HISTORY
        )

    def _render_evidence(self, step: int) -> str:
        """Show what the leading instruction actually produced, as JSON.

        Upstream optionally shows raw question/answer pairs; FlashRSI has
        trajectories, so the examples come from the scored training run that put
        this instruction at the top of the history. Bounded because one long
        task would otherwise fill the whole context.
        """
        sample = random.Random(self.config.seed + step).sample(
            self._evidence, min(self.config.few_shot_size, len(self._evidence))
        )
        text = json.dumps(
            [
                {
                    "task": item.task.question,
                    "output": item.output,
                    "metrics": dict(item.metrics),
                }
                for item in sample
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        limit = self.config.max_evidence_chars
        return text if len(text) <= limit else text[:limit] + "…"


def _mean(results, metric: str) -> float:
    return mean(item.metrics[metric] for item in results)


def _instruction(reply: str) -> str:
    """Read the new instruction out of a tagged reply.

    The last closed pair wins: a provider that prepends a preamble quoting the
    request back would otherwise be read from the request's own tag. The text
    becomes a file's whole content, so it ends with a newline.
    """
    found = re.findall(r"<INS>(.*?)</INS>", reply, flags=re.DOTALL)
    text = (found[-1] if found else reply).strip()
    return text + "\n" if text else text


__all__ = ["OPRO"]
