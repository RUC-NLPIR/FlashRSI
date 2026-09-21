---
pretty_name: FlashRSI Benchmarks
language:
- en
task_categories:
- question-answering
size_categories:
- 10K<n<100K
license: other
license_name: benchmark-specific
license_link: https://huggingface.co/datasets/jinjiajie/flashrsi/blob/main/README.md#distribution
configs:
- config_name: searchqa
  data_files:
  - split: train
    path: searchqa/train.parquet
  - split: dev
    path: searchqa/dev.parquet
  - split: test
    path: searchqa/test.parquet
- config_name: terminal_bench
  data_files:
  - split: tasks
    path: terminal_bench/tasks.parquet
- config_name: hotpotqa
  data_files:
  - split: train
    path: hotpotqa/train.parquet
  - split: dev
    path: hotpotqa/dev.parquet
  - split: test
    path: hotpotqa/test.parquet
- config_name: tau3_banking
  data_files:
  - split: tasks
    path: tau3_banking/tasks.parquet
---

# FlashRSI Benchmarks

Prepared datasets for FlashRSI. Each benchmark has its own named Hugging Face
configuration. `searchqa` and `hotpotqa` contain question-answering records;
`terminal_bench` and `tau3_banking` contain task indexes backed by complete
native archives.

| Config | Contents | Splits |
| --- | --- | --- |
| `searchqa` | QA records with retrieved context | 400 / 200 / 1,400 |
| `hotpotqa` | Multi-hop QA records, full upstream schema | 81,403 / 9,044 / 7,405 |
| `terminal_bench` | Task index + native task archive | 89 tasks |
| `tau3_banking` | Task index + complete tau2 domain archive | 97 tasks |

For reproducible experiments, pass the dataset repository commit as `revision`.
`FlashRSI-Lite` pins a commit in each benchmark implementation.

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

### SearchQA schema

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

### SearchQA provenance and evaluation

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

## HotpotQA

The labeled data of the `fullwiki` configuration of
[`hotpotqa/hotpot_qa`](https://huggingface.co/datasets/hotpotqa/hotpot_qa/tree/1908d6afbbead072334abe2965f91bd2709910ab)
at commit `1908d6afbbead072334abe2965f91bd2709910ab`, re-encoded with Zstandard
and otherwise unchanged: every upstream column is preserved, including `type`,
`level`, and the nested `supporting_facts` and `context` structs.

| Split | Rows | Origin |
| --- | ---: | --- |
| train | 81,403 | official train, minus the derived dev holdout |
| dev | 9,044 | official train, seeded 1/10 holdout |
| test | 7,405 | official labeled validation, held out in full |

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "hotpotqa")
print(data["train"][0])
```

The official `fullwiki` test split is **not** used: all 7,405 of its rows have a
null `answer` and `level` and empty `supporting_facts`, so it cannot be scored
locally. Under `split_policy: flashrsi-hotpotqa-heldout-v1`
([hotpotqa/manifest.json](hotpotqa/manifest.json)) the labeled official
validation split is held out whole as `test`, and `dev` is the first tenth of
the official train ids ordered by `sha256("0:" + id)`. The three splits are
disjoint and cover every labeled official row exactly once; candidate selection
must not read `test`.

`fullwiki` is the open-domain retrieval setting, so `context` holds retrieved
paragraphs rather than gold ones. In the official validation pool published as
`test`, only 2,089 of 7,405 rows have a context containing every gold
supporting-fact title. Treating this as a given-context task is a valid choice
but is neither the official full-retrieval evaluation nor the `distractor`
setting; experiment names should say which is meant. `supporting_facts` is
retained so supporting-fact and joint metrics stay computable, and a run
reporting only answer EM/F1 should say so. See
[hotpotqa/README.md](hotpotqa/README.md).

## Terminal-Bench 2.0

This mirror contains all 89 native tasks from
[the pinned upstream revision](https://github.com/laude-institute/terminal-bench-2/tree/69671fbaac6d67a7ef0dfec016cc38a64ef7a77c),
including instructions, environment definitions, tests, solutions, and bundled
resources. Native bytes and executable flags are preserved in the archive.

- [Task index](terminal_bench/tasks.parquet): 89 rows with `id`, `question`,
  `task_path`, `task_checksum`, `category`, and `difficulty`.
- [Task archive](terminal_bench/tasks.tar.gz): complete native task directories.
- [Manifest](terminal_bench/manifest.json): source revision, archive checksum,
  index checksum, and per-task Harbor checksums.
- [Loading and execution details](terminal_bench/README.md).

```python
from datasets import load_dataset

index = load_dataset("jinjiajie/flashrsi", "terminal_bench")
print(index["tasks"][0])
```

The `tasks` split is the unsplit official task collection. FlashRSI-Lite applies
its deterministic train/dev/test partition at runtime; these are experimental
partitions rather than upstream official splits. Loading the Parquet index alone
does not create runnable environments. FlashRSI-Lite downloads and validates the
archive, restores the native directories locally, and passes them to Harbor.

The archive does not include Docker image layers or all resources fetched by
build scripts and task execution. Docker, task images, model access, and any
required network access are still needed. The repository's existing access
settings apply to all benchmark configurations.

## τ³ Banking

The complete `banking_knowledge` domain from
[`sierra-research/tau2-bench`](https://github.com/sierra-research/tau2-bench)
at tag `v1.0.1` (commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`).

- [Domain archive](tau3_banking/domain.tar.gz): `db.json`, 698 knowledge
  documents, 14 agent prompts, 97 task files, and the upstream aggregate
  `tasks.json` and `tasks_voice.json`.
- [Task index](tau3_banking/tasks.parquet): 97 rows with `id`, `user_instructions`,
  `reward_basis`, `user_tools`, `required_documents`, and `has_initial_state`.
- [Manifest](tau3_banking/manifest.json): source revision, archive and index
  checksums, and a checksum per task file.
- [Loading and execution details](tau3_banking/README.md).

```python
from datasets import load_dataset

index = load_dataset("jinjiajie/flashrsi", "tau3_banking")
print(index["tasks"][0])
```

This is **not** a question-answering dataset. Each task drives a multi-turn
conversation in which a simulated user follows the `user_instructions` persona
and the tau2 runtime scores the result from database state and required
actions. `user_instructions` is the user simulator's script, not a prompt for
the agent under test. The index omits `evaluation_criteria` and `initial_state`
contents, which are grading targets and private environment state and stay
inside the archive. Running these tasks requires the tau2-bench runtime plus
user-simulator and agent models. No official partition exists and none is added.

## Distribution

**SearchQA:** The source maintainer declares redistribution authorization (`authorized-by-maintainer`)
in the linked source README. This preparation retains that declaration; it does
not assign a new standard license to the source questions or retrieved snippets.

**HotpotQA:** Distributed by its authors under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). This mirror
redistributes the pinned revision under the same license.

**Terminal-Bench:** The mirrored task revision predates the upstream `LICENSE`
file. The current upstream repository identifies its license as Apache-2.0; a
copy of that later upstream file and its precise source revision are included as
[UPSTREAM_LICENSE](terminal_bench/UPSTREAM_LICENSE) and
[license-source.json](terminal_bench/license-source.json). This mirror preserves
upstream provenance and notices and does not assign a new license or apply the
SearchQA authorization statement to Terminal-Bench.

**τ³ Banking:** tau2-bench is distributed under the MIT license, copied verbatim
from the pinned revision as [tau3_banking/LICENSE](tau3_banking/LICENSE).
