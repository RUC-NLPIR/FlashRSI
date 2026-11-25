# Published experiment configurations

These 96 configurations cover 12 algorithms, two Target harnesses and four source benchmarks. They use DeepSeek-V4.1-Flash as Target and DeepSeek-V4-Pro as Worker. The official Target API name is `deepseek-flash`; all 24 SearchQA configurations specify Target `llm.max_tokens: 16384`.

See the [experiment protocol](../../docs/experiments/protocol.md) ([中文](../../docs/experiments/protocol.zh-CN.md)) for role definitions, provider alias changes and configuration corrections. Set local data and harness paths and supply your model credentials before running a configuration.

The 24 HotpotQA configurations load the published evaluation split directly from Hugging Face (150 train, 300 dev, 300 test). The test set keeps 82 questions from the earlier 300-question split and adds 218 questions with complete supporting evidence. To compare per-question results, use the [ordered test IDs at the pinned revision](https://huggingface.co/datasets/RUC-NLPIR/FlashRSI/blob/5976205472dde244a54652715aec9b3bcc721fc7/hotpotqa/test300-manifest.json).

`model-metadata.json` stores fixed model labels for seven historical Snapshot pairs, checked against these YAML files. The exporters match both Snapshot IDs and preserve existing archived labels before applying a correction. Later changes to launch configurations do not rewrite historical model metadata.
