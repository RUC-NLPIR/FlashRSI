"""Reject invalid completed edits without changing successful SkillOpt calls.

Fast recovery applies only after all reflection, merge and rank calls finish.
Parallel parsing errors remain terminal: cancelling an unfinished request group
can change its assigned Worker ordinals when cached responses replay faster.
Sequential meta and slow parsing failures can be rejected independently.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from flashrsi.algorithms.skillopt import _dump, _evidence
from flashrsi.algorithms.skillopt import _prompts as prompts
from flashrsi.algorithms.skillopt._patch import _apply_guidance, _field, _PatchError
from scripts._parallel_skillopt import ParallelSkillOpt


class RecoverableSkillOpt(ParallelSkillOpt):
    _defaults = {
        **ParallelSkillOpt._defaults,
        "invalid_patch_policy": "reject_without_score",
    }

    def _check(self):
        super()._check()
        if self.config.invalid_patch_policy != "reject_without_score":
            raise ValueError(
                "algorithm.invalid_patch_policy must be reject_without_score"
            )
        self.config.patch_recovery_sha256 = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()

    def _reject_invalid(
        self, current, error, *, kind, epoch, step=None, patch=None, response=None
    ):
        details = {
            "epoch": epoch,
            "kind": kind,
            "parent_id": current.id,
            "reason": "invalid_patch",
            "error": str(error),
            "accepted": False,
        }
        if step is not None:
            details["step"] = step
        if patch is not None:
            details["patch"] = patch.as_mapping()
        feedback = dict(details)
        if response is not None:
            details["response"] = response
        self._record("decision", details)
        self._rejected = (self._rejected + [feedback])[-5:]

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
        try:
            updated = patch.apply(files, self.config.edit_budget)
        except _PatchError as error:
            self._reject_invalid(
                current, error, kind="fast", epoch=epoch, step=step, patch=patch
            )
            return current, best
        candidate = self._candidate(current, updated)
        return await self._select(
            current, candidate, best, "fast", {**details, "patch": patch.as_mapping()}
        )

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
            reply = await self._ask(prompts.META_SKILL.format(**fields), label="meta")
            try:
                meta_skill = _field(reply, "meta_skill_content")
            except _PatchError as error:
                self._reject_invalid(
                    current, error, kind="meta", epoch=epoch, response=reply
                )
            else:
                self._meta_skill = meta_skill
        if not self.config.use_slow_update:
            return current, best
        reply = await self._ask(prompts.SLOW_UPDATE.format(**fields), label="slow")
        files = self._read_text(current)
        try:
            files = _apply_guidance(files, reply)
        except _PatchError as error:
            self._reject_invalid(
                current, error, kind="slow", epoch=epoch, response=reply
            )
            return current, best
        candidate = self._candidate(current, files)
        return await self._select(current, candidate, best, "slow", {"epoch": epoch})


__all__ = ["RecoverableSkillOpt"]
