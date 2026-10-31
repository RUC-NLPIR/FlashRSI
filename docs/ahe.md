# AHE 迁移

AHE 采用 Agent Debugger → Evolve Agent → 归因判决流程，实现论文默认路径，
复用 Algorithm、Snapshot、Worker 和 runner。

AHE **把 harness 当目录整体演化**：Worker 拿到 checkout 自己编辑，
而不是由算法把模型产出的文本写进文件。论文的贡献不在「让 coding agent 改 harness」，
而在让这个编辑**可证伪**——动手时必须声明改了哪些文件、预测哪些任务会翻转，
下一轮用实测结果逐条判决。

## 入口和执行流程

- 主循环：[algorithms/ahe/__init__.py](../flashrsi/algorithms/ahe/__init__.py)。
- 私有 manifest 协议与归因：[\_manifest.py](../flashrsi/algorithms/ahe/_manifest.py)。
- 角色提示：[\_prompts.py](../flashrsi/algorithms/ahe/_prompts.py)。
- 小规模配置：[examples/ahe.yaml](../examples/ahe.yaml)。

先在 YAML 中分别填写 target 与 Worker 的模型、凭据及连接地址，再运行：

```bash
uv sync --extra all
uv run flashrsi run --config examples/ahe.yaml
```

默认安装已包含 Claude Code 依赖。使用该目标时将 `agent.name` 改为 `claude_code`，
并为 `agent.llm` 单独配置 Anthropic 兼容模型及端点。

1. 在 train 上执行当前版本，得到逐题分数。
2. 达到 `target_score` 即结束；否则进入本轮编辑。
3. Agent Debugger 逐条轨迹写报告（失败优先，受 `debugger_max_tasks` 限制），
   再跨任务综合一次。关掉 `use_debugger` 则 Evolve Agent 只看原始轨迹。
4. 检出当前版本，把目录交给 Evolve Agent；它用自己的原生文件工具编辑，
   并在回复里给出 manifest。
5. 提交 checkout 得到候选，**实际改动路径由 `Snapshot.changed_paths()` 算出**，
   再用它校验 manifest。不合法则拒绝本轮并记录，不终止实验。
6. 候选在同一批 train 上重新执行，逐题对比得到 `fail_to_pass` / `pass_to_fail` / `unchanged`，
   每条声明据此判决。
7. **编辑永远保留**，写入 decision 记录（`kind: "keep"`）。
8. runner 只在演化结束后评估 test；dev/test 轨迹不会交给 Debugger 或 Evolve Agent。

**train 是搜索使用的划分**：编辑所依据的证据和判它的证据是同一批
rollout。因此它不要求 dev 非空，也不能把 train 分数当作泛化结果。

## 谁来判决这次编辑

**没有分数门槛。** 一次格式正确的编辑即使 INEFFECTIVE 也被保留，因为判决本身就是给
下一个 Evolve Agent 的输入，让它决定 KEEP / IMPROVE / ROLLBACK。这是论文的机制：
分数只能说明这次编辑没起作用，判决则说明它违背了哪条承诺，所以搜索是对自己的过往编辑
做推理，而不是把它们按分数筛掉。下一轮的提示里因此同时带着逐条判决和
`rollback_sources`（被改文件的原内容）——它手上的 checkout 只有改后的版本，
没有原文就无法回滚。

判决取值：`EFFECTIVE`（声明的任务全部翻转）、`PARTIALLY_EFFECTIVE`、`MIXED`（有翻转
也有已实现的风险）、`HARMFUL`（只有风险实现）、`INEFFECTIVE`。没有任何声明预测到的回归
单独记为 `unattributed_regressions`，不并进某条改动的判决——它说明 manifest 漏了东西。

## manifest 协议

Evolve Agent 在回复里用 `<MANIFEST>...</MANIFEST>` 返回一个 JSON 对象：

```json
{
  "failure_evidence": ["task and trace evidence"],
  "root_cause": "why the harness failed",
  "targeted_fix": "what you changed",
  "changes": [
    {"path": "relative/file", "fix_tasks": ["task-id"], "risk_tasks": ["task-id"]}
  ]
}
```

- **声明路径必须与真实 diff 完全一致**。漏报一个改动文件就是一次无法被证伪的编辑，
  本轮被拒绝。真实路径由框架自己算，不采信 Worker 的自报。
- 省略 `changes` 时，用顶层 `predicted_impact` 的整体预测逐文件展开；
  每条 `changes` 未写 `fix_tasks` / `risk_tasks` 则继承整体预测，显式写空列表则是一次真实预测。
- 缺字段、非 JSON、路径不符都记为 `decline`，理由进入下一轮 Evolve Agent 的
  `declined_edits`（最近 4 条），实验继续。

## 演化范围

`evolve_scope = {"*"}` 解析为 target 自己声明的全部 component，因为「修好一个 harness 缺陷」
可能需要一个尚不存在的文件，而每个 harness 的文件布局只有它自己知道。
新增文件仍须匹配 target `components.yaml` 里恰好一个规则，否则整次提交被拒——
因此组件规则全表会写进 Evolve Agent 的提示。

两个 harness 的实际可改范围因此不同，且差异完全由各自的 `components.yaml` 产生，
算法里没有 harness 分支：

- **MiniAgent**：可改 `runtime/**` 源码、`prompts/**`、`skills/**`、`tools/**`、`agent.yaml`。
- **Claude Code**：只能改 SDK 支持的配置与扩展文件（`CLAUDE.md`、`skills/**`、`agents/**`、
  `hooks/**`、`.mcp.json`、`settings.json` 等），**不能**改 Claude Code 自身实现。

Worker 在 checkout 里运行自己的工具，也会留下这些工具的产物：导入被改过的模块会写
`__pycache__`，而 `commit` 对这类路径直接拒绝。AHE 因此在提交前调用
`core.snapshot.discard_runtime_files()` 丢弃这些已知运行时产物；真正新增的
文件仍由 target 自己的组件规则分类，归不了类就拒绝。

## 参数

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `max_steps` | 10 | 迭代上限；一步 = 一次编辑加一次候选评估 |
| `target_score` | 1.0 | train 主指标均值达到此值即提前结束 |
| `use_debugger` | true | 关掉则 Evolve Agent 只看原始轨迹 |
| `debugger_max_tasks` | 90 | 每轮最多诊断多少条轨迹，失败优先 |
| `max_evidence_chars` | 30000 | 每次角色提示中证据的字符上限 |

要求 train 非空，且 `task_id` 唯一（逐题归因的前提）。
**要求 `algorithm.worker.type: agent`**：纯 LLM Worker 不能编辑目录，在启动时报错，
不执行任何任务或模型调用。

## 来源与迁移差异

直接参考旧版 FlashRSI commit `5efe9b438483710060183c6c3ecbc5062b410a58` 的
`src/flashrsi/algos/ahe/{algorithm,manifest,prompts}.py` 与 `tests/test_ahe_trainer.py`，
其 `core/recipes.py` 锁定的上游为
[china-qijizhifeng/agentic-harness-engineering](https://github.com/china-qijizhifeng/agentic-harness-engineering)
commit `8b2a55d97590363fe50c3cc6b5e833b020a4bb4c`。该哈希沿用旧版记录，
尚未独立核验；本实现按旧实现迁移，不声称逐行复现论文实现。

保留逐任务 debugger、跨任务综合、目录编辑、修改声明、逐题归因与判决分级；
未引入旧 Trainer、Recipe、State/checkpoint 管理体系，无额外生产依赖。

与旧实现的具体差异：

- manifest 走回复里的标签块，不走 checkout 内的 `.flashrsi/change_manifest.json`。
  该路径在 Lite 归不进任何 component，会导致整次提交被拒；绕开它需要改
  [core/snapshot.py](../flashrsi/core/snapshot.py) 的运行时排除规则，影响所有 harness。
  标签块由 [algorithms/\_replies.py](../flashrsi/algorithms/_replies.py) 的 `tagged()` 读取，
  与 OPRO/EvoPrompt/GEPA 共用同一份；`Agent.ask()` 仍按 mvp_doc 返回纯 `str`。
- 实际改动路径由 `Snapshot.changed_paths(candidate)` 算出，而不是由 Worker 自报。
  「哪些文件变了」是 Snapshot 的知识——文件相等指字节、组件标签和可执行位三者，
  `commit` 本来就在走同一次比较；AHE 只是问它，不自己实现一份相等判断。
- 只迁移论文默认路径（上游 `defer_attribution_to_evolver = True`，注释标为 "The
  published mode"）。旧版另外两个 bool（`rollback_falsified_changes`、
  `allow_non_regression`）构成的保守变体未实现：它把判决权从 Evolve Agent 收回给
  分数，而纯分数门槛等价于 SkillOpt 已有的 `_select`。因此也没有 `mode` 参数。
- 证据预算统一用基类 `_evidence()`（尾部截断并标记），不再保留旧版 `clip()` 的头尾双保留。
- manifest 不合法时拒绝本轮并记录，理由进入下一轮提示；旧版直接抛出并终止整个实验。
- Debugger 调用失败直接上抛，不做旧版的逐条兜底。Lite 没有断点恢复，坏掉的 Worker 应当可见。
- 组件规则全表写进 Evolve Agent 提示，这是 Lite 的分类约束带来的新增内容。
- checkout 与丢弃运行时产物的调用序列由 AHE 控制，提交走基类的 `_commit()`。
- 演化范围不再需要 `allow_add` / `allow_remove` 开关：`{"*"}` 加上 target 自己的组件规则
  已经表达了同样的边界。

## 验证状态

- CLI：`--algorithm.max_steps 0` 由基类 `_ranges` 在启动时拒绝；
  `--algorithm.worker.type llm` 由 `_check()` 在启动时拒绝。两者都不创建实验目录、
  不发起任何模型调用。注意 `mode` 这类**已删除的参数不会报错**——按配置约定，
  各类别可以添加额外参数，未被算法读取的键会被静默忽略。

```bash
uv run pytest tests/test_ahe.py tests/test_ahe_native.py
```

机制测试覆盖：双 harness 目录编辑与采纳、无门槛保留降分版本、判决与
`rollback_sources` 传入下一轮、未预测回归单独上报、manifest 四类非法情形、空编辑、
不可分类新增路径被拒、可分类新增文件正确归类、提交时丢弃运行时产物与凭据拒绝、
`target_score` 提前结束、debugger 失败优先与综合、
纯 LLM Worker 与重复 task_id 的启动报错，以及 manifest 协议本身。

原生协议测试通过 runner、真实 MiniAgent 子进程与真实 OpenAI SDK，
用本地模拟模型服务和 SearchQA fixture：Worker 在真实 checkout 里通过自己的 `write_file`
工具编辑，提交后的版本被 target 真实加载，test 分数从 0 变为 1，判决为 `EFFECTIVE`，
`working/` 运行后为空，记录中无凭据明文。

**尚未运行远程真实模型 smoke、Terminal-Bench 组合（需 Docker）或 AHE × Claude Code 的
真实演化实验；这里的模拟分数仅验证接入机制，不代表演化效果。**
