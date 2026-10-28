# SuperGPQA independent evolution data

SuperGPQA's published pool has no native training split. An explicit external
ARC pool can supply ModularRSI evolution examples through public configuration:

```yaml
benchmark:
  name: supergpqa
  evolution_arc: {subset: ARC-Challenge, split: train}
  evolution_limit: 1
  split_counts: {train: 1, dev: 1, test: 1}
  seed: 42
```

The loader reads the complete native Parquet file from `allenai/ai2_arc` at
revision `210d026faf9955653af8916fad021475a3f00453`. Supported subsets are
`ARC-Challenge` and `ARC-Easy`; splits are `train`, `validation`, and `test`.
Validation/test selections remain explicitly external published evaluation
data, never an official SuperGPQA training partition.

Before limiting examples, the loader checks the complete downstream SuperGPQA
pool against the complete external pool by original task ID and normalized raw
question hash. A collision rejects the source; no overlapping record is removed
or renamed. Only experiment `train` is replaced. SuperGPQA's dev/test selection,
final-letter accuracy scorer, and algorithm gates remain unchanged.

ARC option text and ordering are preserved. Numeric native choice labels are
mapped by option position to the existing letter protocol, retaining
`native_choice_labels` and `native_answer_key` in task metadata. No answer is
generated or corrected. Source, fixed revision, subset, native split, full pool
size, checksum, and external evolution role are recorded automatically.

The complete Challenge/train file has 1119 records. Its one repeated raw question
is preserved under its two distinct native IDs; both records remain training
records and neither is removed. A complete-source probe found no question
overlap with the complete 26529-record SuperGPQA pool. This establishes a data
configuration, not a successful model experiment or a leaderboard result.

See [the public example](../examples/modular_rsi_supergpqa.yaml). Claude Code uses
the existing public three-module example at `examples/modular_rsi_claude_code`;
its Worker keeps a separate native role configuration. The MiniAgent example
keeps the usual five modules and fixed budgets.
