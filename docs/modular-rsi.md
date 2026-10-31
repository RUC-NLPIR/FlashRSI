# ModularRSI 接入

来源：[论文](https://arxiv.org/abs/2609.14857)与
[官方代码](https://github.com/IQuestLab/ModularRSI/tree/b5c72c36b0d08ff93f00ee202a8fbdebe849dfb9)，
参考 `src/harbor/agents/terminus_2_modular/self_evo/`。
本实现根据方法独立编写代码和提示，未复制上游实现、提示或演化后的函数。
这是固定模型下的核心机制移植，尚未复现论文实验分数。

## 演化流程

默认五个模块都从相同的初始 Snapshot 出发，分别演化 Agent Loop、Tool Use、
Observation Management、Context Management 与 Task Completion Detection。
也支持 `prompt / skill / hook` 三个原生扩展模块，适用于 Claude Code 等提供
外部扩展的 harness。三模块使用相同的独立演化与集成流程，但演化的是外部
扩展，并不等价于修改上述五种运行时机制的源码。
实现顺序执行独立分支；模块间不共享中间修改或轨迹记忆。

每个 epoch 打乱 Benchmark 的 train 集，逐 batch 对当前版本重复执行 `num_rollouts` 次。
同一任务有成功和失败时进行对比；全部失败时寻找该模块记忆中的历史成功，
找不到则做失败诊断；全部成功时寻找效率改进。Worker 输出带目标位置、
支持任务 ID、原因与修改建议的 findings。同一文件合并建议，按不同支持任务数
排序，取前 `edit_budget` 个目标进行一次目录编辑。

轨迹超出提示预算时，每个任务保留成功、失败各一个代表样本及历史成功，
保留任务 ID、分组、样本数量、状态与评分，再均匀压缩问题、输出、错误和轨迹文本。
完整轨迹与历史成功记忆不被截断。预算连这些摘要结构都容纳不了时明确报错。

Worker 使用自己的 harness 和运行配置，通过 `worker.edit(checkout, prompt)`
编辑目标的文件。算法不切换 Worker Snapshot，也不要求 Worker 与 target 是
同一种 Agent、共享 root 或组件规则；只要求两个独立实例以及文件编辑能力。
目标的当前候选只用于 rollout 与 checkout。目标执行失败不会把 Worker 的
执行资源一起替换成故障版本。

每次候选经过文件范围与 Python 编译检查、完整 diff review、当前 batch 的
随机任务执行验证。执行正常但答案错误不等于运行故障；不要求分数严格提升。
review 拒绝或运行错误则保留前一版本。非法编辑消耗本次 batch 的尝试；
Worker 失败、分析/review 协议错误中止实验，由框架保存已有记录。
rollout/评分协议异常记录为整批执行失败证据，不假定其中哪个任务触发异常，
仍允许 Worker 根据错误继续修复。

独立演化结束后，将所选各分支的原生 `Snapshot.check_out()` 临时放到 seed
的编辑目录中。Worker 读取这些完整版本，把各模块的修改集成到 seed；共享
文件也由 Worker 集成，不使用 AST、函数切片或额外的合并协议。参考目录
通过原生上下文管理器清理，然后才 `_commit`，不会进入候选 Snapshot。
集成编辑同样检查文件范围、编译和完整 diff review。

随后对合并版本执行整个演化集的检查，并在集成阶段重新诊断与编辑，解决
模块冲突与重复机制。每次集成编辑仍能读取原始分支 checkout；不可执行的
目标版本也能由独立 Worker 修复。最终对整个演化集执行检查；仍有运行错误
则返回已通过全量检查的初始合并版本，若该版本也未通过则返回 seed。
最后一次提升后冻结版本，runner 只执行一次下游 `test`。
`dev` 不参与演化、选优或 Worker 提示。

## 模块边界

`algorithm.modules` 必须完整声明五个运行时模块，或完整声明三个扩展模块，
每个映射到非空的现有 Snapshot 文件列表。五模块示例：

```yaml
modules:
  agent_loop: [runtime/agent.py]
  tool_use: [runtime/agent.py, tools/shell.py]
  observation_management: [runtime/agent.py, runtime/tool_result.py]
  context_management: [runtime/agent.py]
  task_completion_detection: [runtime/agent.py]
```

这些名称代表演化的功能职责，文件来自 harness 已有的资源布局。多个模块可以
共享一个文件；提示要求独立分支只修改所属职责，集成时保留各分支的改进。
**框架强制约束文件范围，功能职责由提示与 review 约束。** 不再接受
`文件.py::函数` 配置，也不提供函数级修改权限保证；需要更强隔离时，使用
本身具有清晰文件边界的 harness。MiniAgent 示例的 `runtime/agent.py` 包含
多个职责，因此属于共享文件的集成示例。

Snapshot 的 component 分类、兼容性、文件权限和版本历史继续由原框架管理；
算法只使用 `changed_paths()` 判断修改是否在模块声明的文件内。允许修改
这些文件中的签名、decorator 和新增/删除函数，不另建函数注册或发现系统。
文件列表指向现有资源；需要新的文件边界时，在初始 harness 中准备它们。
Claude Code 不能提供闭源 SDK 的可编辑源码，因此不能照搬 MiniAgent 的运行时
文件映射。可使用三模块配置：

```yaml
modules:
  prompt: [CLAUDE.md]
  skill: [skills/workflow/SKILL.md]
  hook: [hooks/hooks.json]
```

[Claude Code 示例](../examples/modular_rsi_claude_code.yaml)通过独立 `source_dir`
提供这些初始文件和原生插件清单；提示词作为原生 system prompt 的补充，skills
与 hooks 通过原生插件加载。默认 Claude Code 资源不添加演化策略。
文件列表仍是精确路径，分支仅能修改已声明的文件；不自动开放整个扩展目录。
缺少文件或模块声明不完整时，在启动时明确报错。切换 Agent 时需要同时选择
对应的模块映射与资源目录，不会按 Agent 名称隐式转换。

填写示例中的任务目录、Target 和 Worker 各自的模型与 API 配置后，通过统一入口启动：

```bash
python scripts/run_experiment.py --config examples/modular_rsi_claude_code.yaml
```

这一实现取舍改变了函数隔离方式及 Worker 的演化方式，并增加了模型参与
初始合并的编辑与 review；不是与此前实现逐步等价的重构，也未验证收益等价。

## 演化数据

2026-10-28 起，本项目按适配需求允许同一来源的数据集：ModularRSI 默认使用当前
`benchmark.train` 演化，不要求外部数据集或 `metadata.evolution_source`。
train 必须非空，任务 ID 唯一，且与 dev/test 的任务 ID 不重合；不同任务可以共享
领域 policy 文本或环境目录。各 Benchmark 继续负责原生数据与划分校验，runner
继续在版本选定后执行 sealed test。算法的模块演化、review 和执行 gate 保持原规则。

例如，从同一原生任务池显式划分实验数据：

```yaml
benchmark:
  split_counts: {train: 1, dev: 1, test: 1}
```

这项默认适配不追求论文的独立演化来源设置。下述外部数据参数仍可选用；显式使用
这些参数时，加载器继续执行该模式原有的来源与重合检查。

TerminalBench 和 SWEBench 支持可选 `benchmark.evolution_data_path` 与 `evolution_limit`。
TerminalBench 加载独立的 Harbor 任务目录；SWEBench 加载独立的 SWE 原生记录文件或目录，
必须包含该加载器要求的任务镜像、基线 commit 及官方评分字段，不能填写 Harbor 任务目录。
两者都以独立任务替换 `train`，沿用各自原生加载、执行与 verifier 评分；
原有 `dev/test` 划分保持不变。`limit` 仍限制下游数据，
`evolution_limit` 单独限制演化数据。未设置这些参数时，原有 benchmark 行为不变。
一键入口中的相对数据路径以 YAML 所在目录解析；普通 CLI 的模块数据路径仍相对 cwd。
示例使用绝对路径。

官方独立任务集见
[ModularRSI_2000_Instances](https://huggingface.co/datasets/IQuestLab/ModularRSI_2000_Instances)。
需要先下载并解包为 Harbor 任务目录；本次没有加入自动下载器或实际运行这批任务。
Terminal 示例：[examples/modular_rsi.yaml](../examples/modular_rsi.yaml)。
SWE 示例：[examples/modular_rsi_swe_bench.yaml](../examples/modular_rsi_swe_bench.yaml)。
可选外部数据需要用户准备；未提供时直接使用当前数据集的 train。

显式外部模式的加载器拒绝与下游已加载任务重合的 ID、指令或 checksum，SWE 还
拒绝共用任务镜像。算法统一检查 train 与 dev/test 的任务 ID 隔离，不按来源、
问题文本或环境目录拒绝同数据集任务。自定义 Benchmark 可以直接提供常规 train。

## 移植边界与验证

不引入 population、Member、函数注册管理器或新的 core 接口。
版本、checkout、评分、Worker 编辑与轨迹、脱敏、提交与最终提升均复用原框架。
Python 检查只编译修改后的源码；不在宿主上 import 候选代码。原论文的模块专用
discovery-contract、self-attribute audits、函数库动态发现和逐任务 Function
Composer 未接入；执行协议使用现有 Agent/Benchmark，diff review 是模型判断，
不是独立反作弊证明。集成时可删除已声明整文件范围中的重复函数，未实现独立
Function Merge 阶段。每个 batch 一次编辑，多目标建议由同次编辑处理。

离线测试覆盖同任务轨迹分组、历史成功、支持任务去重排序、模块独立演化、
当前候选 checkout 的连续编辑、共享文件集成、文件范围/编译/review/执行拒绝、
集成修复与回退、独立 Worker 来源、临时参考目录清理、独立 Harbor 数据加载
和 runner 最终测试。
另有原生 MiniAgent 协议测试，通过真实 subprocess、SDK 和文件工具修改并合并
共享 runtime 文件中五个功能位置的修改；模型响应来自 localhost 模拟服务，
不调用付费模型。
真实模型收益、真实容器运行与论文结果尚未验证。
