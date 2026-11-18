# Experiment protocol

[简体中文](./protocol.zh-CN.md)

## Target and Worker

The published comparison covers 12 algorithms, two Target harnesses (MiniAgent and Claude Code), and four source benchmarks. Its evolution runs use **DeepSeek-V4.1-Flash as Target** and **DeepSeek-V4-Pro as Worker**. The Target executes tasks and supplies the trajectories graded for train, dev and test. The Worker proposes or edits harness resources. FlashRSI evolves harness resources without training model weights.

This comparison uses a common Target/Worker model pair across methods. Individual algorithms retain their own proposal and selection procedures. Same-model Target/Worker experiments are a separate evaluation setting and are not included in this table.

Separately configured optimization and execution models are supported by several upstream methods. ADAS evaluates agents with GPT-3.5 while its meta agent uses GPT-4; OPRO exposes separate optimizer and scorer models; GEPA exposes separate task and reflection models. Each method's integration guide describes its adaptation to FlashRSI. [ADAS paper](https://arxiv.org/html/2408.08435v1), [OPRO implementation](https://github.com/google-deepmind/opro/blob/main/opro/optimization/optimize_instructions.py), [GEPA implementation](https://github.com/gepa-ai/gepa#usage)

## Model names and endpoints

| Role | Model family | API model name |
| --- | --- | --- |
| Target | DeepSeek-V4.1-Flash | `deepseek-flash` |
| Worker | DeepSeek-V4-Pro | `deepseek-v4-pro` |

For the official service, use `https://api.deepseek.com` for OpenAI-compatible requests or `https://api.deepseek.com/anthropic` for Anthropic-compatible requests. Supply your own credentials through the configuration or the [role environment variables](../guide/configuration.md).

On September 10, 2026, DeepSeek introduced `deepseek-flash` for V4.1-Flash and retained `deepseek-v4-flash` as a compatibility name routed to V4.1-Flash. Historical explorer records retain both request names. The published launch configurations now use `deepseek-flash`. [Official release announcement](https://api-docs.deepseek.com/news/news260910/)

On October 17, 2026, the service upgraded V4.1-Flash to V4.1-Flash-1017 while retaining the API name. An API alias follows the provider's deployment and does not pin model weights. Exact dated versions should be reported from the execution date and available provider records; the family name alone does not identify the 1017 revision. [Official change log](https://api-docs.deepseek.com/updates/)

## SearchQA output limit

The maintainers clarified that the formal SearchQA experiments used a Target `llm.max_tokens` limit of **16384**. The value 32768 came from preliminary tests on individual tasks and remained in some public configuration copies. All 24 SearchQA launch configurations now explicitly specify 16384, including the configuration that previously omitted the field.

This setting is the per-response output limit for the Target. Worker output budgets and agent turn limits are configured separately.

## Missing model records

Seven explorer entries omitted model labels even though their public YAML configurations contained them. The labels were checked against the corresponding configurations below and recorded in [model metadata](../../examples/experiments/model-metadata.json). The exporter applies these fixed values only to matching initial/selected Snapshot pairs and only when the archived label is missing. Later edits to launch configurations do not change these historical corrections.

| Algorithm | Benchmark | Configuration |
| --- | --- | --- |
| RRSI | AppWorld | [MiniAgent](../../examples/experiments/rrsi-miniagent-appworld.yaml), [Claude Code](../../examples/experiments/rrsi-claude_code-appworld.yaml) |
| RRSI | SearchQA | [MiniAgent](../../examples/experiments/rrsi-miniagent-searchqa.yaml) |
| RRSI | Terminal-Bench | [MiniAgent](../../examples/experiments/rrsi-miniagent-terminalbench.yaml), [Claude Code](../../examples/experiments/rrsi-claude_code-terminalbench.yaml) |
| ModularRSI | Terminal-Bench | [MiniAgent](../../examples/experiments/modular_rsi-miniagent-terminalbench.yaml), [Claude Code](../../examples/experiments/modular_rsi-claude_code-terminalbench.yaml) |
