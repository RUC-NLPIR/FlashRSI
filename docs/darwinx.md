# DarwinX 接入

本实现把 DarwinX 的核心搜索机制移植到 Lite 的 `Algorithm`、`Snapshot`、
`Worker` 与 `Results` 接口，不依赖 Beagle 的 campaign driver。

实现只包含算法入口与提示模板。archive 是普通字典记录，可直接用于提示和实验记录；
被评估的版本保留原生 `Snapshot` 和各轮 `Results`，不引入 population/评估类型或行转换层。
`_measure` 只计算重复评估的逐题均值；总分和轨迹证据读取 `Results`。
父节点选择、两阶段准入、目录编辑分别留在算法自身的方法中，文件提交、记录和最终提升复用基类。

来源：[论文](https://arxiv.org/abs/2608.07545)、
[官方 Beagle](https://github.com/SalesforceAIResearch/Beagle/tree/165343b46a85b5d28c6370e6197ac665c7eda871/beagle/algorithms/darwinx)。
核对的上游 revision 为 `165343b46a85b5d28c6370e6197ac665c7eda871`，主要参考
`vendor/evolve/preserve_extend.py`、`parent_selection.py`、`merge_selection.py`、
`pipeline.py` 及 `config.py`。这是机制移植，不是原始实验的完整复现。

## 搜索流程

1. 在整个 `train` 池上重复评估 seed，建立逐任务均值和初始已解决集合。
2. 从已确认的种群选父节点：默认一半概率按累计 lineage gain 选最优，
   另一半概率从可选父节点均匀采样，允许建立旁系。
3. Worker 编辑父节点 checkout，读取原始成功/失败轨迹、保留契约、archive 和共享经验。
4. 在随机 train 子集上，以相同任务、相同重复次数分别测父节点和候选。
   存在逐题正向变化且回退质量不超过 `screen_regression_tolerance`，才支付全池确认成本。
   低成本筛选允许有限 trade，以便测出可供重组的 specialist；筛选通过不代表准入。
5. 在整个 train 池上重新、分别重复测父节点和候选，执行 preserve-and-extend 判定。
   只有确认通过的候选才成为下一轮 mutation 的父节点。
6. 每个已测候选都进入 archive，包括筛选失败、确认失败、分数持平的变体。
   每次测完调用 Worker 蒸馏经验，下一轮可读取被拒绝方案的得失。
7. 达到重组 cadence 时，从完整确认过的 archive（含被拒绝的 specialist）寻找互补对。
   Worker 编辑主版本 checkout，其内部临时提供共同祖先与 donor 的完整 Snapshot checkout。
   Worker 对照实际文件整合改动，包含新增、删除、二进制与可执行权限。
   参考目录使用相对路径，随编辑目录一起传给容器 Worker；退出 checkout 后自动清理，再由主版本 `commit`。
   重组还要保留双方已解决任务的 union。
   没有互补对时执行普通 mutation。同一对在一次 run 中只尝试一次重组。
8. 最后提升已确认成员中 train 均值最高者，平分保留更早成员；runner 随后只测一次 `test`。

## 准入契约

每次重复都独立执行一整批任务。逐题分数为 primary metric 的 **avg@k**：
`p[t] = mean(score[t, trial])`，不取 best-of-k，也不把重复 task_id 塞进同一批 rollout。
primary metric 必须在 `[0, 1]`，train 非空且 task_id 唯一。

mutation 的确认判定为：

```text
gain = sum(candidate[t] - parent[t])
regression_mass = sum(max(parent[t] - candidate[t], 0))
accept = gain > 0
         and regression_mass <= regression_tolerance
         and no inherited solved task falls below solved_threshold
```

浮点边界使用 `1e-12` 容差。回退质量是逐题下降量的**和**，不是平均下降。
默认 `regression_tolerance: 0`，所以一题下降不能靠另一题的提升抵消。
`solved_threshold: 1` 表示只有所有确认重复均成功的任务才计入已解决集合；
该集合沿 lineage 累积，启用非零回退容差也不能丢掉已解决任务。

重组时，gain 仍相对 primary 计算；回退参考改为两个父节点逐题均值的 `max`，
已解决 invariant 则取两个 lineage invariant 和两个父节点已解决任务的 union。
因此合并出双方能力的 union 就能扩展 primary，不要求额外解决 union 之外的新任务。
所有确认比较都重新评估双方，以相同样本数、相同完整任务池计算，
不会拿一轮筛选分数和多轮确认分数作比较。

重复评估用于减少单次幸运运行的影响，当前没有置信区间或显著性检验；
有限次数测得的保留不代表对所有未见任务的能力保证。

## 配置与成本

见 [examples/darwinx.yaml](../examples/darwinx.yaml)。现有 CLI 可直接覆盖这些字段：

```bash
uv run flashrsi run --config examples/darwinx.yaml \
  --algorithm.max_steps 2 --algorithm.merge_every 0 \
  --algorithm.confirm_samples 2 --benchmark.limit 9
```

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_steps` | 10 | 编辑尝试次数，mutation/recombination 都占一轮；非法编辑也占一轮 |
| `screen_size` | 3 | 随机筛选子集大小，不超过 train 大小 |
| `screen_samples` | 1 | 每个筛选任务的重复数 |
| `confirm_samples` | 3 | 每个确认任务的重复数，不能小于筛选重复数 |
| `screen_regression_tolerance` | 1.0 | 筛选容许的逐题回退质量，用于发现互补 specialist |
| `regression_tolerance` | 0.0 | 正式确认允许的回退质量 |
| `solved_threshold` | 1.0 | 已解决任务的 avg@k 阈值，范围 `(0, 1]` |
| `exploration_probability` | 0.5 | 从已确认可选父节点均匀采样的概率 |
| `merge_every` | 3 | 每几轮尝试一次重组；0 禁用，无互补对时退回 mutation |
| `seed` | 42 | 父节点、筛选子集采样的随机种子，不控制模型采样 |
| `max_evidence_chars` | 24000 | 每个证据块的字符上限；archive/经验优先显示最近内容 |

设 train 大小为 N，筛选大小为 s，筛选重复数为 q，确认重复数为 k：
seed 成本为 `N*k` 个任务执行。普通有效编辑筛选成本为 `2*s*q`，
通过筛选再加 `2*N*k`；重组对应为 `3*s*q` 与 `3*N*k`。
每轮有效编辑调用一次 `worker.edit`，每个已测候选另调用一次 `worker.ask` 蒸馏经验。
无改动、重复文件内容或提交非法的编辑不评估、不生成经验。
这些是目标执行数，不是模型请求数；一个 agent 任务可能发起多次模型请求。

`train` 用于搜索、诊断和最终择优；`dev` 当前不用，`test` 不进入 Worker 或搜索。
这与 ADAS 当前的 dev 搜索协议不同。目标和 Worker 分别显式设置自己的 `llm`。
Worker 必须为 `type: agent`，不能使用纯文本 LLM Worker。
演化范围为目标声明的全部 component，不按具体 harness 或 benchmark 名称分支。

## 记录与移植边界

原始每次重复的轨迹由 `_evaluate` 保存，`decision` 记录逐题均值、样本数、
gain、regression mass、实际父节点参考分数、invariant 丢失、确认级别及准入状态。
Snapshot 保存文件、版本身份和父子关系。mutation 和重组都从主版本 checkout/commit，
记录中的 `snapshot_id/parent_id` 直接来自 Snapshot；重组额外记录 `donor_id` 表示改动来源，
它不作为版本父节点，也不参与共同祖先查找。临时参考目录不进入候选 Snapshot。
`learnings` 保存每个候选的共享经验，最终 promote 记录完整 archive 和被拒绝编辑。

与完整 Beagle 的主要差异：

- 用 Lite 的 Snapshot 和实验记录替代 Git worktree、SQLite、campaign supervisor；不实现恢复运行。
- 使用一个固定 train 池、确定的数值门禁和 lineage solved invariant。
  上游有可配置的 reasoned verdict、fractional gate、任务主题和动态子集等更复杂的策略。
- exploration 是对可选节点均匀采样；上游 `mixed_high_score` 的 broaden 分支仍以累计 gain 排序，
  再以子节点数等打破平局。互补对这里按 union 大小排序，没有移植上游 utility/risk 自动门禁。
- mutation 没有内部多轮 analyze/implement/review 和回退修复循环；每次编辑占一轮。
- 支持两分支重组，不实现 N-way merge、prune/consolidate、教师模型、
  独立 verifier/anti-cheat、跨 benchmark/mixture/heldout 门禁、trace QC 或集群调度。
  提示中的通用化约束不等于独立 anti-cheat 验证。
- 轨迹和 archive 通过 Lite 的字符预算截断；重组文件由 Worker 直接读取 checkout。

已验证：离线目录编辑在 MiniAgent 和 Claude Code 上的协议、逐题回退拒绝、
avg@k、幸运筛选后确认失败、确认父节点选择、被拒绝 specialist 重组与 union 保留、
非法编辑后的继续搜索，以及 runner 的配置、凭据脱敏和最终单次 test。
尚未验证：真实付费模型的 DarwinX 演化效果、真实环境 benchmark 的端到端表现及论文分数。
