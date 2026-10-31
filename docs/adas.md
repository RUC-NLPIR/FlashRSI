# ADAS 迁移

ADAS 实现 Meta Agent Search：meta agent 读取 archive，编辑 harness 目录产出下一个
设计，按 dev 分数入档，结束时选中 archive 里分数最高的设计，复用 Algorithm、Snapshot、
Worker 和 runner。

ADAS 的 archive 保留已评估设计的说明与分数，并作为后续提案的证据；证据超出预算时按
`max_evidence_chars` 截断。低分设计也会留在 archive 中，供后续搜索参考。

**与 AHE 的关系是正交，不是重复。** 两者都把 harness 当目录交给 coding agent 编辑，
但问责方式相反：

| | AHE | ADAS |
| --- | --- | --- |
| Worker 看到的证据 | rollouts + debugger 报告 + 上轮逐条判决 | **整个 archive**（历史设计的说明 + 分数） |
| 候选去留 | 合法即保留，无分数门槛 | **按分数**：incumbent 只在提升时移动 |
| 凭什么问责一次编辑 | manifest（声明的 fix_tasks 对照实测） | 分数 |
| 跨轮携带的状态 | 上轮判决 + declined 列表 | 完整 archive |
| 评估用的划分 | train（无 held-out 屏障） | **dev**（对应原文 validation） |

## 入口和执行流程

- 主循环与 archive：[algorithms/adas/\_\_init\_\_.py](../flashrsi/algorithms/adas/__init__.py)。
  archive 就是 `evolve()` 里的一个 list，每项是 `{"account": ..., "score": ...}` ——
  也就是基类 `_evidence()` 要的那个形状，原样进提示，原样进 promote 记录，不另包一层类型。
  领先版本用 `best, best_score` 两个变量跟着走（与 ACE 一致），因为只有 Snapshot 能被 checkout
  和 promote。
- 角色提示：[\_prompts.py](../flashrsi/algorithms/adas/_prompts.py)。
- 小规模配置：[examples/adas.yaml](../examples/adas.yaml)。

先在 YAML 中分别填写 target 与 Worker 的模型、凭据及连接地址，再运行：

```bash
uv sync --extra all
uv run flashrsi run --config examples/adas.yaml
```

默认安装已包含 Claude Code 依赖。使用该目标时将 `agent.name` 改为 `claude_code`，
并为 `agent.llm` 单独配置 Anthropic 兼容模型及端点。

1. 在 dev 上执行当前版本，得到种子分数；它成为 archive 的第 0 项。
2. 取 archive 中分数最高的设计作为本轮父代（同分保留较早的那个）。
3. 检出父代，把目录交给 meta agent；它用自己的原生文件工具编辑，
   并在回复的 `<DESIGN>` 块里说明这个设计做了什么。
4. 按 `num_reflections` 在**同一个 checkout** 里复查：agent 修改自己刚写的文件，
   最后一次给出的说明进入 archive。
5. 提交 checkout 得到候选。不可分类的新增路径、空编辑或泄漏凭据都拒绝本轮并记录，
   不终止实验。
6. 候选在 dev 上评估，**无论升降都进入 archive**，写一条 `kind: "admit"` 记录。
7. 回到第 2 步，直到 `max_steps` 用完。
8. 结束时 `_promote` 选中 archive 里分数最高的设计，并把整份 archive 写进决策记录。
9. runner 只在演化结束后评估 test；test 轨迹不会进入 archive 或任何提示。

**dev 是搜索使用的划分，train 在这个算法里不使用。** dev 分数参与提案反馈和版本选择，
不能作为最终独立测试结果。因此 `_check()` 要求 dev 非空，对 train 无要求。

## 为什么降分的设计也留在 archive 里

这不是容错，是机制本身。下一份提示是对着整段历史写的，所以一个比父代差的设计仍然告诉
meta agent：这个方向试过了，代价是多少。`accepted` 字段记录它是否成为新的领先者，
但记录本身无论如何都会写。

与之相对，**被拒绝的设计不进 archive**：archive 的一行是「一个设计和它的分数」，
而被拒时没有分数可记。拒绝理由进 `declined_designs`，随最终 promote 记录落盘。

## 坏候选如何被吸收

`evolve_scope = {"*"}` 意味着候选可以改 MiniAgent 的 `runtime/**`，也就可能写出跑不起来的
harness。子进程非零退出被
[agents/miniagent/\_\_init\_\_.py](../flashrsi/agents/miniagent/__init__.py) 转成
`status="error"`，benchmark 记 0 分，候选自然落选——按分数选择本身就吸收了这件事。

已知窄口：候选若让 harness **退出码 0 却打印非预期 stdout**（改了返回字典的键名，
或往 stdout 打了东西），会抛 `JSONDecodeError` / `KeyError` 终止整个实验。
此类输出协议错误目前未被转换为候选失败分数，AHE 同样受影响。

## 参数

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `max_steps` | 10 | 迭代上限；一步 = 一次设计（含 reflection）加一次 dev 评估 |
| `num_reflections` | 2 | 评估前在同一 checkout 里复查几次；0 跳过该轮 |
| `max_evidence_chars` | 30000 | 每段证据的字符上限；archive 与组件规则各按此独立截断 |

一步的成本是 `1 + num_reflections` 次 Worker 编辑加一次 dev rollout，种子另算一次
dev rollout。

要求 dev 非空。**要求 `algorithm.worker.type: agent`**：纯 LLM Worker 不能编辑目录，
在启动时报错，不执行任何任务或模型调用。

## 来源与迁移差异

上游为 [ShengranHu/ADAS](https://github.com/ShengranHu/ADAS)（*Automated Design of
Agentic Systems*）。

**当前未固定上游 commit。** 源码中的 `Commit:` 保留待补标记，上游版本仍需核验。

本实现移植论文的搜索机制。上游 meta agent 往一个固定的
Python 框架里写 `forward()` 函数字符串；这里一个设计**就是 harness 目录本身**，
所以要求能编辑文件的 Worker。保留的是搜索机制：累积 archive、meta agent 读它产出下一个、
按实测分数入档。

具体差异：

- **设计的载体是目录，不是代码字符串。** 因此 archive 存的是
  `(Snapshot, 说明, 分数)`，而不是一段可 exec 的源码。上游那层用 DSL 描述 agent
  （`forward()` 加固定的 `Info` 结构）没有迁移——Lite 的 agent 是各 harness 自己的文件布局，
  由 `components.yaml` 表达，没有统一的 agent DSL 可以往里填。
- **archive 只有一个种子。** 上游用 CoT / Self-Consistency / Reflexion / Debate 等若干
  基线 agent 播种。这里唯一自然的种子是 target 的当前版本及其 dev 分数：那五个基线是原文
  DSL 里的具体架构，在这里没有对应物，不伪造。
- **说明走回复里的 `<DESIGN>` 标签块。** 上游把设计说明写在生成代码的字段里；这里代码是
  harness 自己的文件，说明无处安放，所以用标签块，由
  [algorithms/\_replies.py](../flashrsi/algorithms/_replies.py) 的 `tagged()` 读取，
  与 OPRO/EvoPrompt/GEPA/AHE 共用同一份。未加标签的回复整条作为说明——
  设计本体是那次编辑，说明只是给下一轮读的散文，取整条不会让搜索失效。
- **reflection 在同一个 checkout 内进行。** 上游 reflection 改的是代码字符串；这里改的是
  文件，所以两次 reflection 都在同一次 `check_out()` 里完成，只提交一次、只评估一次。
- **实际改动路径由 `Snapshot.changed_paths(candidate)` 算出**，不由 Worker 自报，
  用来识别「什么都没改」的空编辑。与 AHE 同理：文件相等指字节、组件标签和可执行位三者，
  `commit` 本来就在走同一次比较。
- **组件规则全表写进两个提示**，这是 Lite 的分类约束带来的新增内容：新增路径必须恰好匹配
  一条规则，否则整次提交被拒。
- **不合法设计拒绝本轮并记录**，理由随 promote 记录落盘，不终止实验。
- checkout 与 `discard_runtime_files` 的调用序列由 ADAS 控制，提交走基类的 `_commit()`。
- archive 随每轮决策和最终记录写入实验目录。当前 runner 不支持跨进程续跑。

## 验证状态

`--algorithm.worker.type llm` 配合 `algorithm.worker.name=null` 时由 `_check()` 在启动时拒绝，
不创建实验目录或发起模型调用。

```bash
uv run pytest tests/test_adas.py
```

机制测试覆盖：双 harness（MiniAgent / Claude Code）目录编辑与采纳、降分设计入档但不
promote、父代取 archive 领先者而非上一个候选、同分保留较早设计、archive 完整进入下一轮
提示（含历史说明与分数）、组件规则进入提示、reflection 在同一 checkout 内改写且只评估一次、
`num_reflections: 0` 跳过复查、不可分类新增路径与空编辑被拒且不终止实验（并核对 decline 与
其后 admit 各自记在正确的 step 上）、可分类新增文件正确归类、未加标签的回复仍是设计、
纯 LLM Worker 与空 dev 的启动报错、三个参数的取值范围。

**尚未运行：真实模型 smoke、任何真实 benchmark 上的演化实验、ADAS × Claude Code 的真实
演化。测试里的分数由 fixture 表格决定，仅验证接入机制与决策逻辑，不代表演化效果。**
