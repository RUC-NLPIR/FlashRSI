"""AHE: a coding agent edits the whole harness, and must predict what that does.

    until the score clears target_score, or the step budget runs out:
        read each rollout, then synthesize one diagnosis across them
        hand the harness to the Evolve Agent as a directory; it edits freely
          but must declare every file it touched and which tasks it will flip
        roll the edit out and check each declaration against what happened
        keep the edit, and hand the verdicts to the next Evolve Agent

AHE is the one method here that evolves the harness as a *directory* rather
than a named component, which is why its scope is every component the target
declares and why the edit arrives as a filesystem effect rather than as text.
The paper's contribution is the second half: an edit that cannot say what it
will fix cannot later be found wrong, so the manifest is read before the
candidate is committed and graded after it is measured.

Upstream: https://github.com/china-qijizhifeng/agentic-harness-engineering
Commit: 8b2a55d97590363fe50c3cc6b5e833b020a4bb4c
Port reference: FlashRSI 5efe9b438483710060183c6c3ecbc5062b410a58.
"""

from __future__ import annotations

from pathlib import Path

from flashrsi.algorithms import _replies
from flashrsi.algorithms.ahe import _manifest as protocol
from flashrsi.algorithms.ahe import _prompts as prompts
from flashrsi.algorithms.ahe._manifest import Manifest, ManifestError
from flashrsi.core import Algorithm, Snapshot
from flashrsi.core.snapshot import discard_runtime_files


class AHE(Algorithm):
    """Falsifiable harness engineering by a coding agent.

    Every other method here proposes text and lets the algorithm write it. AHE
    hands over the checkout itself, so what comes back is a directory, and the
    only thing tying that edit to a reason is the manifest the agent must write
    alongside it.

    Nothing is gated on score. Every well-formed edit is kept, and its per-change
    verdicts go to the next Evolve Agent, which decides whether to keep, improve
    or roll each one back. That is the point: a score can only say an edit did
    not help, while a verdict says which promise it broke, so the search reasons
    about its own past edits instead of discarding them.
    """

    name = "ahe"
    description = "Edit the whole harness, and hold each edit to its prediction."
    # Every component the target declares: a harness defect may need a file
    # that does not exist yet, and only the target knows how it lays them out.
    evolve_scope = {"*"}
    _defaults = {
        "max_steps": 10,
        "target_score": 1.0,
        "use_debugger": True,
        "debugger_max_tasks": 90,
        "max_evidence_chars": 30000,
    }
    _ranges = {
        "max_steps": (int, 1),
        "target_score": float,
        "use_debugger": bool,
        "debugger_max_tasks": (int, 1),
        "max_evidence_chars": (int, 1),
    }

    async def evolve(self) -> Snapshot:
        train = self.benchmark.train
        current = self.target.snapshot
        results = await self._evaluate(current, train, label="baseline")
        self._previous: dict = {}
        self._declined: list[dict] = []

        for step in range(self.config.max_steps):
            if results.score >= self.config.target_score:
                break
            candidate, manifest = await self._edit(current, results, step)
            if manifest is None:
                continue
            measured = await self._evaluate(candidate, train, label="candidate")
            self._judge(current, results, candidate, measured, manifest, step)
            self.target.update(candidate)
            current, results = candidate, measured
        return self.target.snapshot

    def _judge(self, current, results, candidate, measured, manifest, step):
        """Grade the edit against what the rollout actually did, and keep it.

        The verdicts are state, not just a record: the next Evolve Agent reads
        them, which is what makes this a search that reasons about its own
        past edits rather than one that scores them away.
        """
        attribution = protocol.attribute(results.per_task, measured.per_task)
        self._previous = {
            **protocol.evaluate(manifest, attribution),
            "manifest": manifest.as_record(),
            "rollback_sources": self._sources(current, manifest),
        }
        self._record(
            "decision",
            {
                "step": step,
                "kind": "keep",
                "parent_id": current.id,
                "candidate_id": candidate.id,
                "accepted": True,
                "parent_score": results.score,
                "candidate_score": measured.score,
                **self._previous,
            },
        )

    async def _edit(self, current, results, step):
        """Let the Evolve Agent edit a checkout, and hold it to its manifest.

        The manifest is read before the candidate is committed, because an
        agent that cannot justify its own diff should not produce a candidate
        at all -- leaving the block without committing discards the checkout.
        """
        evidence = await self._diagnose(results)
        working = self._run_dir / "working" if self._run_dir else None
        with current.check_out(working_dir=working) as directory:
            reply = await self.worker.edit(
                directory,
                prompts.EVOLVE.format(
                    rules=self._evidence([dict(current.component_rules)]),
                    evidence=evidence,
                ),
            )
            # The Evolve Agent ran its own tools in there, so it also left what
            # those tools produce; commit refuses those paths outright.
            discard_runtime_files(directory)
            try:
                candidate = self._commit(current, directory)
            except ValueError as error:
                return self._decline(current, step, f"rejected edit: {error}")
            # What the edit really did, as the Snapshot's own comparison rather
            # than the Agent's account of it. A commit always mints a new id,
            # because the parent is part of the hash, so an untouched checkout
            # is recognized by its files and not by its identity.
            changed = current.changed_paths(candidate)
            if not changed:
                return self._decline(current, step, "the harness was left unchanged")
            try:
                manifest = Manifest.parse(_replies.tagged(reply, "MANIFEST"), changed)
            except ManifestError as error:
                # An unfalsifiable edit is not a candidate. The reason goes to
                # the next Evolve Agent rather than ending the run, so a reply
                # in the wrong shape costs one step instead of the experiment.
                return self._decline(current, step, str(error))
        return candidate, manifest

    def _decline(self, current, step, problem: str):
        self._declined = (self._declined + [{"step": step, "problem": problem}])[-4:]
        self._record(
            "decision",
            {
                "step": step,
                "kind": "decline",
                "parent_id": current.id,
                "problem": problem,
                "accepted": False,
            },
        )
        return current, None

    async def _diagnose(self, results):
        """Layer one rollout into the evidence the Evolve Agent is shown.

        Layered means three depths: which tasks failed, each rollout in full,
        and -- the paper's first stage -- a debugger's reading of them. Without
        the debugger the Evolve Agent sees only traces and has to do the causal
        work itself while it edits.
        """
        scores = results.per_task
        rows = {item.task.task_id: self._trajectory_evidence(item) for item in results}
        evidence = {
            "failures": sorted(key for key, value in scores.items() if value <= 0),
            "successes": sorted(key for key, value in scores.items() if value > 0),
            "previous_change_evaluation": self._previous,
            "declined_edits": self._declined,
            "rollouts": rows,
        }
        if self.config.use_debugger:
            # Failures first, so a task cap spends the debugger on the rollouts
            # that have something to explain.
            ordered = sorted(rows, key=lambda task_id: (scores[task_id] > 0, task_id))
            reports = {
                task_id: await self.worker.ask(
                    prompts.DEBUGGER_TASK.format(
                        task_id=task_id, evidence=self._evidence([rows[task_id]])
                    )
                )
                for task_id in ordered[: self.config.debugger_max_tasks]
            }
            evidence["agent_debugger_reports"] = reports
            if reports:
                evidence["agent_debugger_overview"] = await self.worker.ask(
                    prompts.DEBUGGER_OVERVIEW.format(reports=self._evidence([reports]))
                )
        return self._evidence([evidence])

    def _sources(self, parent: Snapshot, manifest: Manifest) -> dict:
        """The prior content of every declared path, bounded.

        The next Evolve Agent is asked to consider rolling a change back, so it
        needs to see what it would be rolling back to. Its checkout holds only
        the edited version. A path that did not exist is said so explicitly:
        undoing that edit deletes a file rather than restoring text.
        """
        limit = max(1, self.config.max_evidence_chars // max(1, len(manifest.changes)))
        sources = {}
        for change in manifest.changes:
            entry = parent.files.get(change.path)
            if entry is None:
                sources[change.path] = {"existed": False, "content": None}
                continue
            try:
                text = entry.content.decode("utf-8")
            except UnicodeDecodeError:
                sources[change.path] = {"existed": True, "content": None}
                continue
            sources[change.path] = {"existed": True, "content": text[:limit]}
        return sources

    def _commit(self, baseline: Snapshot, directory: Path) -> Snapshot:
        """Version the edited directory, refusing one that leaked a credential.

        ``_candidate`` covers an algorithm that computed the new text; here the
        bytes came from a process this algorithm does not control, so they are
        checked. The scan reads exactly what would be versioned, and the
        Snapshot is still only in memory until it has passed.
        """
        candidate = baseline.commit(directory)
        secrets = self._runtime_secrets()
        for path, entry in candidate.files.items():
            if baseline.files.get(path) == entry:
                continue
            text = entry.content.decode("utf-8", errors="ignore")
            if any(secret in text for secret in secrets):
                raise ValueError(f"candidate contains a runtime credential: {path}")
        self._save_snapshot(candidate)
        return candidate

    def _check(self) -> None:
        if not self.benchmark.train:
            raise ValueError("AHE requires a non-empty train split")
        seen = set()
        for task in self.benchmark.train:
            if task.task_id in seen:
                raise ValueError(
                    "AHE attributes each edit to individual tasks and needs "
                    f"unique task_id values: {task.task_id}"
                )
            seen.add(task.task_id)
        # The Evolve Agent works in a checkout, which a text Worker cannot do.
        # This is the configured role, not the harness behind it, so the check
        # holds for every Agent Worker without naming any of them.
        if self.worker.config.get("type", "agent") != "agent":
            raise ValueError(
                "AHE edits the harness as a directory and needs a Worker that "
                "can edit files; set algorithm.worker.type to 'agent'"
            )


__all__ = ["AHE"]
