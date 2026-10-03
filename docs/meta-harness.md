# Meta-Harness 接入

来源：[论文](https://arxiv.org/abs/2603.28052)、
[官方代码](https://github.com/stanford-iris-lab/meta-harness/tree/8123ccabe2b19fa1123090b2e5f1bacc20963ce8)。
核对的 revision 为 `8123ccabe2b19fa1123090b2e5f1bacc20963ce8`，参考
`reference_examples/text_classification/meta_harness.py` 与
`reference_examples/terminal_bench_2/meta_harness.py`。
这是固定模型下的核心搜索机制移植，不是论文实验的完整复现。

## 搜索流程

1. 在 `dev` 上评估初始 Snapshot，保存源码版本、主指标分数和完整执行轨迹。
2. 每轮提供可编辑的 seed checkout，并在其内部临时放置历史文件目录。
   `index.json` 把原生 Snapshot ID 映射到源码 checkout；`trajectories/`
   提供框架保存的完整评估、分数、编辑决策和此前 Worker 轨迹。
3. Worker 使用文件与终端工具自主检索，决定参考哪些版本、如何诊断和构造候选。
   历史不会拼成一个长提示，也不按字符预算截断；退步版本同样可读。
4. 历史参考目录退出后自动清理，再由框架提交目标目录并执行整个 `dev` 评估。
   无改动或非法编辑占一轮，不执行候选评估；拒绝记录在后续历史中可读。
   Worker 调用失败则中止实验，保留框架错误轨迹。
5. 所有已测候选都留在历史中。搜索结束后只提升主指标最高的 Snapshot，
   平分保留更早版本；runner 最后只评估一次 `test`。

seed checkout 是每轮写入完整候选的起点，不限制 Worker 必须以 seed 为搜索父代。
Worker 可以读取、复制、组合或改写任何历史源码；外循环不按分数指定父代，
也不加入固定 mutation、crossover 或额外 reflection 阶段。
候选的 `parent_id` 如实表示其物理 checkout/commit 基线（seed），
不把 Worker 借鉴的版本另建成一份版本图。

## 复用与文件边界

实现只有算法入口与提示模板。版本直接使用原生 Snapshot；评分、记录、
凭据脱敏、文件提交和最终提升复用 Algorithm，不引入 Member、population、
历史管理器或独立的轨迹序列化协议。

源码参考通过 Snapshot 的 `check_out` 提供，保留二进制内容和可执行权限。
轨迹参考直接复制框架已经脱敏的记录，包括完整消息与错误。
每轮重新生成参考视图，Worker 对历史副本的误改不会覆盖真实 Snapshot 或实验记录。
所有参考路径相对编辑目录，因此只搬移 `working_dir` 时仍可检索。
这仅验证目录搬移协议，不代表已经验证真实容器部署。

临时历史位于候选 checkout 内，以便文件工具和隔离的 Worker 能访问。
提交前整个参考目录已移除；历史、日志和运行凭据不进入候选版本。
演化范围为 target 声明的全部组件，目标组件布局与执行接口仍由原有框架约束。
MiniAgent 的可编辑 runtime 能用于代码级搜索；Claude Code 演化的是其声明的
指令、技能、工具和配置，不能据此宣称已经改写闭源 SDK 的内部运行逻辑。

直接通过 Python 调用 `evolve()` 时，也会使用临时实验目录生成同样的完整历史，
结束或失败后清理并恢复 `_run_dir`；runner 调用则保留正常的持久实验记录。

## 配置与成本

见 [examples/meta_harness.yaml](../examples/meta_harness.yaml)：

```bash
uv run flashrsi run --config examples/meta_harness.yaml \
  --algorithm.max_steps 2 --benchmark.limit 9
```

唯一算法参数 `max_steps` 默认 20，表示编辑尝试次数。
Worker 必须为 `type: agent`，具备文件读取、终端检索和目录编辑能力；
纯 LLM Worker 在启动时报错。target 与 Worker 的模型配置分别设置。

设 `dev` 大小为 N，最多进行 `N * (1 + max_steps)` 次目标任务执行，
以及 `max_steps` 次 Worker 编辑。无效编辑不消耗候选评估。
不读取 `train`；`dev` 是搜索集，其分数用于诊断和选优，并非独立泛化结果。
`test` 不进入搜索历史或 Worker 的候选选择。

每轮会重新导出全部已测源码和记录，磁盘复制量随历史增长。
当前优先保留简单的原生 checkout 流程，未加入历史缓存或索引数据库。

## 移植边界与验证

原论文允许每轮多个候选、多初始 harness，以及 accuracy/token 等多目标 Pareto
输出。Lite 当前每轮构造一个目录候选，从一个初始 Snapshot 搜索，按 benchmark
的单个主指标选出一个最终 Snapshot。不实现多目标 frontier、恢复运行、
上游特定任务的 import/smoke 检查和集群调度；接口执行和评分交给现有 target/benchmark。
提示中的泛化约束不等于独立反作弊验证。

离线测试覆盖双 harness、完整历史检索、退步版本、长轨迹、脱敏、
二进制与权限、目录搬移、拒绝后继续、Worker 失败清理、直接 Python 使用和 runner。
真实付费模型的演化效果、真实环境 benchmark 端到端表现和论文分数尚未验证。
