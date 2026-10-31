# HotpotQA 独立演化数据

`examples/modular_rsi_hotpotqa.yaml` 显式使用固定版本官方 `train` 作为
ModularRSI 的演化来源，下游 dev/test 从官方 `validation` 做实验内划分。
这是演化实验划分，不是官方隐藏 test 或完整榜单成绩。

填写 Target 和 Worker 各自的模型/API 配置后，使用统一入口：

```bash
python scripts/run_experiment.py --config experiment.local.yaml --plan
python scripts/run_experiment.py --config experiment.local.yaml --check-only
python scripts/run_experiment.py --config experiment.local.yaml
```

关键配置：

```yaml
benchmark:
  name: hotpotqa
  mode: context
  dataset:
    source: hotpotqa/hotpot_qa
    config: fullwiki
    revision: 1908d6afbbead072334abe2965f91bd2709910ab
    splits: [validation]
  evolution_split: train
  evolution_limit: 1
  split_counts: {train: 1, dev: 1, test: 1}
  seed: 42
```

`evolution_split` 只接受固定原生来源的 `train` 或 `validation`。
两完整源池先按 ID 和规范化原始问题检查重叠，再按既有规则选取演化题目；
不同上下文或重命名 ID 不能掩盖重复问题。来源 revision、原生 split、题池数量和
内容校验和由加载器记录。`evolution_limit` 只限制演化样本，原配置的下游 dev/test
成员保持不变。未配置独立来源时保持原加载行为，不能仅给同一题池改标签作为独立来源。

context 模式保留原生答案 EM/F1；fullwiki 模式也保留各演化任务真实的 supporting facts
及官方 joint 指标，需要另外按公开配置准备 Wikipedia 检索环境。
此功能不改变 ModularRSI 的模块、gate、预算或 test 使用规则。

Claude Code 使用公共 `examples/modular_rsi_claude_code` 的 prompt/skill/hook 三模块
配置；MiniAgent 保持自身的五模块。Worker 使用自身原生资源及独立运行配置。
只通过 `--check-only` 不代表真实模型 smoke 已通过。
