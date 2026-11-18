# 实验协议

[English](./protocol.md)

## Target 与 Worker

公开结果比较了 12 种算法、两种 Target harness（MiniAgent 和 Claude Code）及四个源 benchmark。演化实验统一使用 **DeepSeek-V4.1-Flash 作为 Target、DeepSeek-V4-Pro 作为 Worker**。Target 执行任务，其轨迹由 benchmark 评分，得到 train、dev 和 test 指标。Worker 根据算法要求提出修改或编辑 harness 资源。FlashRSI 演化的是 harness 资源，不训练模型权重。

各方法使用共同的 Target／Worker 模型组合，并保留各自的候选生成和选优过程。同模型 Target／Worker 属于另一项评测设置，当前结果表尚未包含其结果。

优化模型与执行模型分别配置，在相关方法中已有实例。ADAS 原论文使用 GPT-4 搜索、GPT-3.5 执行；OPRO 分别配置 optimizer 和 scorer；GEPA 分别配置任务模型和反思模型。各方法的接入文档说明了 FlashRSI 的适配方式。[ADAS 原论文](https://arxiv.org/html/2408.08435v1)、[OPRO 实现](https://github.com/google-deepmind/opro/blob/main/opro/optimization/optimize_instructions.py)、[GEPA 实现](https://github.com/gepa-ai/gepa#usage)

## 模型名称与接口

| 角色 | 模型系列 | API 调用名称 |
| --- | --- | --- |
| Target | DeepSeek-V4.1-Flash | `deepseek-flash` |
| Worker | DeepSeek-V4-Pro | `deepseek-v4-pro` |

官方 OpenAI 兼容接口使用 `https://api.deepseek.com`，Anthropic 兼容接口使用 `https://api.deepseek.com/anthropic`。模型凭据通过配置或[角色环境变量](../guide/configuration.md)提供。

DeepSeek 于 2026 年 9 月 10 日发布 V4.1-Flash，推荐调用名称为 `deepseek-flash`，同时将旧名称 `deepseek-v4-flash` 兼容路由至 V4.1-Flash。历史实验页面保留了这两种请求名称；公开启动配置现统一使用 `deepseek-flash`。[官方发布公告](https://api-docs.deepseek.com/news/news260910/)

2026 年 10 月 17 日，服务端将 V4.1-Flash 升级为 V4.1-Flash-1017，API 名称保持不变。API 别名会随服务端部署更新，无法单独锁定模型权重。具体日期版本应结合执行日期及可用的服务端记录确认，仅凭系列名称无法确认是否为 1017 版本。[官方更新日志](https://api-docs.deepseek.com/updates/)

## SearchQA 输出上限

维护者已澄清，正式 SearchQA 实验的 Target `llm.max_tokens` 上限为 **16384**。32768 来自早期个别题目的测试，部分公开配置副本中遗留了这一数值。24 份 SearchQA 启动配置现均显式设置为 16384，包括之前遗漏该字段的一份配置。

这是 Target 每次响应的输出上限。Worker 输出预算和 Agent 的轮数上限分别配置。

## 缺失的模型字段

实验页面中有 7 组缺少模型字段，对应公开 YAML 已包含模型配置。本次对照下列配置核对模型名称，将补录值固定保存在[模型元数据](../../examples/experiments/model-metadata.json)中。导出器仅在初始／选中 Snapshot 组合匹配且归档字段缺失时补录。之后调整启动配置不会改变这些历史补录值。

| 算法 | Benchmark | 配置 |
| --- | --- | --- |
| RRSI | AppWorld | [MiniAgent](../../examples/experiments/rrsi-miniagent-appworld.yaml)、[Claude Code](../../examples/experiments/rrsi-claude_code-appworld.yaml) |
| RRSI | SearchQA | [MiniAgent](../../examples/experiments/rrsi-miniagent-searchqa.yaml) |
| RRSI | Terminal-Bench | [MiniAgent](../../examples/experiments/rrsi-miniagent-terminalbench.yaml)、[Claude Code](../../examples/experiments/rrsi-claude_code-terminalbench.yaml) |
| ModularRSI | Terminal-Bench | [MiniAgent](../../examples/experiments/modular_rsi-miniagent-terminalbench.yaml)、[Claude Code](../../examples/experiments/modular_rsi-claude_code-terminalbench.yaml) |
