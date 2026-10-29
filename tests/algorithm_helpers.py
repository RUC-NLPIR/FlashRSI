"""Offline benchmark shared by the imported algorithm tests."""

from dataclasses import replace

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.core import Benchmark, Task

PATHS = {MiniAgent: "prompts/system.md", ClaudeCode: "CLAUDE.md"}


class MemoryBenchmark(Benchmark):
    name = "memory"
    description = "Offline disjoint splits."
    primary_metric = "accuracy"
    metadata = {}

    def load(self):
        if self._splits is None:
            self._splits = {
                "train": tuple(
                    Task(f"train-{i}", f"train-{i}", "right") for i in range(2)
                ),
                "dev": (Task("dev-only", "dev-only", "right"),),
                "test": (Task("test-only", "test-only", "right"),),
            }
        return self._splits

    def grade(self, results):
        return tuple(
            replace(
                item,
                metrics={
                    "accuracy": float(
                        item.output == "right" and item.status == "finished"
                    )
                },
            )
            for item in results
        )
