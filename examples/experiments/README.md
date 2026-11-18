# Published experiment configurations

These 96 configurations cover 12 algorithms, two Target harnesses and four source benchmarks. They use DeepSeek-V4.1-Flash as Target and DeepSeek-V4-Pro as Worker. The official Target API name is `deepseek-flash`; all 24 SearchQA configurations specify Target `llm.max_tokens: 16384`.

See the [experiment protocol](../../docs/experiments/protocol.md) ([中文](../../docs/experiments/protocol.zh-CN.md)) for role definitions, provider alias changes and configuration corrections. Set local data and harness paths and supply your model credentials before running a configuration.

`model-metadata.json` stores fixed model labels for seven historical Snapshot pairs, checked against these YAML files. The exporters match both Snapshot IDs and preserve existing archived labels before applying a correction. Later changes to launch configurations do not rewrite historical model metadata.
