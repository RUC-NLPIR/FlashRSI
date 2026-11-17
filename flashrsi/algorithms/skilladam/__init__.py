"""SkillAdam, adapted from https://github.com/ruc-datalab/SkillAdam
at b6c9640f7a9e0d5e3a500c25bc4e6369eeca78f1.
"""

import json
import random
from statistics import variance

from flashrsi.core import Algorithm, Snapshot

from ._proposal import apply_proposal


class SkillAdam(Algorithm):
    """Track issues and past attempts across rounds of skill editing.

    Volatile per-task validation gains shrink the next round's edit budget,
    including when the validation gate rejects the current attempt.
    """

    name = "skilladam"
    description = "Evolve a skill with issue memory and a variance-driven edit budget."
    evolve_scope = {"skill"}
    observation_scope = {"skill"}
    _defaults = {
        "skill_path": None,
        "max_iterations": 4,
        "batch_size": 8,
        "seed": 42,
        "base_budget": 4,
        "min_budget": 1,
        "beta": 0.9,
        "v_max": 0.25,
        "max_evidence_chars": 30000,
    }
    _ranges = {
        "skill_path": str | None,
        "max_iterations": (int, 1),
        "batch_size": (int, 1),
        "seed": int,
        "base_budget": (int, 1),
        "min_budget": (int, 1),
        "beta": (float, 0),
        "v_max": (float, 0),
        "max_evidence_chars": (int, 1),
    }

    async def evolve(self) -> Snapshot:
        cfg = self.config
        current = self.target.snapshot
        memory = {}
        v_ema = 0.0
        rng = random.Random(cfg.seed)
        train = tuple(self.benchmark.train)
        # FlashRSI uses a fixed dev split. Keep the incumbent's paired scores
        # so sampling noise on a rerun cannot replace a better saved version.
        baseline = await self._evaluate(
            current, self.benchmark.dev, label="baseline_dev"
        )
        for step in range(1, cfg.max_iterations + 1):
            ratio = min(v_ema / cfg.v_max, 1.0) if cfg.v_max else 0.0
            budget = max(cfg.min_budget, round(cfg.base_budget * (1 - ratio)))
            batch = rng.sample(train, min(cfg.batch_size, len(train)))
            traces = await self._evaluate(current, batch, label="train")
            text = current.files[cfg.skill_path].content.decode("utf-8")
            prompt = (
                "Improve the supplied skill using the training trajectories and issue memory. "
                "Reuse a stable label for each recurring problem. Mark it open or resolved "
                "based on observed behavior of the current skill. Record the evidence. "
                "Use previous attempts and gate outcomes when choosing an approach. "
                "Return one JSON object with issues and edits arrays. Each issue has label, "
                "status and evidence. Each edit has label (existing or newly reported issue), "
                "approach, before (unique exact excerpt) and after (replacement text). "
                "Edits apply in order. Use an empty edits array when no change is warranted."
                f"\nEdit budget: {budget}\nSkill path: {cfg.skill_path}\nSkill:\n{text}"
                f"\nIssue memory:\n{json.dumps(memory, ensure_ascii=False)}"
                f"\nTraining trajectories:\n{self._evidence(self._trajectory_evidence(t) for t in traces)}"
            )
            reply = await self.worker.ask(prompt)
            decision = {
                "step": step,
                "parent_id": current.id,
                "edit_budget": budget,
                "accepted": False,
                "v_ema_before": v_ema,
            }
            try:
                updated, issues, attempts = apply_proposal(reply, text, budget, memory)
            except ValueError as error:
                self._record(
                    "decision", {**decision, "reason": str(error), "v_ema": v_ema}
                )
                continue

            for label, status, evidence in issues:
                entry = memory.setdefault(label, {"attempts": []})
                entry.update(status=status, evidence=evidence)
            if updated != text:
                candidate = self._candidate(current, {cfg.skill_path: updated})
                trial = await self._evaluate(
                    candidate, self.benchmark.dev, label="candidate_dev"
                )
                deltas = [
                    score - baseline.per_task[key]
                    for key, score in trial.per_task.items()
                ]
                sigma_sq = variance(deltas) if len(deltas) > 1 else 0.0
                v_ema = cfg.beta * v_ema + (1 - cfg.beta) * sigma_sq
                accepted = trial.score > baseline.score
                decision.update(
                    candidate_id=candidate.id,
                    accepted=accepted,
                    score=trial.score,
                    baseline_score=baseline.score,
                    variance=sigma_sq,
                )
                if accepted:
                    self.target.update(candidate)
                    current = candidate
                    baseline = trial
            else:
                decision["reason"] = "no_change"
            for label, approach in attempts:
                memory[label]["attempts"].append(
                    {
                        "step": step,
                        "approach": approach,
                        "gate_accepted": decision["accepted"],
                    }
                )
            self._record(
                "decision", {**decision, "v_ema": v_ema, "issue_memory": memory}
            )
        return current

    def _check(self):
        if not self.benchmark.train or not self.benchmark.dev:
            raise ValueError("SkillAdam requires non-empty train and dev splits")
        if len({t.task_id for t in self.benchmark.dev}) != len(self.benchmark.dev):
            raise ValueError("SkillAdam requires unique dev task IDs")
        if self.config.beta > 1 or self.config.min_budget > self.config.base_budget:
            raise ValueError(
                "SkillAdam requires beta <= 1 and min_budget <= base_budget"
            )
        skills = [
            p
            for p in self._read_text(self.target.snapshot)
            if p.lower().endswith(".md")
        ]
        path = self.config.skill_path
        if path is None and len(skills) == 1:
            path = skills[0]
        if path not in skills:
            raise ValueError(
                "SkillAdam requires an existing Markdown skill; set algorithm.skill_path"
            )
        self.config.skill_path = path
