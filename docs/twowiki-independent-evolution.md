# 2WikiMultiHopQA 独立演化来源

[公开示例](../examples/modular_rsi_twowiki.yaml) 使用固定原生 train 池演化，完整 validation 池作自定义下游 1/1/1 划分。填写 Target 和 Worker 各自的模型/API 后，依次用 `python scripts/run_experiment.py --config examples/modular_rsi_twowiki.yaml` 执行 `--plan`、`--check-only` 和正式运行。

`benchmark.evolution_split` 支持 `train`、`validation`，`evolution_limit` 限制最终演化样本数。加载器先比较两完整来源的 ID 和规范化原始问题文本，再限样；不同题号或不同上下文不能掩盖相同问题。默认下游同时加载 train/validation 时，把其中 train 再声明为外部来源会被拒绝。仅替换实验 train，原下游 dev/test 保持不变。

原生来源为 `framolfese/2WikiMultihopQA`，revision `fe713bfbd1afbca1a65246741a75890405d56a3a`。元数据由实际加载器产生，包含 source/revision/native split、全池数量和校验和。评分仍是现有 canonical-answer EM/F1，不包含实体别名、支持证据、关系证据或联合评分。公开 validation 的自定义 test 不是官方隐藏 test 或榜单成绩。

实现复用 QA 基类的完整来源检查，不改算法、gate 或角色预算。MiniAgent 使用五模块，Claude Code 使用[公开 prompt/skill/hook 三扩展示例](../examples/modular_rsi_claude_code.yaml)。真实数据准备与两 Target 的模型验证分别记入 [Smoke 表](smoke-matrix.md)，旧拒绝和失败记录保留。
