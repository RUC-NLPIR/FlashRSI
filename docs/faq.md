# FAQ

## What is a Snapshot?

An immutable, executable version of the harness's declared resource files. It records the resources and lineage; a run records the evolution or evaluation process and may contain many Snapshots. See [Framework & Snapshot](./development/framework.md).

## Can I test an intermediate version?

Yes. Pass its saved JSON file to `flashrsi evaluate --snapshot PATH` with a compatible destination configuration. See [Snapshot evaluation](./guide/evaluation.md).

## Does every experiment need Docker?

The local QA quickstart does not. Harbor and several native task environments do. Check the [benchmark requirements](./benchmark-quickstart.md) before installing system services and benchmark data.

## Why are Target and Worker configured separately?

The Target solves tasks; the Worker proposes or performs edits. They may use different models, providers, tools, and budgets. Configure `agent.llm` and `algorithm.worker.llm` independently; see [Configuration](./guide/configuration.md).

## Does a registered adapter imply a reproduced result?

No. Registration exposes the adapter to the runner. Its integration guide states the supported track, environment, migration differences, and validation status. Completed runs should include their actual configuration, resource version, split, and trajectories.

## How do I add another benchmark, algorithm, or harness?

- [Add a benchmark](./development/benchmark.md): tasks, environments, and grading.
- [Add an algorithm](./development/algorithm.md): search scope, policy, and selection.
- [Add a harness](./development/harness.md): tagged resources and native execution.

## How should I cite FlashRSI?

The project currently provides this citation. Check the [project README](../README.md#citation) for the final paper metadata:

```bibtex
@misc{jin2026flashrsi,
  title  = {FlashRSI: A Unified Framework for Agent Self-Improvement},
  author = {Jiajie Jin and Yuze Li and Yuyang Hu and Guanting Dong and
            Xiaoxi Li and Xinyu Yang and Zhicheng Dou and Yutao Zhu},
  year   = {2026},
}
```

## What is the license?

The framework uses [Apache-2.0](../LICENSE). Check each benchmark and upstream harness for its own license and distribution conditions.
