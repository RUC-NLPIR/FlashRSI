# HotpotQA (fullwiki)

This directory republishes the labeled data of the `fullwiki` configuration of
[`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa/tree/1908d6afbbead072334abe2965f91bd2709910ab)
at commit `1908d6afbbead072334abe2965f91bd2709910ab`, partitioned into the
train/dev/test splits FlashRSI evolution runs expect.

| Split | Rows | Origin |
| --- | ---: | --- |
| `train` | 81,403 | official train, minus the derived dev holdout |
| `dev` | 9,044 | official train, seeded 1/10 holdout |
| `test` | 7,405 | official labeled validation, held out in full |

The official `fullwiki` test split is **not** used: all 7,405 of its rows have a
null `answer` and `level` and empty `supporting_facts`, so it cannot be scored
locally. The labeled official validation split is reserved as the final test
partition instead.

## Split policy

`split_policy: flashrsi-hotpotqa-heldout-v1` in [manifest.json](manifest.json).

The rule has two parts. The labeled official validation split is held out whole
as `test`, so the final partition is official data that no tuning touches. The
`dev` tuning split is then carved out of official train, taking the first tenth
of the official train ids ordered by `sha256("0:" + id)` — the same seeded
ordering the FlashRSI loader uses, so the partition is reproducible from the ids
alone and independent of file order. `train` is the remainder. The three splits
are disjoint and together cover every labeled official row exactly once. Row
order within each split follows the official files.

Candidate selection during evolution must not read `test`.

## Schema

All three files keep the complete upstream Arrow schema, re-encoded with
Zstandard compression. No column is dropped, flattened, or rewritten:

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | string | Official HotpotQA question ID |
| `question` | string | Multi-hop question |
| `answer` | string | Reference answer |
| `type` | string | `bridge` or `comparison` |
| `level` | string | `easy`, `medium`, or `hard` |
| `supporting_facts` | struct of `title` list and `sent_id` list | Gold sentence-level evidence |
| `context` | struct of `title` list and `sentences` list of lists | Retrieved paragraphs |

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "hotpotqa")
print(data["train"][0])
```

For reproducible experiments, pass the dataset repository commit as `revision`.

## Retrieval setting

`fullwiki` is the **open-domain retrieval** setting: `context` holds paragraphs
returned by the upstream retriever, not the gold paragraphs. In the official
validation pool published here as `test`, only 2,089 of 7,405 rows have a
context containing every gold supporting-fact title; 4,073 contain some and
1,243 contain none. Answering from the supplied context alone therefore has a
ceiling well below 100%.

Using this data as given context is a valid experimental choice, but it is not
the same as the official full-retrieval evaluation, and it is not the
`distractor` setting either. Experiment names and reports should state which of
these they mean. Reading this data source does not by itself constitute an
implementation of full retrieval evaluation.

`supporting_facts` is retained so that supporting-fact and joint metrics remain
computable. A run that reports only answer EM/F1 should say so rather than
implying the official joint score.

## Preparation and provenance

From FlashRSI-Lite:

```bash
uv run python scripts/prepare_hotpotqa.py
```

An existing download of the pinned shards can be used with `--source-dir PATH`.
The script writes only the `hotpotqa/` subdirectory under its output directory;
it does not upload data or rewrite other benchmarks or the repository's root
dataset card. It verifies each source shard's SHA-256 before reading, checks
that the shards share one schema, and confirms after writing that the output
schema (including Hugging Face feature metadata) and all values survive the
round trip. IDs are checked for global uniqueness across splits, answers for
non-emptiness, and the published splits for exact coverage of the official rows.
Re-running against the same sources produces identical bytes.

Source checksums, output checksums, and row counts are in
[manifest.json](manifest.json).

- Original dataset: `hotpotqa/hotpot_qa`, config `fullwiki`, commit
  `1908d6afbbead072334abe2965f91bd2709910ab`.
- Paper: [HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question
  Answering](https://arxiv.org/abs/1809.09600).

## Distribution

HotpotQA is distributed by its authors under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). This mirror
redistributes the pinned revision under the same license and does not assign a
new one.
