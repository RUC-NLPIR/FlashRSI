---
pretty_name: FlashRSI Benchmarks
language:
  - en
task_categories:
  - question-answering
size_categories:
  - 1K<n<10K
license: other
license_name: authorized-by-maintainer
license_link: https://huggingface.co/datasets/jinjiajie/EvoOS/blob/2e2d97feb4a3394fd577017024e6d9f3176e9fbc/benchmarks/searchqa/README.md
configs:
  - config_name: searchqa
    data_files:
      - split: train
        path: searchqa/train.parquet
      - split: dev
        path: searchqa/dev.parquet
      - split: test
        path: searchqa/test.parquet
---

# FlashRSI Benchmarks

Prepared datasets for FlashRSI. Each benchmark has its own named Hugging Face
configuration. The initial configuration is `searchqa`.

## SearchQA

This is the **2,000-task SkillOpt subset**, exported by
[jinjiajie/EvoOS](https://huggingface.co/datasets/jinjiajie/EvoOS/tree/2e2d97feb4a3394fd577017024e6d9f3176e9fbc/benchmarks/searchqa).
It is not the full SearchQA dataset. The original IDs, record order, answer lists,
retrieved contexts, and split membership are preserved.

| Split | Rows |
| --- | ---: |
| train | 400 |
| dev | 200 |
| test | 1,400 |

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "searchqa")
print(data["train"][0])
```

For reproducible experiments, pass the dataset repository commit as `revision`.
`FlashRSI-Lite` pins a commit in its SearchQA implementation.

## Schema

All three files use the same Parquet schema and Zstandard compression:

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | string | Original unique SearchQA task ID |
| `question` | string | Original question without the prompt wrapper |
| `context` | string | Retrieved snippets, preserved verbatim |
| `answers` | list of string | Non-empty reference answer list, preserved verbatim |

The source export combines the instruction, context, and question in `input`.
Preparation splits these fields without changing their text. Reconstruct the
original input with:

```python
row = data["train"][0]
prompt = (
    "Answer the question using the supplied context. Return only the short answer."
    f"\n\nContext:\n{row['context']}\n\nQuestion:\n{row['question']}"
)
```

Uniform source fields `grader: qa` and `metadata.task_type: searchqa` are recorded
here rather than repeated in every row. No examples were filtered, deduplicated,
reshuffled, or generated. Preparation validates source checksums, counts, globally
unique IDs, reference answers, prompt reconstruction, and Parquet round trips.
File checksums and source metadata are in [searchqa/manifest.json](searchqa/manifest.json).

## Provenance and evaluation

- Export: `jinjiajie/EvoOS`, commit `2e2d97feb4a3394fd577017024e6d9f3176e9fbc`.
- Original dataset: `lucadiliello/searchqa`, commit `c1a979068ba118d85467179b704031d113d689cc`.
- Subset split source: `microsoft/SkillOpt`, commit `db46cd9ae7ce12f1dbd73c945185816aa738751d`.
- SearchQA paper: [SearchQA: A New Q&A Dataset Augmented with Context from a Search Engine](https://arxiv.org/abs/1704.05179).

The export manifest names its original primary metric `hard`. FlashRSI-Lite
currently reports normalized exact match (`exact_match`, primary) and token F1
(`f1`), taking the best match over reference answers. Its normalization applies
NFKC, case folding, punctuation deletion, English article removal, and whitespace
normalization. Failed trajectories and blank outputs score zero. These metric
names and rules should not be assumed identical to every upstream evaluator.

Hugging Face loading preserves the published 400/200/1,400 splits. FlashRSI-Lite
now defaults to `benchmark.split: auto`, preserving these split memberships.
For datasets missing dev or test, auto reserves 20% of training/unassigned data for
each missing split (60/20/20 when both are absent), without moving existing held-out
tasks into training. All three splits must remain nonempty. An optional limit
samples proportionally within the final splits and must be at least three.
Explicit ratio mappings still merge and repartition source splits; those runs do
not use the original fixed SkillOpt partition. Source split names remain in task
metadata. Older FlashRSI-Lite versions defaulted to explicit 60/20/20 ratios.

## Distribution

The source maintainer declares redistribution authorization (`authorized-by-maintainer`)
in the linked source README. This preparation retains that declaration; it does
not assign a new standard license to the source questions or retrieved snippets.
