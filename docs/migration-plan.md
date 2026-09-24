# Benchmark 与算法迁移计划

状态：建议执行顺序，尚未开始本计划中的新组件实现。2026-09-20。

进度补记（2026-09-24）：上面的状态为计划制定时的起点。当前代码已包含 HotpotQA、
OPRO、GEPA、EvoPrompt、ACE 等后续实现；本轮新增 AHE，只实现论文默认路径（编辑永远保留，
逐条判决交给下一个 Evolve Agent），并通过机制测试及真实 Agent Worker 在真实 checkout 中
编辑的本地原生协议测试。AHE 的首个验证组合是 Terminal-Bench（需 Docker），本轮未运行，
因此步骤 7 不标记全部验收完成；范围与差异见 [AHE 迁移说明](ahe.md)。
AHE 是首个要求 `algorithm.worker.type: agent` 的算法，也是首个使用
`evolve_scope = {"*"}`（target 声明的全部组件）的算法。
同一轮按 review 意见精简了算法基类：`_evaluate` 返回的结果自带 `score` / `per_task`，
`worker.ask()` 按 mvp_doc 返回纯 `str`、由基类自动记录与脱敏，回复的解析移到
`algorithms/_replies.py`（与发问的 prompt 同一层），基类因此去掉 `_ask`、`_score`、
`_per_task`、`_tagged` 四个方法。
上一轮的 ACE 见 [ACE 迁移说明](ace.md)：online 消费 train 流，按「先执行计分、后反思更新」
记录累积在线分数；步骤 8 中 EvoMemBench 各 track 自身的学习/评测时序仍需按该 track 的协议单独设计。

本文安排迁移工作，不替代 `mvp_doc.md`，不新增或变更公共接口。旧版 FlashRSI 的实现、prompt 和测试是迁移参考，不是 Lite 的架构规范。涉及公共契约的调整，先列明具体缺口再由开发者确认。

## 目标与起点

- Benchmark：SearchQA、HotpotQA、τ³ Banking（配置名 `tau3_banking`）、Terminal-Bench 2.0、EvoMemBench。
- 方法：SkillOpt、GEPA、OPRO、ACE、EvoPrompt、AHE。
- Harness：继续使用 MiniAgent 与 Claude Code；本轮不扩大 harness 数量。
- SearchQA、SkillOpt 和两个 harness 已在 Lite 实现，已有双 harness 全量实验及保存的验收记录。用户确认双 harness 演化实验已完成，Terminal-Bench 单任务正在自行验证；其结果作为既有工作的收尾，不重复安排实现。
- 新组件逐个迁移。先完成代表性组合，再扩大交叉实验；暂不运行 5 × 6 × 2 的全部组合。

## 建议顺序

| 步骤 | 工作 | 首个验证组合 | 本步完成标准 |
| --- | --- | --- | --- |
| 0 | 固定现有基线与实际接口说明 | SkillOpt × SearchQA；收录已有 Terminal-Bench 验收 | 标记现有结果、代码版本、配置与未验收项；列出设计文档和实现的接口差异，由开发者决定规范更新 |
| 1 | 接入 HotpotQA | SkillOpt × HotpotQA | 数据、划分、输入和评分协议固定；两个 harness 可执行，小规模演化不修改 SkillOpt |
| 2 | 迁移 OPRO | OPRO × SearchQA，再到 HotpotQA | 候选生成、历史排序、搜索评分和最终版本选择通过机制测试与双 harness smoke |
| 3 | 迁移 GEPA | GEPA × HotpotQA，再到 SearchQA | 逐题评分、Pareto 选择、minibatch 筛选与评估预算正确；候选分支不污染当前版本 |
| 4 | 迁移 EvoPrompt | EvoPrompt × SearchQA，再到 HotpotQA | 先 GA、后 DE 分两次交付；种群、父代选择和各自淘汰规则正确 |
| 5 | 迁移 ACE offline | ACE × HotpotQA，再到 SearchQA | playbook 确实载入目标；Reflector/Curator、持续更新、周期验证与最终 best 恢复正确 |
| 6 | 接入 τ³ Banking | 固定 Agent 单任务，再 SkillOpt / ACE × Banking | simulator、用户交互、工具执行、环境重置和原生 reward 构成闭环；两个 harness 均有运行证据 |
| 7 | 迁移 AHE | AHE × Terminal-Bench，先 MiniAgent，后 Claude Code | Agent Worker 在 checkout 中编辑；debugger、修改声明、候选运行与下一轮归因闭环正确 |
| 8 | 分 track 接入 EvoMemBench | 单 track 固定 Agent，再 ACE；随后扩展其他方法 | 先固定记忆与顺序协议，再完成一个 track 的加载、执行和有效评分；逐 track 标注支持状态 |
| 9 | 扩大交叉实验 | 已通过接入验收的组合 | 固定数据、模型和资源预算，生成可追溯的结果矩阵；不支持的组合写明原因 |

步骤 0 是简短整理，不另建管理框架。下一次实现从步骤 1 开始，每轮只完成可独立 review 的子步骤。

## Benchmark 迁移要点

### HotpotQA

旧版入口：`../FlashRSI/src/flashrsi/benchmarks/builtin_benchmarks.py` 中 `_load_hotpotqa`，以及 `../FlashRSI/scripts/materialize_gepa_hotpotqa.py`。这些路径相对 Lite 项目根目录。

1. 先核对旧版普通 HotpotQA 与 GEPA 专用数据准备脚本的输入、上下文、划分和评分差异。
2. 明确第一版使用给定上下文还是完整检索设置；读取 fullwiki 数据源不等于已经实现完整检索评测。若采用给定上下文，实验名称和文档明确这一点。
3. 优先复用旧版固定数据版本和已核对的 grader；区分 answer EM/F1 与 supporting-fact/joint 指标，不把未实现的指标计入成绩。
4. 建议沿用旧版的 held-out 方案：从原始 train 派生训练/调参分区，将有标签的官方 dev 留作最终 test。该映射必须由适配器明确处理，不能直接套用 Lite 的通用 auto split；无标签 test 不进入本地有监督评分。
5. 第一轮交付 loader、grader、离线 fixture 和示例配置；下一轮再做真实 smoke 与一次小演化。

### τ³ Banking

旧版 `_load_tau3_banking` 指向锁定的 `tau2-bench` 仓库及 `banking_knowledge` domain；旧版 native grader 支持接收 reward。先核对这些资产是否就是本次希望运行的 τ³ Banking 版本，不以配置名推断协议一致。

- 明确用户模拟器、目标 Agent、演化 Worker 的职责和各自模型配置；不能把用户模拟器与演化 Worker 混用。
- 先完成固定 Agent 的多轮交互与工具调用，再接演化。保留会话事件、终止原因、工具结果及原生评估反馈。
- 每个独立任务/重复 trial 重置环境状态；隔离任务私有答案、用户私有信息和评分规则。
- 旧 loader 将任务放在 test，Lite 的演化需要明确的开发划分。按上游协议及关联任务结构确定分组规则，记录自定义 train/dev/test 的来源。
- 不将任务 JSON 展平成问答，也不把已有 reward 导入器当作 simulator 已完整接通的证明。
- 首次跑通后再补重复 trial 与聚合统计；先明确单次成功率与重复运行指标的报告口径。

### EvoMemBench

旧版已有 collection 与 `EvoMemTrackGrader`：部分 QA/tool-path 可本地评分，环境类 track 需要外部执行提供有效 reward。迁移前按实际数据资产核对每个 track，不宣称整体直接可用。

1. 先做 track 清单：数据、记忆输入、episode 顺序、跨 episode 持久化、执行依赖、评分器和既有验证证据。
2. 优先选择执行依赖最少且能完整复现协议的一个 track；不能仅因 grader 可运行就跳过记忆构建与读取流程。
3. 分清算法积累的状态、Agent 的可版本化资源、任务运行时记忆和评测会话状态。明确哪些状态保留、何时重置，以及 dev/test 的初始状态。
4. 若 track 要求有序学习，按其规则保持顺序和分组，不使用通用随机拆分或训练 shuffle。
5. ACE 先迁移 offline；需要 online 的 track 再单独设计学习/评测时序。在线评测若允许反馈更新，明确“先预测和计分、后更新”及反馈边界，不能直接复用 offline 最终 test 流程。
6. 每个 track 分别验收并报告；有明确上游聚合规则后再报告总分。

## 方法迁移要点

旧版方法代码位于 `../FlashRSI/src/flashrsi/algos/<method>/`，参考测试位于旧版 `tests/`。下表描述需要保留的旧实现机制，不代表已独立验证其与最新官方实现完全等价。每个方法迁移开始时核对旧版锁定的来源、prompt、默认值和已知偏差。

| 方法 | 保留的主要机制 | Lite 首版范围与重点 |
| --- | --- | --- |
| SkillOpt | 已有反思、合并、fast/slow 更新与严格 dev 筛选 | 作为现有基线维护；实验脚本中的恢复、并发等能力与核心实现分别标注 |
| OPRO | instruction–score 历史、多候选生成、旧实现的 train 搜索评分、最后选择全局最佳 | 最小的第二种算法；不加上 SkillOpt 的逐步 dev 接受门槛 |
| GEPA | 候选种群、逐题分数、Pareto parent selection、严格 minibatch 提升、验证评估及预算 | 先迁移默认路径；可选 merge 单独交付，未实现时明确报错 |
| EvoPrompt | GA 的交叉/变异及联合淘汰；DE 的 donor 约束与逐成员竞争 | GA 与 DE 分开验收；不改成只保留一个 incumbent 的循环 |
| ACE | 结构化 playbook、反思与策展、合法增量持续应用、周期验证和独立 best | 先 offline；区分 current 与 best，不为每次增量强加 dev gate；online 后续单列 |
| AHE | 逐任务 debugger、跨任务汇总、文件编辑、修改声明与效果归因 | 要求具备文件编辑能力的 Agent Worker；旧版默认延迟归因与可选保守回滚分别迁移并标注 |

文本类算法都必须明确“编辑哪个文件、如何保留原生格式、目标执行时如何加载”。MiniAgent 的 prompt 文件与 Claude Code 的补充指令/技能不等同于相同 system prompt；不能为跨 harness 表面一致而替换 Claude Code 原生 system prompt。文件路径及载入差异通过 Agent/配置处理，算法不按 harness 名称分支。

AHE 对 MiniAgent 可以覆盖源码及资源，对 Claude Code 只能覆盖其支持的配置与扩展文件；分别记录演化范围，不声称两者都能修改 harness 内部实现。新增文件必须符合目标组件规则；编辑后的源码执行沿用明确的隔离环境。纯 LLM Worker 不伪装成文件编辑 Worker。

## 每次迁移的交付与验收

每个组件按以下顺序分小步交付：

1. **核对旧实现**：列明来源版本、机制、配置、依赖、现有测试，以及本轮支持/暂缓的能力。
2. **最小实现**：Benchmark 负责数据与评分，环境交互放入 integration；Algorithm 自己拥有演化循环，状态先留在算法内部。复用 Lite 的 Snapshot、Trajectory 和实验记录，不搬入旧版 Trainer/Recipe/State 管理体系。
3. **必要测试**：Benchmark 检查数据隔离和评分；算法用固定轨迹、分数与 Worker 输出检查关键决策，复用旧机制测试的用例而非照搬旧测试框架。
4. **真实 smoke**：先固定 Agent 执行，再小预算演化，验证候选实际生效及最终选择；支持两个 harness 的组件逐一验证。
5. **可复查交付**：代码、示例 YAML、接入说明、来源/协议差异、测试结果和运行记录。分别标记离线通过、真实执行通过和全量实验完成。

公共接口确有缺口时，写出最小反例和最小调整建议后确认；不预先建设通用 simulator、memory manager、population manager 或插件系统。只有多个已迁移组件产生明确重复需求后，再抽取公共实现。

## 扩大实验的规则

- 新 benchmark 先配已稳定的方法，新方法先配已稳定的 benchmark，避免同时排查两套新实现。
- 全量实验前固定每个 benchmark 的数据版本、任务集合、评分和状态隔离协议；候选选择不得访问 offline test。
- 方法各自保留原有搜索与接受规则。横向比较记录目标任务执行次数、Worker 请求次数、tokens 和耗时，不能将相同 `max_steps` 解释为相同预算。
- 对同一 harness/benchmark 固定初始资源与任务条件；跨 harness 的原生格式、工具和可编辑范围差异明确记录。
- 分开报告机制迁移正确性、跨 harness 可运行性和演化收益。最小 smoke 不要求一定涨分；效果结论再增加独立重复运行。
- 实验矩阵中的每项标记为未接入、离线通过、smoke 通过、全量完成或不支持，并附证据路径；不支持项写明具体能力缺口。
