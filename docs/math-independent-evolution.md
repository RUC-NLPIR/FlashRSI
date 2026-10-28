# MATH-500 的独立演化数据

通过统一入口运行 [ModularRSI 示例](../examples/modular_rsi_math500.yaml)。填写各自独立的 Target/Worker 模型与 API 配置后，依次执行 `python scripts/run_experiment.py --config examples/modular_rsi_math500.yaml --plan`、`--check-only`，最后去掉检查参数运行。

`variant: math500` 仍使用完整、固定 revision 的 [MATH-500](https://huggingface.co/datasets/HuggingFaceH4/MATH-500) 数据池。`evolution_split` 从固定 revision `21a5633873b6a120296cce3e2df9d5550074f4a3` 的 [原生 MATH](https://huggingface.co/datasets/EleutherAI/hendrycks_math) 中选择 train 或 test；`evolution_subjects` 选择完整原生科目，省略时使用全部七个科目。`evolution_limit` 只限制最后抽取的演化题数量。

加载器先比较完整下游池与完整演化池的 ID、去空白并忽略大小写的问题校验和，再进行 tiny 抽样。发生重合直接拒绝，不能把同一题改名当作独立来源。MATH test 与 MATH-500 有重合，不能拿它替代独立 train。元数据保存实际来源、revision、科目、native split、全池数量和校验和。仅替换实验 train，dev/test 保持原有划分，仍用 Math-Verify 0.9.0 与 last-boxed 协议评分。

示例明确使用整个 `geometry/train` 子集。这是按原生科目指定的来源，不是完整 MATH train 的验证：全七科原始 train 中发现两条空 `\\boxed{}` 参考答案及重复问题，当前加载器会拒绝不满足数据契约的原始记录；没有补写答案、跳过错误或放宽评分。数据来源范围必须随结果一同报告。自定义 1/1/1 是实验划分，不代表官方独立测试榜单。

Claude Code 使用 [公开三扩展示例](../examples/modular_rsi_claude_code.yaml) 的 `agent.source_dir` 和 prompt/skill/hook 模块映射；Worker 仍使用自身独立配置。配置准备、离线参考评分与真实两 Target 模型 smoke 分别记账，见 [Smoke 表](smoke-matrix.md)。
