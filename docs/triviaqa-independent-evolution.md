# TriviaQA independent evolution data

Use native training records for evolution and keep the downstream experiment
partition drawn from the complete labeled validation pool:

```yaml
benchmark:
  name: triviaqa
  dataset:
    source: mandarjoshi/trivia_qa
    config: rc.wikipedia
    revision: 0f7faf33a3908546c6fd5b73a660e0f8ff173c2f
    splits: [validation]
  evolution_split: train
  evolution_limit: 1
  split_counts: {train: 1, dev: 1, test: 1}
  seed: 42
```

`evolution_split` accepts native `train` or `validation`. The complete external
and downstream pools are checked by original ID and normalized raw question
hash before any evolution limit is applied. Context changes do not hide the
same question. An overlap rejects the configuration; no row is removed,
renamed, or relabeled. Including native train in the downstream pool while
selecting the same train pool for evolution therefore fails the guard.

Only experiment train is replaced. Existing dev/test partitioning, original
Wikipedia contexts, answer aliases, the official alias-aware EM/F1 scorer, and
algorithm gates remain unchanged. The loader transfers the native alias map for
the selected external training tasks. Legacy scoring remains an explicit
alternative and does not claim the official scorer identity.

`evolution_dataset` optionally overrides the external dataset source mapping.
It follows the same streaming dataset reader as `benchmark.dataset`; its
selected native split is always controlled by `evolution_split`. For a complete
verified local directory containing native Parquet shards, both mappings may
use `source: /absolute/path/to/rc.wikipedia` and `config: default`. Local Parquet
builders use `default`, whereas the upstream HF repository uses `rc.wikipedia`.
Use absolute local paths; dataset source identifiers and local paths follow the
underlying loader's current-directory resolution, not YAML-relative path rules.
Keep `revision` pinned to the actual original artifacts and record their hashes
and cache provenance. This is an explicit complete native cache mode, not a
claim that default online downloads succeeded.

The verified native pool at this revision contains 61888 training records in
seven Parquet shards and 7993 validation records. Complete-pool probes found no
original-ID or normalized-question overlap and no repeated training IDs or
questions. These probes and reference-answer scoring are data evidence only;
ModularRSI still needs a real experiment through the public entry point.

Source, revision, native split, complete pool size/checksum, and the external
evolution role are recorded by the loader. See
[the public example](../examples/modular_rsi_triviaqa.yaml). Claude Code uses the
existing public `examples/modular_rsi_claude_code` three-module example;
MiniAgent retains five modules, with an independently configured native Worker.
