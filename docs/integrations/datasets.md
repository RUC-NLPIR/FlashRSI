# Datasets & splits

A benchmark may load a pinned dataset, a local file, a task archive, or a native simulator. Check its source, revision, and split policy before running an experiment.

## Start with local data

The [quickstart](../index.md) ships 12 SearchQA records in [quickstart.jsonl](../../examples/data/quickstart.jsonl). Its configured fractions produce six train, three dev, and three test questions.

```yaml
benchmark:
  name: searchqa
  data_path: ./examples/data/quickstart.jsonl
  split:
    train: 0.5
    dev: 0.25
    test: 0.25
  seed: 42
```

Local file formats and supported fields vary by adapter. Use the [benchmark configuration index](../benchmark-quickstart.md) rather than assuming every benchmark accepts the same schema.

## Choose and report a split

Train supplies evolution tasks; dev supports selection where the method uses it; test assesses the selected version. Keep task IDs disjoint across the roles.

Use `benchmark.split` or `split_counts` where supported. For collections with only a native evaluation pool, report any custom partition as an experimental split. It is not automatically an official leaderboard evaluation.

Some methods can use a separate evolution source. The [integration notes](../reference.md#dataset-and-evolution-sources) describe the source revisions and how each adapter separates evolution tasks from evaluation data.

## Inspect sources and releases

The public project links its datasets at [RUC-NLPIR/FlashRSI](https://huggingface.co/datasets/RUC-NLPIR/FlashRSI). Individual adapters and preparation cards record their actual source repositories and pinned revisions; use those records to reproduce a run.

| Card | What it documents |
| --- | --- |
| [Bundle overview](../../scripts/dataset_card.md) | Named configurations, task archives, distribution, and source licenses. |
| [SearchQA](../../scripts/searchqa_dataset_card.md) | QA records, source, preparation, and splits. |
| [HotpotQA](../../scripts/hotpotqa_dataset_card.md) | Multi-hop QA schema and source splits. |
| [τ³ Banking](../../scripts/tau3_banking_dataset_card.md) | Task index and native domain archive. |

Task indexes do not replace runtime dependencies. Docker layers, private corpora, search services, simulator models, and verifier packages may need separate preparation. Dataset licenses are benchmark-specific; the framework's Apache-2.0 license does not replace them.
