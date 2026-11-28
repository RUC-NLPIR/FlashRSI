# Published experiment configurations

These 96 configurations cover 12 algorithms, two Target harnesses and four source benchmarks. They use DeepSeek-V4.1-Flash as Target and DeepSeek-V4-Pro as Worker. The official Target API name is `deepseek-flash`; all 24 SearchQA configurations specify Target `llm.max_tokens: 16384`.

See the [experiment protocol](../../docs/experiments/protocol.md) ([中文](../../docs/experiments/protocol.zh-CN.md)) for role definitions, provider alias changes and configuration corrections. Set local data and harness paths and supply your model credentials before running a configuration.

The 24 HotpotQA configurations load the published evaluation split directly from Hugging Face (150 train, 300 dev, 300 test). The test set keeps 82 questions from the earlier 300-question split and adds 218 questions with complete supporting evidence. To compare per-question results, use the [ordered test IDs at the pinned revision](https://huggingface.co/datasets/RUC-NLPIR/FlashRSI/blob/5976205472dde244a54652715aec9b3bcc721fc7/hotpotqa/test300-manifest.json).

`model-metadata.json` stores fixed model labels for seven historical Snapshot pairs, checked against these YAML files. The exporters match both Snapshot IDs and preserve existing archived labels before applying a correction. Later changes to launch configurations do not rewrite historical model metadata.

## Terminal-Bench execution budgets

The Terminal-Bench configurations reference ordered task IDs in `splits/terminalbench.json`
(20 train / 15 dev / 30 test). EvoHarness uses `splits/terminalbench-no-dev.json`
(the same train and test tasks, with no dev tasks). `benchmark.split_manifest` is
resolved relative to the YAML file. The loader preserves the listed order, excludes
unlisted tasks, and rejects missing or duplicate IDs. Keep `split: auto` and omit
`split_counts` and `limit` when using these fixed partitions.

The [SkillOpt + MiniAgent configuration](skillopt-miniagent-terminalbench.yaml) uses Target `max_turns: 100` and `llm.max_tokens: 65535`, matching the completed historical experiment. The previously published values of 10 turns and 32768 tokens came from the smoke configuration.

The Terminal-Bench configurations omit Target `agent.timeout` so execution uses each task's native Agent deadline. The verifier also uses its task-defined deadline. `agent.harbor.setup_timeout` controls environment preparation, while `algorithm.worker.timeout` controls Worker calls; neither sets the verifier deadline.
