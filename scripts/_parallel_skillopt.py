"""Parallel Worker waits without changing the existing SkillOpt request order.

This experimental adapter adds only ``worker_concurrency`` (default 4) and its
own source digest to algorithm.config. Requests start in the same order as the
serial algorithm, so an ordinal-based CachedLLM assigns identical request IDs.
Responses may finish out of order; proposals and merge inputs never do.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from flashrsi.algorithms import SkillOpt
from flashrsi.algorithms.skillopt import _dump
from flashrsi.algorithms.skillopt import _prompts as prompts
from flashrsi.algorithms.skillopt._patch import _SOURCES, _Patch, _ranked


class ParallelSkillOpt(SkillOpt):
    _defaults = {**SkillOpt._defaults, "worker_concurrency": 4}

    def _check(self):
        super()._check()
        concurrency = self.config.worker_concurrency
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("algorithm.worker_concurrency must be a positive integer")
        self.config.parallel_skillopt_sha256 = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()

    async def _ordered_parallel(self, items, invoke, *, prepare=None):
        """Wait for dependencies, then start calls in serial invocation order.

        The gate is released immediately before invoking the inherited Worker.ask or
        _merge. Both enter Worker.run before yielding, preserving its ordinal.
        The semaphore covers the complete request, including response parsing.
        """
        semaphore = asyncio.Semaphore(self.config.worker_concurrency)
        order = asyncio.Condition()
        next_index = 0
        pending = []

        async def run(index, item):
            nonlocal next_index
            if prepare is not None:
                item = await prepare(item, pending)
            async with order:
                await order.wait_for(lambda: next_index == index)
                await semaphore.acquire()
                next_index += 1
                order.notify_all()
            try:
                return await invoke(item)
            finally:
                semaphore.release()

        for index, item in enumerate(items):
            pending.append(asyncio.create_task(run(index, item)))
        try:
            return await asyncio.gather(*pending)
        except BaseException:
            for future in pending:
                future.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise

    async def _reflect(self, snapshot, files, training):
        proposals = {source: [] for source in _SOURCES}
        templates = {
            "failure": prompts.REFLECT_FAILURE,
            "success": prompts.REFLECT_SUCCESS,
        }
        requests = []
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
                requests.append(
                    (
                        source,
                        templates[source].format(
                            files=_dump(files),
                            rules=_dump(list(snapshot.component_rules["skill"])),
                            evidence=_dump(
                                [self._trajectory_evidence(item) for item in group]
                            ),
                            rejected=_dump(self._rejected),
                            meta_skill=self._meta_skill,
                            budget=self.config.edit_budget,
                        ),
                    )
                )

        async def invoke(request):
            source, prompt = request
            return _Patch.parse(await self.worker.ask(prompt), source)

        patches = await self._ordered_parallel(requests, invoke)
        for (source, _), patch in zip(requests, patches, strict=True):
            if patch.edits:
                proposals[source].append(patch)
        return proposals

    async def _consolidate(self, files, proposals):
        # References are either existing Patches or indices of Worker-call nodes.
        # Source order, breadth-first levels and singleton passthroughs exactly
        # match SkillOpt._consolidate; no prompt can run before its inputs exist.
        nodes = []
        roots = []
        for source, group in proposals.items():
            group = list(group)
            while len(group) > 1:
                width = self.config.merge_batch_size
                next_level = []
                for start in range(0, len(group), width):
                    parents = group[start : start + width]
                    if len(parents) == 1:
                        next_level.append(parents[0])
                    else:
                        next_level.append(len(nodes))
                        nodes.append((source, parents))
                group = next_level
            roots.extend(group)

        async def prepare(node, pending):
            source, parents = node
            patches = [
                await pending[parent] if isinstance(parent, int) else parent
                for parent in parents
            ]
            return source, patches

        async def invoke(node):
            source, patches = node
            return await self._merge(files, patches, source)

        results = await self._ordered_parallel(nodes, invoke, prepare=prepare)
        merged = [results[root] if isinstance(root, int) else root for root in roots]
        patch = await self._merge(files, merged, "failure_first")
        if len(patch.edits) > self.config.edit_budget:
            reply = await self.worker.ask(
                prompts.RANK.format(
                    files=_dump(files),
                    edits=_dump(patch.as_mapping()["edits"]),
                    budget=self.config.edit_budget,
                ),
            )
            patch = patch.select(
                _ranked(reply, size=len(patch.edits), limit=self.config.edit_budget)
            )
        return patch
