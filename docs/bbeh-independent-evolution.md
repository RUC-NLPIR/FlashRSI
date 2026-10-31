# BBEH 的独立演化来源

`benchmark.evolution_bbh_tasks` 可指定另一个公开基准 BBH 的原生任务文件，
例如 `[word_sorting]`。固定来源为
[BIG-Bench-Hard](https://github.com/suzgunmirac/BIG-Bench-Hard/tree/9ee07bd481feebf959a6b59d61ea57bdcf30964d)，
commit `9ee07bd481feebf959a6b59d61ea57bdcf30964d`，MIT 许可。
公开入口自动准备该 Git 数据；文件中的原始 `input` 和 `target` 保持不变。

这是显式外部演化实验：BBH 的已发布评估题用作演化数据，不称为 BBH 或 BBEH
官方训练集。演化题继续使用 BBEH 的 correctness evaluator；该配置不代表官方
BBH CoT/few-shot 或榜单评测。下游 BBEH 的 dev/test 与原配置相同。

加载器在 `evolution_limit` 抽样之前检查完整来源的 ID 和规范化原始问题，
不能通过不同任务类别名掩盖同题重合。`evolution_source` 记录真实 Git 来源、
revision、选择的原生任务文件、全池大小和校验值。未知文件、缺失答案、重复题
或重合题明确拒绝，不补写答案或删除冲突样本。

`word_sorting` 文件有 250 题，与完整原始 BBEH 4520 行问题无重合。
原 BBEH 的 `duplicate_questions: exclude` 仍显式排除全部 9 条重复组记录；
该配置不能称为未过滤的全量榜单。

参见 [MiniAgent 配置](../examples/modular_rsi_bbeh.yaml)。填写 Target 和 Worker
各自的连接参数后，依次执行公开入口的 `--plan`、`--check-only` 和正常运行。
Claude Code 使用公开的 `modular_rsi_claude_code` 三扩展示例及其 modules 配置。
公开预检、全池校验和离线参考评分不替代两 Target 的真实模型 smoke。
