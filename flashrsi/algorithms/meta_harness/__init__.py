"""Meta-Harness: let a coding Worker retrieve full search history from files.

Upstream: https://github.com/stanford-iris-lab/meta-harness
Commit: 8123ccabe2b19fa1123090b2e5f1bacc20963ce8
Reference: reference_examples/{text_classification,terminal_bench_2}/meta_harness.py
"""

from __future__ import annotations

import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi.algorithms.meta_harness import _prompts as prompts
from flashrsi.core import Algorithm, Snapshot
from flashrsi.core.snapshot import discard_runtime_files


class MetaHarness(Algorithm):
    """Search whole harnesses using selectively retrieved code, scores and traces.

    Every evaluated version remains readable, including regressions. The Worker
    chooses what to inspect and reuse; the loop imposes no parent-selection rule.
    """

    name = "meta_harness"
    description = "Optimize harnesses with filesystem access to full search history."
    evolve_scope = {"*"}
    _defaults = {"max_steps": 20}
    _ranges = {"max_steps": (int, 1)}

    async def evolve(self) -> Snapshot:
        # Filesystem feedback is essential even for direct Python use. Reuse the
        # framework's records in a temporary run rather than serialize them again.
        run_dir = self._run_dir
        with ExitStack() as resources:
            if run_dir is None:
                self._run_dir = Path(resources.enter_context(TemporaryDirectory()))
                for name in ("snapshots", "trajectories", "working"):
                    (self._run_dir / name).mkdir()
            try:
                seed, dev = self.target.snapshot, self.benchmark.dev
                results = await self._evaluate(seed, dev, label="baseline")
                baseline_score = best_score = results.score
                best, versions = seed, [seed]
                self._record(
                    "scores",
                    {"snapshot_id": seed.id, "score": results.score},
                )

                for step in range(self.config.max_steps):
                    candidate = await self._propose(seed, versions, step)
                    if candidate is None:
                        continue
                    results = await self._evaluate(candidate, dev, label="candidate")
                    versions.append(candidate)
                    improved = results.score > best_score
                    self._record(
                        "decision",
                        {
                            "kind": "admit",
                            "step": step,
                            "parent_id": candidate.parent_id,
                            "candidate_id": candidate.id,
                            "score": results.score,
                            "improved_best": improved,
                        },
                    )
                    if improved:
                        best, best_score = candidate, results.score

                return self._promote(
                    seed,
                    best,
                    score=best_score,
                    baseline_score=baseline_score,
                    candidate_ids=[snapshot.id for snapshot in versions],
                )
            finally:
                self._run_dir = run_dir

    async def _propose(self, seed, versions, step) -> Snapshot | None:
        """Expose historical native checkouts and records beside the editable seed.

        Nested references travel with working_dir to a container Worker. They
        disappear before commit, so neither history nor logs become agent files.
        """
        with seed.check_out(working_dir=self._run_dir / "working") as directory:
            with (
                TemporaryDirectory(prefix="history-", dir=directory) as temporary,
                ExitStack() as sources,
            ):
                history = Path(temporary)
                index = []
                for snapshot in versions:
                    source = sources.enter_context(
                        snapshot.check_out(working_dir=history / "sources")
                    )
                    index.append(
                        {
                            "snapshot_id": snapshot.id,
                            "parent_id": snapshot.parent_id,
                            "directory": source.relative_to(history).as_posix(),
                        }
                    )
                (history / "index.json").write_text(
                    json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                shutil.copytree(
                    self._run_dir / "trajectories", history / "trajectories"
                )
                await self.worker.edit(
                    directory,
                    prompts.PROPOSE.format(
                        step=step,
                        history=history.relative_to(directory).as_posix(),
                        rules=json.dumps(dict(self.target.component_rules)),
                    ),
                )
            discard_runtime_files(directory)
            try:
                candidate = self._commit(seed, directory)
            except ValueError as error:
                problem = str(error)
            else:
                if seed.changed_paths(candidate):
                    return candidate
                problem = "the harness was left unchanged"
            self._record(
                "decision", {"kind": "decline", "step": step, "problem": problem}
            )
            return None

    def _check(self) -> None:
        if not self.benchmark.dev:
            raise ValueError("Meta-Harness requires a non-empty dev split")
        if self.worker.config.get("type", "agent") != "agent":
            raise ValueError("Meta-Harness requires algorithm.worker.type: agent")


__all__ = ["MetaHarness"]
