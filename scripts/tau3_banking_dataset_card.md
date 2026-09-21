# τ³ Banking (tau2-bench `banking_knowledge`)

This directory mirrors the complete `banking_knowledge` domain from
[`sierra-research/tau2-bench`](https://github.com/sierra-research/tau2-bench)
at tag `v1.0.1` (commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`).

## Files

- `domain.tar.gz` preserves the entire domain directory under a single
  `tau3_banking/` archive root: `db.json`, 698 knowledge `documents/`, 14 agent
  `prompts/`, the 97 task files in `tasks/`, and the upstream aggregate
  `tasks.json` and `tasks_voice.json`. File contents and executable permissions
  are retained; archive timestamps and owner identifiers are normalized for
  reproducible preparation.
- `tasks.parquet` is a browsing index with one row per task file: `id`,
  `user_instructions`, `reward_basis`, `user_tools`, `required_documents`, and
  `has_initial_state`. It deliberately **omits** `evaluation_criteria.actions`,
  `communicate_info`, and `initial_state` contents, which are the grading
  targets and private environment state.
- `manifest.json` records the source revision, archive and index checksums, and
  a `task_checksum` per task file.
- `LICENSE` is the upstream MIT license, copied verbatim from the pinned
  revision.

## This is not a question-answering dataset

Each task drives a multi-turn conversation: a simulated user follows the
`user_instructions` persona, the agent under test answers using the domain's
tools and knowledge documents, and the tau2 runtime scores the result from
database state and required actions. `user_instructions` is the **user
simulator's** script, not a prompt to hand directly to the agent being
evaluated, and the index alone does not provide a runnable environment.

Rewards come from the tau2 simulator running this domain. Nothing in this
directory is a text-matching answer key, and importing a previously recorded
reward is not evidence that the simulator is connected.

## Task files vs `tasks.json`

The tau2 runtime loads the `tasks/` directory
(`KNOWLEDGE_TASK_SET_PATH = KNOWLEDGE_DATA_DIR / "tasks"`), so those 97 files are
authoritative and are what the index and per-task checksums describe. The
archived `tasks.json` lists the same 97 ids but disagrees with them for 13:

| Field | Tasks affected |
| --- | ---: |
| `required_documents` | 7 (in each case `tasks.json` holds a strict subset) |
| `user_scenario` | 4 |
| `evaluation_criteria` | 4 |
| `description` | 2 |
| `user_tools` | 1 |

`tasks.json` is preserved as an upstream artifact; it is not the source of this
index. Anything reading the archive should prefer `tasks/`.

## Splits

No official train/dev/test partition exists, and none is added here: all 97
tasks are published as a single `tasks` split. FlashRSI-Lite is responsible for
constructing and recording any evolution partition, including how related tasks
are grouped and how per-task environment state is reset between trials.

## Runtime requirements

The archive contains the domain data only. Running these tasks additionally
requires the tau2-bench runtime, a user-simulator model, and an agent model.
Downloading this archive does not make execution offline or free.

## Preparation and provenance

From FlashRSI-Lite:

```bash
uv run python scripts/prepare_tau3_banking.py
```

The script fetches only the pinned domain and license via a sparse, depth-1
checkout and asserts the resolved commit before packaging. An existing checkout
can be used with `--source-dir PATH --license-file PATH`. The script writes only
the `tau3_banking/` subdirectory under its output directory; it does not upload
data or rewrite other benchmarks or the repository's root dataset card.
Rebuilding from the same source files and permissions produces the same archive
and index.

## Distribution

tau2-bench is distributed under the MIT license, included here as
[LICENSE](LICENSE). This mirror preserves upstream licensing and does not assign
a new license to the domain data.
