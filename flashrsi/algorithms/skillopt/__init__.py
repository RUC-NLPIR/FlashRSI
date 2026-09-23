"""SkillOpt: separate reflection, bounded file edits, and held-out selection."""

from __future__ import annotations

import json
import random

from flashrsi._records import _trajectory_record
from flashrsi.algorithms.skillopt import _prompts as prompts
from flashrsi.algorithms.skillopt._patch import (
    _SOURCES,
    _apply_guidance,
    _field,
    _Patch,
    _ranked,
)
from flashrsi.core import Algorithm, Snapshot


class SkillOpt(Algorithm):
    """Evolve skill files through the same public API for every target harness.

    Worker calls produce JSON proposals. SkillOpt applies those proposals to a
    checkout, so a text LLM and an Agent Worker use exactly the same protocol.
    Both fast and slow candidates must strictly improve the held-out score.
    """

    name = "skillopt"
    description = "Reflect on successes and failures to evolve reusable skills."
    evolve_scope = {"skill"}
    observation_scope = {"skill"}
    _defaults = {
        "num_epochs": 4,
        "batch_size": 40,
        "reflection_minibatch_size": 8,
        "edit_budget": 4,
        "merge_batch_size": 8,
        "seed": 42,
        "max_steps": None,
        "success_threshold": 0.0,
        "use_slow_update": True,
        "use_meta_skill": True,
        "slow_update_samples": 20,
    }
    _ranges = {
        "num_epochs": (int, 1),
        "batch_size": (int, 1),
        "reflection_minibatch_size": (int, 1),
        "edit_budget": (int, 1),
        # A merge combines at least two proposals.
        "merge_batch_size": (int, 2),
        "seed": int,
        "max_steps": (int | None, 1),
        "success_threshold": float,
        "use_slow_update": bool,
        "use_meta_skill": bool,
        "slow_update_samples": (int, 1),
    }

    async def evolve(self) -> Snapshot:
        train, dev = self.benchmark.train, self.benchmark.dev
        current = self.target.snapshot
        self._rejected, self._meta_skill = [], ""
        best = self._score(await self._evaluate(current, dev, label="baseline"))
        previous_epoch = None
        steps = 0

        for epoch in range(self.config.num_epochs):
            tasks = list(train)
            random.Random(self.config.seed + epoch).shuffle(tasks)
            for start in range(0, len(tasks), self.config.batch_size):
                if self.config.max_steps is not None and steps >= self.config.max_steps:
                    return self.target.snapshot
                steps += 1
                batch = tuple(tasks[start : start + self.config.batch_size])
                current, best = await self._fast_update(
                    current, best, batch, epoch, steps
                )

            if previous_epoch is not None and (
                self.config.use_slow_update or self.config.use_meta_skill
            ):
                current, best = await self._slow_update(
                    previous_epoch, current, best, epoch
                )
            previous_epoch = current
        return self.target.snapshot

    def _check(self) -> None:
        if not self.benchmark.train or not self.benchmark.dev:
            raise ValueError("SkillOpt requires non-empty train and dev splits")

    async def _fast_update(self, current, best, batch, epoch, step):
        training = await self._evaluate(current, batch, label="train")
        files = self._read_text(current)
        proposals = await self._reflect(current, files, training)
        patch = await self._consolidate(files, proposals)
        details = {"epoch": epoch, "step": step}
        if not patch.edits:
            self._record(
                "decision",
                {**details, "kind": "fast", "reason": "empty_patch", "accepted": False},
            )
            return current, best
        updated = patch.apply(files, self.config.edit_budget)
        candidate = self._candidate(current, updated)
        return await self._select(
            current, candidate, best, "fast", {**details, "patch": patch.as_mapping()}
        )

    async def _reflect(self, snapshot, files, training):
        proposals = {source: [] for source in _SOURCES}
        templates = {
            "failure": prompts.REFLECT_FAILURE,
            "success": prompts.REFLECT_SUCCESS,
        }
        size = self.config.reflection_minibatch_size
        for offset in range(0, len(training), size):
            groups = {source: [] for source in _SOURCES}
            for trajectory in training[offset : offset + size]:
                succeeded = (
                    trajectory.status == "finished"
                    and trajectory.metrics[self.benchmark.primary_metric]
                    > self.config.success_threshold
                )
                groups["success" if succeeded else "failure"].append(trajectory)
            for source, group in groups.items():
                if not group:
                    continue
                reply = await self._ask(
                    templates[source].format(
                        files=_dump(files),
                        rules=_dump(list(snapshot.component_rules["skill"])),
                        evidence=_dump([_evidence(item) for item in group]),
                        rejected=_dump(self._rejected),
                        meta_skill=self._meta_skill,
                        budget=self.config.edit_budget,
                    ),
                    label=source,
                )
                patch = _Patch.parse(reply, source)
                if patch.edits:
                    proposals[source].append(patch)
        return proposals

    async def _consolidate(self, files, proposals):
        merged = []
        for source, group in proposals.items():
            while len(group) > 1:
                width = self.config.merge_batch_size
                next_level = []
                for start in range(0, len(group), width):
                    merged_patch = await self._merge(
                        files, group[start : start + width], source
                    )
                    next_level.append(merged_patch)
                group = next_level
            merged.extend(group)
        patch = await self._merge(files, merged, "failure_first")
        if len(patch.edits) > self.config.edit_budget:
            reply = await self._ask(
                prompts.RANK.format(
                    files=_dump(files),
                    edits=_dump(patch.as_mapping()["edits"]),
                    budget=self.config.edit_budget,
                ),
                label="rank",
            )
            patch = patch.select(
                _ranked(reply, size=len(patch.edits), limit=self.config.edit_budget)
            )
        return patch

    async def _merge(self, files, patches, source):
        if not patches:
            return _Patch()
        if len(patches) == 1:
            return patches[0]
        reply = await self._ask(
            prompts.MERGE.format(
                files=_dump(files),
                kind=source,
                patches=_dump([patch.as_mapping() for patch in patches]),
            ),
            label="merge",
        )
        return _Patch.parse(reply, source if source in _SOURCES else "")

    async def _slow_update(self, previous, current, best, epoch):
        sample = random.Random(self.config.seed + epoch * 2000).sample(
            list(self.benchmark.train),
            min(self.config.slow_update_samples, len(self.benchmark.train)),
        )
        before = await self._evaluate(previous, sample, label="comparison_before")
        after = await self._evaluate(current, sample, label="comparison_after")
        comparison = [
            {"previous": _evidence(a), "current": _evidence(b)}
            for a, b in zip(before, after, strict=True)
        ]
        fields = {
            "previous": _dump(self._read_text(previous)),
            "current": _dump(self._read_text(current)),
            "comparison": _dump(comparison),
        }
        if self.config.use_meta_skill:
            self._meta_skill = _field(
                await self._ask(prompts.META_SKILL.format(**fields), label="meta"),
                "meta_skill_content",
            )
        if not self.config.use_slow_update:
            return current, best
        reply = await self._ask(prompts.SLOW_UPDATE.format(**fields), label="slow")
        files = _apply_guidance(self._read_text(current), reply)
        candidate = self._candidate(current, files)
        return await self._select(current, candidate, best, "slow", {"epoch": epoch})

    async def _select(self, current, candidate, best, kind, details):
        if candidate.files == current.files:
            self._record(
                "decision",
                {**details, "kind": kind, "reason": "no_change", "accepted": False},
            )
            return current, best
        evaluated = await self._evaluate(
            candidate, self.benchmark.dev, label="candidate_dev"
        )
        score = self._score(evaluated)
        accepted = score > best
        self._record(
            "decision",
            {
                **details,
                "kind": kind,
                "parent_id": current.id,
                "candidate_id": candidate.id,
                "score": score,
                "baseline_score": best,
                "accepted": accepted,
            },
        )
        if accepted:
            self.target.update(candidate)
            return self.target.snapshot, score
        if kind == "fast":
            self._rejected = (
                self._rejected + [{"score": score, "patch": details["patch"]}]
            )[-5:]
        return current, best


def _evidence(trajectory):
    record = _trajectory_record(trajectory)
    record["messages"] = [
        message for message in trajectory.messages if message.get("type") != "RunConfig"
    ]
    return record


def _dump(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        default=lambda item: dict(item) if hasattr(item, "items") else str(item),
    )


__all__ = ["SkillOpt"]
