# MuSiQue 独立演化来源

[公开示例](../examples/modular_rsi_musique.yaml) 使用 MuSiQue-Ans v1.0 的原生 train 池演化，原生 dev 池作自定义下游 1/1/1 划分。填写 Target 和 Worker 各自的模型/API 后，运行统一入口的 `--plan`、`--check-only`，再用同一配置正式运行。

`benchmark.evolution_split` 支持原生 `train`、`dev`；`evolution_limit` 限制最终抽取的演化题数量。两完整来源先按 ID 和规范化原始问题文本检查重叠，再取样。修改题号、段落或上下文不能绕过检查。仅替换实验 train，原下游 dev/test 不变；若默认同时载入原生 train/dev 后又把 train 声称为外部来源，启动时拒绝。

来源固定为 `bdsaglam/musique` 的 revision `22873a405dd809893b22ada0b499299fb612d2df`，原生 JSONL 不做题目改写或私有抽样。元数据由实际加载器生成，包含真实 source/revision/native split、全池数量和校验和。官方回答 EM/F1 保持原样；`answer_support` 模式仍使用原生段落编号和官方支持证据评分，标签留在评分端。

HotpotQA 与 MuSiQue 共用 QA 基类中的完整题池检查和 train 替换实现，各自保留数据契约、原生来源和评分器。算法、gate、角色预算都没有改变。Claude Code 按 [公开三扩展示例](../examples/modular_rsi_claude_code.yaml) 配置 `agent.source_dir` 和 prompt/skill/hook，MiniAgent 保留五个模块。

原生 dev 是带标签的公开池。这里的实验 test 是自定义 held-out，不代表官方隐藏 test 或完整榜单成绩。离线检查、真实数据准备与两 Target 的模型 smoke 分别记录在 [Smoke 表](smoke-matrix.md)，旧缺数据拒绝及失败历史继续保留。
