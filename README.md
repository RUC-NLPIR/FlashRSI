# FlashRSI-Lite

按 [mvp_doc.md](mvp_doc.md) 逐步实现。当前完成配置、实验目录、CLI 准备流程、
Benchmark 核心模型与 SearchQA 接入、Snapshot 和 Agent 基类，以及 MiniAgent 和 Claude Code 后端。
现已接入 SkillOpt、OPRO、GEPA、EvoPrompt、ACE、AHE、ADAS、DarwinX、纯 LLM Worker 与 runner，可从 CLI 完成演化和最终测试。
第 7 步已新增 Terminal-Bench 2.0 数据与通用 Harbor 执行接入，Claude Code 和 MiniAgent
共用容器执行路径；MiniAgent 已默认启用 shell 工具，真实容器验收仍待完成，见 [接入说明](docs/terminal-bench.md)。
SearchQA 与 Terminal-Bench 数据均放在私有 Hugging Face 仓库
[jinjiajie/flashrsi](https://huggingface.co/datasets/jinjiajie/flashrsi)，框架按各自固定版本加载。

## DarwinX

新增 [DarwinX 迁移说明](docs/darwinx.md) 与 [示例配置](examples/darwinx.yaml)。
DarwinX 在 train 池上演化整个 harness：低成本筛选之后做重复确认，按逐任务的
preserve-and-extend 契约准入；总分提升也不能掩盖已有能力回退。
种群保留旁系和被拒绝变体的证据，支持从共同祖先重组互补分支，并检查双方任务覆盖的 union。
每个已测变体都会形成后续可读的共享经验。只有确认通过的成员能成为 mutation 父节点。

这是固定模型下的核心机制移植，已核对并固定官方 Beagle revision；完整 campaign 的
教师模型、独立 verifier 和跨 benchmark 门禁尚未移植。离线协议测试覆盖两个 harness，
真实模型效果及论文分数尚未验证。

## ADAS

新增 [ADAS 迁移说明](docs/adas.md) 与 [小规模示例配置](examples/adas.yaml)。
ADAS（Meta Agent Search）是第二个把 harness 当**目录**演化的算法，但它与 AHE 正交：
其他算法都从「当前版本」出发推理，ADAS 从**它建过的全部设计**出发——archive 完整进入提示，
一个分数很低的设计的价值就在于下一轮能看到它低。
每轮取 archive 中的领先者作为父代交给 meta agent 编辑，按 `num_reflections` 在同一个
checkout 里自我复查，然后在 dev 上评估。**无论升降都进入 archive**（这是机制而非容错），
但 incumbent 只在提升时移动，结束时选中 archive 里分数最高的设计。
与 AHE 的分工是问责方式相反：AHE 保留每个合法编辑并用 manifest 逐条判决，
ADAS 用分数决定去留。因此它同样要求 `algorithm.worker.type: agent`，
纯 LLM Worker 在启动时报错；dev 是搜索唯一读的划分，train 不使用。
本轮只完成离线机制测试（17 条，覆盖双 harness 目录编辑、archive 传递、reflection、
拒绝路径与启动校验）；**真实模型 smoke、真实 benchmark 演化与上游 commit 核验均未完成。**

## AHE

新增 [AHE 迁移说明](docs/ahe.md) 与 [小规模示例配置](examples/ahe.yaml)。
AHE 是目前唯一把 harness 当**目录**整体演化的算法：Worker 拿到 checkout 自己编辑，
而不是由算法把模型产出的文本写进文件，因此它要求 `algorithm.worker.type: agent`，
纯 LLM Worker 在启动时报错。每次编辑必须声明改了哪些文件、预测哪些任务会翻转；
实际改动路径由 diff 算出，声明对不上即拒绝该轮——说不出要修什么的编辑无法被证伪。
编辑**永远保留**，不设分数门槛：逐条判决（`EFFECTIVE` / `INEFFECTIVE` / `HARMFUL` 等）
连同原文件内容交给下一个 Evolve Agent，由它决定 KEEP / IMPROVE / ROLLBACK。
分数只能说明一次编辑没起作用，判决则说明它违背了哪条承诺，所以搜索对自己的过往编辑做推理，
而不是把它们按分数丢掉。
演化范围是 target 自己声明的全部 component，两个 harness 的实际可改范围因各自
`components.yaml` 而不同，算法中没有 harness 分支。
本地原生协议测试已验证真实 Worker 在真实 checkout 中编辑并使 test 分数改变；
远程真实模型 smoke、Terminal-Bench 组合与演化收益尚未验证。

## ACE

新增 [ACE 迁移说明](docs/ace.md) 与 [小规模示例配置](examples/ace.yaml)。
ACE 通过 Reflector/Curator 积累结构化 playbook，合法增量持续应用。
`mode: offline`（默认）按 `eval_steps` 周期评估 dev，结束后恢复 dev 最佳版本；
`mode: online` 按原顺序流式消费 train，每批先执行计分再反思更新，不访问 dev，
保留最后版本并单独记录累积在线分数，与最终 test 分开口径。
保留目标原生指令；同一算法支持 MiniAgent 与 Claude Code，已通过双 harness 本地原生协议测试。
远程真实模型 smoke 与演化收益尚未验证。

## SkillOpt

DeepSeek-v4-flash 答题、DeepSeek-v4-pro 演化，分别运行 MiniAgent / Claude Code 的
SearchQA 实验入口与论文对照见[双 harness 实验说明](docs/searchqa-deepseek-reproduction.md)。
该独立脚本支持本地凭据注入、官方评分、固定划分、请求恢复和初始/最终测试对照。

先在 `example.yaml` 中填写目标和 Worker 的模型、API key 和连接地址，
安装所选后端依赖后运行，例如 MiniAgent 目标与纯 LLM Worker：

```bash
uv sync --extra miniagent --extra llm --extra dev
uv run flashrsi run --config example.yaml \
  --algorithm.num_epochs 1 --algorithm.max_steps 1 --benchmark.limit 6
```

模型和连接分别配置在 `agent.llm` 与 `algorithm.worker.llm`。上面的命令会调用模型；
省略小规模覆盖时使用默认训练参数。Claude Code 目标需要 `claude-code` extra，
通过 `--agent claude_code --model <Anthropic兼容模型>` 选择；Worker 可继续使用纯 LLM。
Agent Worker 设置 `algorithm.worker.type: agent` 和 `algorithm.worker.name`，
可选 `miniagent` 或 `claude_code`，使用它自己的模型和原生配置。

流程集中在 [SkillOpt](flashrsi/algorithms/skillopt/__init__.py)：

1. 初始化时加载 benchmark、设置范围；演化开始时在 dev 集评估初始版本。
2. 每个 epoch 按 `seed + epoch` 打乱 train，依次执行 batch。
3. 每个 reflection minibatch 分别分析失败与成功轨迹，生成结构化编辑。
4. 按来源分组、分层合并；超过预算时由 Worker 排序选择。
5. 通过 Snapshot checkout/commit 生成候选，在 dev 上严格提升才 `update`；平分也拒绝。
6. 从第二个 epoch 末开始，在同一批训练任务上比较相邻 epoch 版本，更新优化器记忆及长期指导。
7. runner 最后只对选中的版本评估一次 test，不将 test 反馈交给 Worker。

`Algorithm(config, *, target, worker, benchmark)` 统一补齐算法默认配置、按 `_ranges`
校验参数、设置目标 scope、加载 benchmark 并检查通用执行能力，最后调用 `_check()`
完成算法自己的检查。
runner 不重复加载数据，`evolve()` 直接组织演化流程并返回最终 `Snapshot`，
选中的版本同时保留在 `target.snapshot`。算法不按 harness 或 benchmark 名称分支。

算法在类上声明 `evolve_scope` 和 `observation_scope`。基类将 observation 中的组件设为
`r`，evolve 中的组件设为 `rw`，重叠时以 `rw` 为准；未声明组件隐藏。
SkillOpt 两者均为 `{"skill"}`。写成 `{"*"}` 表示 target 声明的全部组件，
供把 harness 当目录整体演化的方法使用（AHE）——这类方法无法枚举组件名，
因为每个 harness 的文件布局只有它自己知道。组件校验直接由 `Agent.set_scope()` 完成；
参数类型与取值范围由类上的 `_ranges` 声明，基类在初始化时统一校验，
`_check()` 只留下需要数据或 target 才能判断的语义前置条件，例如非空 train/dev、
`instruction_file` 是否落在可演化组件内，不重复检查参数类型或 metric 契约。
scope 控制目标快照的编辑目录；目标执行任务仍使用完整版本。

实现按职责阅读：

| 位置 | 职责 |
| --- | --- |
| `core/algorithm.py` | 初始化与 `_ranges` 参数校验、`_evaluate`、Worker 调用的自动记录、`_instruction_path`、`_promote`、`_evidence`/`_trajectory_evidence`、按 scope 读取文本、候选文件提交（`_candidate` 写文本、`_commit` 收下 Worker 编辑过的目录）、轨迹与 Snapshot 保存 |
| `algorithms/skillopt/__init__.py` | `evolve` 主流程、反思、合并排序、slow/meta update、接受或拒绝候选 |
| `algorithms/skillopt/_patch.py` | 编辑响应解析、精确锚点、预算与保护区、slow guidance 应用 |
| `algorithms/skillopt/_prompts.py` | 算法使用的 prompt 模板 |
| `algorithms/opro/__init__.py` | OPRO 的搜索循环、历史排序、候选采样与最终提升 |
| `algorithms/opro/_prompts.py` | OPRO 的元提示与历史行模板 |
| `algorithms/gepa/__init__.py` | GEPA 的迭代循环、parent 选择、minibatch 筛选、种群准入与最终提升 |
| `algorithms/gepa/_pareto.py` | 逐题 Pareto frontier 与支配剪枝 |
| `algorithms/gepa/_prompts.py` | GEPA 的反思重写提示 |
| `algorithms/evoprompt/__init__.py` | EvoPrompt 的种群初始化、GA/DE 单代演化与最终提升 |
| `algorithms/evoprompt/_prompts.py` | EvoPrompt 的 GA、DE 与 paraphrase 模板 |
| `algorithms/ace/__init__.py` | ACE 的训练反思、增量应用、offline 周期验证与最佳版本恢复、online 流式计分 |
| `algorithms/ace/_playbook.py` | ADD 协议、section、bullet 编号、计数与精确去重 |
| `algorithms/ace/_prompts.py` | Reflector、Curator 和训练重试提示 |
| `algorithms/ahe/__init__.py` | AHE 的诊断、目录编辑、逐题归因与判决 |
| `algorithms/ahe/_manifest.py` | 修改声明的解析与 diff 校验、逐题归因、判决分级与证伪路径 |
| `algorithms/ahe/_prompts.py` | Agent Debugger 逐条/综合提示与 Evolve Agent 提示 |
| `algorithms/adas/__init__.py` | ADAS 的 archive 搜索循环、目录编辑与 reflection、按分数入档 |
| `algorithms/adas/_prompts.py` | meta agent 的产出提示与自我复查提示 |
| `algorithms/darwinx/__init__.py` | train 种群演化、筛选与重复确认、目录 mutation/recombination、经验蒸馏 |
| `runner.py` | 实例化组件、创建实验目录、运行演化与最终 test、保存摘要 |

算法要问的东西尽量由它手上的对象回答，而不是由基类再加一个方法。

`_evaluate(snapshot, tasks)` 返回的 `Results` 自带 `score`（benchmark `primary_metric`
的均值，即算法的适应度）和 `per_task`（逐题分数，供 GEPA 的 Pareto 前沿或 AHE 的编辑归因
这类无法用均值表达的比较使用），所以算法不接触 `primary_metric`。它同时仍是一个
Trajectory 的 tuple，`for` / `len()` / `zip()` 照旧可用；切片会退化成普通 tuple 并丢掉
分数，因为一个子集从未被作为整体测量过。空评估没有分数，读 `score` 会报错。

`await self.worker.ask(prompt)` 按 mvp_doc 的签名返回纯 `str`，失败时抛错。
要让 Worker 编辑一个目录则用 `await self.worker.edit(working_dir, prompt)`：
编辑本身是目录的新内容，返回值是它对这次编辑的说明（AHE 的 manifest 就在里面）。
两者都不提交 Snapshot，版本化由调用方决定。
回复被包成 `<INS>` 标签还是代码块，是**发问的那个 prompt** 自己决定的，
所以解析不在 `Agent` 上，而在 [algorithms/_replies.py](flashrsi/algorithms/_replies.py)：
`tagged(reply, tag)` 取最后一对闭合标签内的整段文本，`fenced(reply)` 取最后一个闭合代码块，
OPRO、EvoPrompt、GEPA、AHE 共用这一份。
**Worker 调用的轨迹记录、凭据脱敏和失败报错由基类自动完成**，算法不为这一笔调 `_record`，
记录文件统一命名为 `00001-worker.json`；阶段由 prompt 首行的 `[ACE: curate]` 这类标记区分。

基类的 `_evaluate` 不更新目标版本。`_candidate` 接收文本文件更新，保留未指定文件，
通过 Snapshot 检查权限并生成候选，不自动接受。`_read_text` 只读取 observation/evolve
声明的组件，二进制资源保留不改。由 Worker 自己编辑目录的算法（AHE、ADAS、DarwinX）改用
`_commit`：字节来自算法控制不了的进程，所以提交前扫一遍凭据，扫的正是将被版本化的内容。
它们先用 `Snapshot.discard_runtime_files()` 丢弃 `__pycache__` 一类已知运行时产物
（`commit` 对它们直接拒绝，否则一次编辑白跑），真正新增的文件仍由 target 的组件规则分类，
归不了类照样拒绝。需要删除文件或修改二进制的算法直接使用 Snapshot 接口。
runner 的最终 test 也复用 `_evaluate`；记录与算法内评估采用相同格式。

`_evaluate` 的可选关键字参数 `label` 只用于轨迹文件名，不影响模型输入或算法决策，
默认为 `evaluation`；记录文件按调用顺序命名为 `00001-<label>.json`。

其余共享动作在基类：`_instruction_path()` 返回 target 自己声明的 `instruction_file`
并校验它落在算法可编辑的组件内；`_promote(current, best, **details)` 在搜索结束时
选中一个版本，写入 `kind: "promote"` 决策记录，`details` 里放算法自己的搜索状态
（OPRO 的 `history`、GEPA 与 EvoPrompt 的 `population`）。
写 Worker 提示时，`_evidence(rows)` 把行编码为 JSON 并按 `max_evidence_chars` 截断，
截断处补省略号；`_trajectory_evidence(traj)` 给出整条轨迹并去掉 `RunConfig`。
选哪些字段进 prompt 仍由算法自己决定，基类只统一编码、上限和解析。
需要把上游 CLI 的别名规范化时重写 `_normalize()`，它在 `_ranges` 校验之前执行，
因此保存的配置记录的是实际运行的名字。

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `num_epochs` | `4` | train 遍历次数 |
| `batch_size` | `40` | 每次 fast update 的训练任务数 |
| `reflection_minibatch_size` | `8` | 每次反思的最大任务数，成功/失败分别调用 |
| `edit_budget` | `4` | 一次 fast update 最多应用的编辑条数 |
| `merge_batch_size` | `8` | 一次合并最多输入的同源 patch 数，至少 2 |
| `seed` | `42` | batch 调度与 slow update 抽样种子 |
| `max_steps` | 空 | fast update 批次数上限；不是模型调用次数上限 |
| `success_threshold` | `0.0` | finished 且主指标大于该值才归为成功 |
| `use_slow_update` | `true` | 比较相邻 epoch，更新 skill 内的长期指导 |
| `use_meta_skill` | `true` | 根据相邻 epoch 结果更新仅供优化器使用的记忆 |
| `slow_update_samples` | `20` | 每次比较最多抽样的训练任务数 |

所有筛选均使用 `benchmark.primary_metric`，按任务取平均；要求 train/dev 非空。
达到 `max_steps` 时不再开始新的 batch；完整 epoch 已结束时仍执行其 epoch-end update。
空 patch 跳过候选评估，但继续后续 batch。最近 5 个被拒绝的 fast patch 进入下一次反思。

Worker 统一调用 `run(prompt)` 返回 JSON 文本，SkillOpt 应用编辑，不让 Worker 直接写目标目录。
编辑协议属于算法私有实现，支持 `append`、`insert_after`、`replace`、`delete`，每条指定
文件路径，后三种要求唯一、精确的文本锚点。支持多个 UTF-8 skill 文件；二进制支持资源保留不改。
空 skill 目录允许 Worker 新建符合组件规则的原生技能；MiniAgent 通常应修改已启用的
`skills/main.md`，新增文件是否会加载仍由其原生配置决定。Claude Code 采用
`skills/<name>/SKILL.md` 与原生 frontmatter；算法不会修改默认 harness 的 seed 文件。

fast edit 不能修改或引入 `SLOW_UPDATE_START/END` 保护区；只有 slow update 能写入。
保护区校验是 SkillOpt 的编辑规则，Snapshot 的 scope 仍只表达文件权限。
本 MVP 将 slow candidate 也纳入严格 dev 筛选，避免其接受后遗留过期的 baseline 分数。
这是对旧版流程的明确调整；多文件协议、无自动恢复和严格解析也与旧版不同，
本实现不宣称逐字复现官方 prompts 或论文数值。Worker 错误、非法 JSON、歧义锚点和越界
编辑直接报错，保存已有证据，不静默替换为另一种优化策略。

纯 LLM Worker 的 `llm` 使用 OpenAI-compatible Chat Completions：
`model_name`、`api_key`、`base_url` 分别映射到模型与客户端，其他请求参数直接传给 SDK。
凭据须显式提供；地址留空时使用 `https://api.openai.com/v1`。角色层 `timeout` 默认 300 秒，
`max_retries` 默认 1；不隐式继承目标配置。该 Worker 无 Snapshot，也不支持 `edit`
（带 `working_dir` 的文件编辑）。空回答、截断回答及未完成的工具调用返回 error Trajectory。

实验目录包含解析后的配置（含算法默认值）、以版本 ID 命名的初始与候选 Snapshot、
每次 Worker 调用的 prompt/Trajectory、train/dev 评分轨迹、候选接受记录，以及
按调用顺序编号的 `trajectories/*-test.json` 和最终 `result.json`。Agent Worker 的版本额外保存为
`snapshots/worker.json`。失败保存 `error.json` 并返回非零状态；配置与运行记录脱敏。
Snapshot 保留原始文件内容，不能把凭据写入 seed 文件；候选检查已知运行凭据。
当前不支持断点续跑或并发调度；Terminal-Bench 环境任务由 runner 绑定 Harbor 执行。
直接 Python 使用不配置实验目录时结果保留在内存。

第 6 步验证包含本地模拟服务上的真实 MiniAgent 子进程/OpenAI SDK、Claude SDK/CLI
演化闭环，以及算法、scope、持久化与失败行为的离线测试；未调用真实付费模型。

## OPRO

第二个算法，用来检验「算法一行不改跨 harness」的契约：与 SkillOpt 相比，OPRO 的
编辑粒度、评分集、接受时机和目标组件全部不同，但两者使用同一套公共接口。

| | SkillOpt | OPRO |
| --- | --- | --- |
| 编辑粒度 | 锚点增量 patch | 整体重写一个文件 |
| 评分集 | dev，严格提升才接受 | train，搜索评分 |
| 接受时机 | 每个候选当场接受或拒绝 | 全程不动当前版本，结束时提升全局最优 |
| 目标组件 | `skill` | `prompt` |

```bash
uv run flashrsi run --config examples/opro.yaml \
  --algorithm.max_steps 2 --algorithm.num_candidates 2 --benchmark.limit 12
```

流程集中在 [OPRO](flashrsi/algorithms/opro/__init__.py)：

1. 读取目标指令文件的当前文本，在 train 上评分，作为历史第 0 行。
   Claude Code 的 seed 没有 `CLAUDE.md`，此时基线文本为空，即其原生 prompt。
2. 每个 step 取历史中分数最高的版本作为 parent；平分时保留较早的指令。
3. 元提示展示按分数升序的 instruction–score 历史，以及当前最优指令实际产生的轨迹。
4. 对同一个元提示采样 `num_candidates` 次；空指令和与历史重复的指令直接丢弃，
   不重新采样，因此一个 step 可能产出少于 `num_candidates` 个候选。
5. 每个候选整体重写该指令文件，在 train 上评分后加入历史。
   搜索期间不调用 `update`，所有候选都相对同一基线评分。
6. 搜索结束后一次性提升全局最优版本，并记录完整历史池。
7. runner 随后只对选中的版本评估一次 test。

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `max_steps` | `200` | 优化器搜索步数 |
| `num_candidates` | `8` | 每步采样的指令数 |
| `history_size` | `20` | 元提示展示的历史行数上限 |
| `score_threshold` | `0.1` | 低于该分数的历史行不进入元提示 |
| `few_shot_size` | `3` | 元提示展示的轨迹条数 |
| `max_evidence_chars` | `24000` | 轨迹证据的字符上限 |
| `seed` | `42` | 证据抽样种子 |

改哪个文件完全由目标 Agent 声明，没有对应的配置项：`algorithm` 段只放算法自己的
超参数，目标的文件布局由 Agent 表达。Agent 基类提供 `instruction_file`，MiniAgent
声明 `prompts/system.md`（`prompts/extract.md` 服务证据摘要，不是 Agent 的指令），
Claude Code 声明 `CLAUDE.md`（原生的可选补充指令位，文件由算法新建）。算法只向
Agent 询问这个路径，不按 harness 名称分支。声明为空、或声明的路径不在目标的
`prompt` 组件内（即超出 OPRO 可演化的范围）时，启动报错并列出该 Agent 自己的
prompt 规则。
`evolve_scope` 与 `observation_scope` 均为 `{"prompt"}`；同组件的其他文件
可读但不被改写。OPRO 不使用 dev，因此 `_check()` 不要求 dev 非空。

默认值 `max_steps=200`、`num_candidates=8` 与论文一致，意味着约
`max_steps × num_candidates × len(train)` 次目标执行。实跑时用上面的命令行覆盖，
或用 `benchmark.limit` 控制规模。

与旧版和 upstream 的三处明确差异：

- 只保留 `<INS>` 指令模板，不迁 `instruction_pos` 的四个插入位置。Lite 把指令写成
  harness 原生加载的指令文件，框架控制不了它在 QA prompt 中的位置，`A_begin` 的
  「答案起始句」语义在这里不成立。解析仍取最后一对闭合标签，避免读到模型复述的请求。
- 元提示中的轨迹证据复用该指令进入历史时已评分的 train 轨迹，不为取证据额外重跑。
  证据与同一行展示的分数同源，按默认值省去约 600 次目标执行。搜索与接受规则不变。
- 本实现不宣称逐字复现官方 prompts 或论文数值。

## GEPA

第三个算法，与 OPRO 同为整体重写一个 prompt 文件，区别在选择机制：OPRO 始终从
分数最高的指令出发，GEPA 保留一个按 dev 逐题分数构成的种群，并在候选进入 dev
全量评估前先用 minibatch 筛一遍。

| | OPRO | GEPA |
| --- | --- | --- |
| 评分集 | train，搜索评分 | train minibatch 筛选 + dev 全量 |
| 选择单位 | 历史中的全局最优单点 | dev 逐题分数构成的 Pareto 种群 |
| 候选来源 | 同一元提示采样多个候选 | 每轮一个反思重写，先筛后评 |
| 预算 | `max_steps × num_candidates` | `max_metric_calls` 计目标执行次数 |

```bash
uv run flashrsi run --config examples/gepa.yaml \
  --algorithm.max_metric_calls 30 --benchmark.limit 24
```

流程集中在 [GEPA](flashrsi/algorithms/gepa/__init__.py)：

1. 在 dev 上评估初始版本，逐题分数与均分构成种群成员 0。
   Claude Code 的 seed 没有 `CLAUDE.md`，此时基线文本为空，即其原生 prompt。
2. 每轮迭代按 Pareto frontier 采样 parent：一个成员只要在**某一道** dev 题上
   得分最高就保持可选，因此均分落后的分支不会被过早淘汰。
3. 在 train 上抽 `reflection_minibatch_size` 个任务执行 parent，这批轨迹既用于
   minibatch 对照，也是反思读取的证据，不额外付一次执行。
4. Worker 基于该证据整体重写目标的指令文件。
5. 候选先在同一 minibatch 上对照 parent，未严格提升则丢弃，不进入 dev 全量评估。
6. 通过筛选的候选在 dev 全量评分后加入种群，记录逐题分数与 parent 索引。
   加入种群不等于提升：搜索期间不调用 `update`，所有候选都相对同一基线评分。
7. 预算耗尽后一次性提升均分最优的成员，并记录完整种群。
8. runner 随后只对选中的版本评估一次 test。

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `max_metric_calls` | `null` | 目标执行预算；`null` 时按数据规模推导 |
| `reflection_minibatch_size` | `3` | 每轮反思与筛选使用的 train 任务数 |
| `candidate_selection_strategy` | `pareto` | `pareto` 或 `current_best` |
| `max_evidence_chars` | `24000` | 轨迹证据的字符上限 |
| `seed` | `42` | parent 采样与 minibatch 抽样种子 |
| `use_merge` | `false` | 上游的 system-aware merge，本轮未实现，置 `true` 报错 |

单轮迭代消耗 `2 × reflection_minibatch_size + len(dev)` 次目标执行。
`max_metric_calls` 为 `null` 时取 `max(100, len(dev) + 10 × 单轮开销)`，
即基线评估加十轮迭代；预算不足一轮时在执行前报错并给出所需下限。
预算在 `evolve()` 开始时解析一次，不随搜索过程变化。

改哪个文件完全由目标 Agent 声明，没有对应的配置项：与 OPRO 读同一个
`instruction_file`（MiniAgent 为 `prompts/system.md`，Claude Code 为 `CLAUDE.md`），
算法只向 Agent 询问这个路径，不按 harness 名称分支。声明为空、或声明的路径不在
目标的 `prompt` 组件内（即超出 GEPA 可演化的范围）时，启动报错并列出该 Agent
自己的 prompt 规则。
`evolve_scope` 与 `observation_scope` 均为 `{"prompt"}`；同组件的其他文件
（如 MiniAgent 的 `prompts/extract.md`）可读但不被改写。GEPA 按逐题分数构建
frontier，因此 `_check()` 额外要求 dev 的 `task_id` 唯一。

与旧版和 upstream 的四处明确差异：

- 只迁移默认路径。`use_merge` 的 system-aware crossover 未实现，置 `true` 时
  启动报错而非静默退化为普通迭代。
- 每轮只重写一个指令文件，不迁上游按 module 轮换的机制。上游优化的是 compound
  system（一条 pipeline 含多个 module），而 Lite 的两个 harness 各自只声明一个
  `instruction_file`，轮换在此没有使用者。将来出现多指令文件的 harness 再补。
- frontier 只按 dev 逐题分数构建，不迁旧版的 `objective`/`cartesian`/`hybrid`
  变体与 `top_k_pareto`、`epsilon_greedy` 选择策略。逐题分数是论文机制的核心，
  其余变体属于旧版自行扩展，未单独验证。
- 证据是 FlashRSI 的 Trajectory 与其评分，不是上游的 assistant response 加
  自然语言 feedback；prompt 正文保持上游文本，便于逐行核对。

本实现不宣称逐字复现官方 prompts 或论文数值。空提议、与 parent 相同的提议和与
种群中已有成员重复的提议分别记录为 `empty_proposal`、`unchanged_instruction` 和
`duplicate_instruction`，都不产生候选也不消耗筛选预算。Worker 调用本身失败时
直接报错并保存已有证据，与 SkillOpt 一致，不静默跳过该轮或替换为另一种搜索策略。

## EvoPrompt

第四个算法，同样整体重写一个 prompt 文件。与前三个的区别在于它维护一个固定大小的
**种群**，每代用进化算子批量产生候选：GA 先造出完整子代再统一淘汰，DE 逐位置用三个
donor 构造 trial 并成对替换。

| | GEPA | EvoPrompt |
| --- | --- | --- |
| 选择单位 | dev 逐题分数构成的 Pareto 种群 | 固定大小的种群，按 dev 均分排序 |
| 候选来源 | 每轮一个反思重写 | 每代 `population_size` 个算子输出 |
| 算子输入 | parent 的轨迹证据 | 种群中其他成员的文本 |
| 淘汰时机 | 通过 minibatch 筛选才进种群 | GA 代末统一淘汰；DE 逐成员成对竞争 |

```bash
uv run flashrsi run --config examples/evoprompt.yaml \
  --algorithm.population_size 4 --algorithm.max_steps 2 --benchmark.limit 12
# DE 变体（需要 population_size >= 4）：
uv run flashrsi run --config examples/evoprompt.yaml --algorithm.variant de \
  --algorithm.population_size 4 --algorithm.max_steps 2 --benchmark.limit 12
```

流程集中在 [EvoPrompt](flashrsi/algorithms/evoprompt/__init__.py)：

1. 读取目标指令文件的当前文本，在 dev 上评分，作为种群成员 0。
   Claude Code 的 seed 没有 `CLAUDE.md`，此时基线文本为空，即其原生 prompt。
2. 反复让 Worker 改写该文本，补足到 `population_size` 个成员，每个都在 dev 上评分。
   与上游从任务专属的 prompt 文件播种不同，这里的种子是目标 harness 自带的指令。
3. 每代按 `variant` 执行一次进化：
   - `ga`：按 `selection` 取 `population_size` 对父代，crossover + mutate 得到子代，
     再按 `survivor_selection` 在「父代 + 子代」中统一淘汰。
   - `de`：对每个成员取三个不同 donor 构造 trial，严格高分才替换该成员，
     其余成员原样保留。
4. 算子返回空文本或与 parent 相同的文本时保留 parent 的快照与分数，不提交候选也不
   重复评分。这种成员在记录中标记 `carried: true`，便于与「真的评出同样分数的候选」
   区分；它仍是独立的一条记录，不与 parent 共用对象，否则 `topk` 补齐时会把较优
   prompt 的所有副本一次排除掉。
5. 搜索期间不调用 `update`，所有成员都相对同一基线评分；每代记录候选与存活种群。
6. 结束后一次性提升全局最优成员，并记录完整种群。
7. runner 随后只对选中的版本评估一次 test。

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `variant` | `ga` | `ga` 或 `de` |
| `population_size` | `10` | 种群大小；`ga` 至少 2，`de` 至少 4 |
| `max_steps` | `10` | 进化代数 |
| `selection` | `wheel` | 仅 GA：`wheel`、`random`、`tournament`（接受上游写法 `tour`） |
| `survivor_selection` | `topk` | 仅 GA：`topk` 保留最优的不同文本，`standard` 直接保留子代 |
| `donor_random` | `false` | 仅 DE：`false` 用全局最优作为 base vector |
| `seed` | `42` | 父代采样、donor 采样与 wheel 重采样种子 |

一次运行约消耗 `population_size × (1 + max_steps) × len(dev)` 次目标执行：
初始化每个成员一次，之后每代每个候选一次。默认值 `population_size=10`、
`max_steps=10` 与论文一致，实跑时用上面的命令行覆盖，或用 `benchmark.limit` 控制规模。

改哪个文件完全由目标 Agent 声明，没有对应的配置项：与 OPRO、GEPA 读同一个
`instruction_file`，算法只向 Agent 询问这个路径，不按 harness 名称分支。声明为空、
或声明的路径不在目标的 `prompt` 组件内时，启动报错并列出该 Agent 自己的 prompt 规则。
`evolve_scope` 与 `observation_scope` 均为 `{"prompt"}`。EvoPrompt 只用 dev 评分，
因此 `_check()` 只要求 dev 非空，不要求 train。

与旧版和 upstream 的四处明确差异：

- GA 与 DE 同时迁移，两者共用初始化、候选提交、提升和解析，只有一代之内的算子与
  淘汰规则不同。`variant` 的取值在启动时校验，不支持的值直接报错。
- 种群从目标 harness 自带的指令播种并由 Worker 改写补齐，不迁上游按任务准备的
  初始 prompt 文件列表；对应地没有 `initial_prompts` 配置项。
- 算子返回空文本或 parent 原文时保留 parent 的快照与分数，不提交一个内容相同的候选。
  旧版会为这种情况再跑一次完整评估，在 Lite 中这是一次没有信息量的 dev 开销。
  DE 的 donor 按**位置**排除，不按对象身份，这既是上游的语义（走 population 下标），
  也避免与这一优化耦合。
- `topk` 按文本去重后再补齐到固定大小，这是上游的原意：一代 mutation 全部塌缩到
  同一个 prompt 时，种群不会被它的副本填满，但下一代仍有足够成员可抽父代。

本实现不宣称逐字复现官方 prompts 或论文数值。prompt 模板保持上游原文（含其自带的
worked example），解析取最后一对闭合的 `<prompt>` 标签，避免读到模型复述的模板示例。
Worker 调用本身失败时直接报错并保存已有证据，与其他算法一致。

## 安装与验证

需要 Python 3.11+。在本目录执行：

```bash
uv venv --python 3.11
uv pip install -e '.[dev]'
uv run pytest
```

## 命令行

安装后，使用 `flashrsi run`。当前提供 `--prepare-only`，读取并校验配置、
自动创建实验目录和保存配置：

```bash
uv run flashrsi run --config example.yaml --prepare-only
```

也可以直接传入设计中的常用参数：

```bash
uv run flashrsi run \
  --benchmark searchqa \
  --algorithm skillopt \
  --agent miniagent \
  --model gpt-5 \
  --worker-model gpt-5 \
  --prepare-only
```

`--model` 对应 `agent.llm.model_name`，`--worker-model` 对应
`algorithm.worker.llm.model_name`。`--output-dir` 设置实验输出根目录。
所有配置参数都支持 `--完整.字段.路径 值` 或 `--完整.字段.路径=值`，层级不受限制。
新增参数无需注册 CLI 选项，值按 YAML 解析：

```bash
uv run flashrsi run --config example.yaml --prepare-only \
  --benchmark.limit 20 \
  --algorithm.rounds 3 \
  --algorithm.worker.llm.model_name gpt-5 \
  --algorithm.worker.llm.temperature=0.7 \
  --agent.tools '[{name: search, timeout: 30}]'
```

也保留可重复的 `--set 路径=值` 写法：

```bash
uv run flashrsi run --config example.yaml --prepare-only \
  --set benchmark.limit=20 \
  --set algorithm.rounds=3 \
  --set algorithm.worker.llm.temperature=0.7 \
  --set 'agent.tools=[{name: search, timeout: 30}]'
```

优先级为默认值 < YAML < 常用命令行参数 < 点路径参数和 `--set`。
点路径参数和 `--set` 混用时，同一路径以最后一次设置为准；两者都优先于常用参数。
省略的参数保留 YAML 中的值；列表可整体设置，路径指向映射中的键。
负数可直接作为值；以 `-` 开头的普通字符串使用等号写法，例如 `--agent.prompt=-text`。

`python -m flashrsi` 与 `flashrsi` 使用同一入口，`flashrsi run --help` 查看参数。
不加 `--prepare-only` 时执行 `algorithm.name` 选择的演化算法，结束后评估 test 集并保存结果。
准备模式仍不下载数据或调用模型。不支持的算法、Agent 和 Benchmark 名称会在执行前报错。

## 配置

以 [example.yaml](example.yaml) 为准。`load_config` 返回支持属性访问的 `Config`：

| 部分 | 字段 | 用途 |
| --- | --- | --- |
| `run` | `output_dir` | 实验输出根目录 |
| `benchmark` | `name`, `split` | Benchmark 与自动/比例划分策略 |
| `agent` | `name`, `llm` | 被演化和评估的目标 Agent，拥有独立模型配置 |
| `algorithm` | `name`, `worker` | 演化算法及它使用的 Worker |

每个类别及 `algorithm.worker` 都可直接添加额外参数，无需修改配置类。
额外参数支持嵌套映射和列表，并会在覆盖、保存、重新加载时保留。
配置层继续校验已有公共字段；额外参数的含义由对应模块处理。

```python
config = load_config("example.yaml")
print(config.benchmark.name)
print(config.algorithm.worker.llm.model_name)

config.benchmark.limit = 100
config.algorithm.worker.llm.temperature = 0.7
```

也支持 `config["benchmark"]["name"]` 和 `.get()` 等字典操作。
与字典方法重名的参数（如 `items`），或包含连字符的参数，用方括号访问。
顶层仍为上述四个类别。`benchmark.split` 默认是 `auto`：

```yaml
benchmark:
  name: searchqa
  split: auto
```

- 已有 train/dev/test：保留源分区归属；`validation` 映射为 dev。
- 只有 train，或单个没有分区信息的数据文件：按 60%/20%/20% 划分。
- 已有 train 和 dev、缺少 test：保留 dev，从 train 留出 20% 给 test。
- 已有 train 和 test、缺少 dev：保留 test，从 train 留出 20% 给 dev。

空分区视为缺失。自动划分只使用训练或未分配数据补齐分区；已有 dev/test
不会被移入 train。只有 dev/test 而没有训练数据时会明确报错。auto 保证三个
分区各至少一条，数据不足以独立划分时会报错，避免演化使用空分区或重复任务。

也可以显式指定 `split: {train: 0.6, dev: 0.2, test: 0.2}`：合并所有源分区后
按指定比例重划分。各比例在 0 到 1 之间，总和必须为 1，允许零比例。
为兼容已有配置，比例映射缺少的键仍从 0.6/0.2/0.2 补齐后校验。
CLI 可用 `--benchmark.split auto`，或用点路径覆盖比例字段。

目标 Agent 与 Worker 各自拥有 `llm`，两者不继承模型、连接地址、凭据或请求参数。
`llm` 内放 `model_name`、`api_key`、`base_url` 以及后端支持的模型请求参数；
`timeout`、`max_turns`、工具权限和 `source_dir` 放在执行者这一层。
Snapshot 中的原生配置文件则控制所选版本的 skills、工具、hooks 等行为。

`algorithm.worker.type` 可以是 `llm` 或 `agent`，两种 Worker 使用相同的 `llm`
结构。当 `type: agent` 时，还需要 `name` 来选择 harness，例如：

```yaml
agent:
  name: miniagent
  llm:
    model_name: target-model
    api_key: your-api-key
    base_url: https://api.example.com/v1
    max_tokens: 4096
  timeout: 300
  max_turns: 10

algorithm:
  name: skillopt
  worker:
    type: agent
    name: claude_code
    llm:
      model_name: worker-model
      api_key: your-worker-api-key
      base_url: https://api.anthropic.com
      effort: high
    timeout: 600
    max_turns: 20
```

Agent 和 Worker 都必须指定 `llm.model_name`。执行时凭据必须在各自配置中明确提供；
Claude Code 也可用 `llm.auth: login` 显式选择本机登录。`llm.base_url` 留空使用对应服务的
官方地址，后端不再隐式读取宿主的模型、凭据或端点环境变量。配置层不检查模型是否可用。

直接在 YAML 中填写各角色的模型连接参数：

```yaml
agent:
  name: miniagent
  llm:
    model_name: your-model
    api_key: your-api-key
    base_url: https://api.example.com/v1
algorithm:
  worker:
    type: llm
    llm:
      model_name: your-worker-model
      api_key: your-worker-api-key
```

将占位字符串替换为实际值。相同配置传给 Agent、Worker 和容器，保存配置时会清空凭据。
直接 Python 调用时，在配置字典中填写相同字段即可。
不同后端保留自己的请求参数语义，例如 MiniAgent 的 `llm.reasoning_effort`
与 Claude Code 的 `llm.effort`。旧的顶层模型字段会报错并提示迁移到 `llm`。
为用于目录命名，算法、Agent 和 Benchmark 的 `name` 使用字母、数字、`_`、`-`。

```python
from flashrsi.config import load_config, prepare_run_dir

config = load_config("example.yaml")
run_dir = prepare_run_dir(config)
print(run_dir)
```

`load_config` 只读取和校验配置。覆盖顺序为默认值 < YAML < `overrides`，
嵌套字典逐项合并，例如：

```python
config = load_config(
    "example.yaml",
    overrides={"algorithm": {"worker": {"llm": {"model_name": "another-model"}}}},
)
```

`run.output_dir` 相对 YAML 所在目录解析；通过 `overrides` 设置时相对当前工作目录。
未传 YAML 时也相对当前工作目录。返回配置中的 `output_dir` 为绝对路径。

创建 Agent 时明确传入它自己的子配置；runner 遵守同一分发约定：

```python
target = MiniAgent(config.agent)
worker = ClaudeCode(config.algorithm.worker)
```

实例在初始化时复制配置。后续通过 `target.config.llm.model_name = "another-model"`
调整默认值；修改原来的 `config.agent` 不会改变已创建的实例。一次 `run` 和整批
`rollout` 各自在开始时复制并固定配置，外部调整只影响之后开始的调用。
适配器在 `_run` 中只读取 `self.config`；此时它指向本次调用的配置副本。
`update(snapshot)` 只选择资源版本，不替换运行配置。比较 baseline 和 candidate 时，
调用方应使用相同模型配置；更换目标模型后需要重新评估 baseline。

`llm` 定义主模型和默认连接。MiniAgent 的辅助模型默认共用它，也可通过
`llm.side_model` 和 `llm.side_base_url` 指定；Claude 自定义子 agent 的模型选择继续遵循原生定义。

## 实验目录

调用 `prepare_run_dir(config)` 会自动在 `run.output_dir` 下创建当前实验目录。
`flashrsi run --prepare-only` 已接入这个函数。

目录名为 `{algo}-{agent_name}-{bench}-{time}`，时间采用本地时间，精确到微秒。
例如：

```text
runs/skillopt-miniagent-searchqa-20260914-163000-123456/
├── config.yaml       # 解析后的配置；嵌套凭据字段置空
├── snapshots/        # 初始版本和候选版本
├── trajectories/     # rollout 与评分结果
└── working/          # checkout、任务执行等临时目录
```

重复调用创建新目录；若时间戳碰撞，则增加一微秒重试，已有实验保持原样。
运行时配置保留传入的凭据。写入磁盘时递归清空以 `API_KEY`、`TOKEN`、`SECRET`、
`PASSWORD` 结尾的字段及 Authorization、Cookie 等凭据字段，同时脱敏其他字段中
重复出现的相同值；嵌套映射和列表也按此处理。
CLI 准备模式下这些子目录仍为空。通过 Python 使用 Snapshot 时可将 `working/`
传给 `Snapshot.check_out()`，并显式保存版本；普通 CLI 运行由 runner 和算法保存版本与记录。

## Benchmark

`Task`、`Trajectory` 和 `Benchmark` 位于 `flashrsi.core`。当前内置的
`SearchQA` 自动下载锁定版本的
[jinjiajie/flashrsi](https://huggingface.co/datasets/jinjiajie/flashrsi) 数据集，
使用其中的 `searchqa` 配置。这是从 EvoOS 整理的 SkillOpt 子集，共 2,000 条，
包含原始 train 400 / dev 200 / test 1,400 条，Parquet 下载量约 3.4 MB。
框架默认 `split: auto`，保留原始 400 / 200 / 1,400 分区；显式设置比例时才合并重划分。
每个 Task 的 `question` 包含原问题、检索上下文和短答案指令；标准答案与别名
单独存放在 `ground_truth` 和 `metadata["answers"]`。

```python
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Trajectory

config = load_config("example.yaml", overrides={"benchmark": {"limit": 20, "seed": 7}})
benchmark = SearchQA(config)
splits = benchmark.load()
print(len(splits["train"]), benchmark.primary_metric)

# 评分接口示例：用标准答案检查评分，不调用模型。
task = benchmark.dev[0]
graded = benchmark.grade((Trajectory(task, "finished", task.ground_truth),))
print(dict(graded[0].metrics))  # {"exact_match": 1.0, "f1": 1.0}
```

`load()` 返回值及其中的任务元组可重复读取，同一实例只加载一次。
调用后也可使用 `benchmark.train`、`.dev`、`.test`；加载前访问会明确报错。
划分使用 `seed` 和任务 ID 的稳定哈希排序，不受源数据遍历顺序影响。
任务数按比例向下取整，余数依次补到小数部分最大的分区，同分时按 train/dev/test
顺序分配。auto 在小数据集上调整取整结果，确保每个分区至少一条；显式比例模式
允许空分区。未设置 limit 时所有任务恰好分配一次。

`grade()` 返回附有 `exact_match`（主指标）和 `f1` 的新 Trajectory 元组，
保留原有消息、用量和其他指标，输入轨迹不变。评分先统一 Unicode、大小写、
标点、英文冠词和空白，再计算 exact match 和 token F1；有多个答案时取最高分。
执行失败或输出为空白的轨迹两项均为 0。只对该实例加载的任务评分，重复任务 ID、
缺失或非法答案及空数据集会明确报错。

开发和离线运行时可设置 `benchmark.data_path`，指向一个 Parquet、JSON 或 JSONL 文件，
或包含 `train`、`dev`/`validation`、`test` 同名数据文件的目录。
JSON 使用对象数组，JSONL 每行一个对象，例如：

```json
{"id": "example-1", "question": "What is the capital of France?", "context": "Paris is the capital of France.", "answers": ["Paris"]}
```

规范字段为 `id`、`question`、`context`、`answers`。本地旧格式仍支持 `key` 和 `answer`；答案可用单个非空字符串或字符串列表。
auto 保留目录内已有的分区，并按上述规则补齐缺失分区。原分区名始终保存在 Task
的 `metadata["source_split"]`，自动划出的任务仍记录其原始来源。
本地路径相对当前工作目录解析；Benchmark 的 `metadata` 记录实际本地路径，
远程加载时记录 Hugging Face 数据集名称与锁定 revision。

`benchmark.limit` 是保留的总任务数上限。auto 先确定分区，再按各分区大小比例抽样，
保持任务分区归属，每区至少一条，因此 limit 至少为 3。显式比例模式仍在划分前
选取总任务池，limit 可为任意正整数。`benchmark.seed` 为整数，默认 0，控制稳定
排序、自动留出和抽样；同一 seed 的 auto 小样本是完整划分的分区内子集。
首次远程加载会下载这 2,000 条子集并使用 Hugging Face 本地缓存；limit 不限制下载量。

`flashrsi.benchmarks.metrics` 提供可复用的 `normalize_answer`、`exact_match`、
`token_f1` 和多参考答案的 `qa_metrics`。通用下载、本地文件读取、重复 ID 检查及
确定性划分位于 `flashrsi.benchmarks._data`；SearchQA 只负责其字段映射、提示词和
评分规则，公共 `load()` / `grade()` 签名保持不变。

当前没有自动注册机制；`flashrsi.benchmarks` 导出 `SearchQA` 和 `TerminalBench` 类。
没有必要的 `SearchQABenchmark` 别名已移除。Benchmark 可单独通过 Python 使用，
runner 根据配置名实例化 Benchmark、目标 Agent、Worker 和 Algorithm。

### 数据集准备与独立使用

仓库保持 private，下载需要有读取权限的本机 Hugging Face 登录或 `HF_TOKEN` 环境变量；
凭据无需写入实验 YAML。框架使用固定的 revision 和 Hugging Face 本地缓存。

可以直接保留 Hugging Face 上发布的原始分区：

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "searchqa")
print({split: len(rows) for split, rows in data.items()})
# {"train": 400, "dev": 200, "test": 1400}
```

数据集各行统一为四列：稳定的 `id`、原始 `question`、原始检索 `context` 和
字符串列表 `answers`。问题、上下文和答案文本均原样保留。数据卡记录上游、原始
评分声明和授权说明；`searchqa/manifest.json` 记录来源版本、数量及文件校验和。

本地可重建发布文件：

```bash
uv run python scripts/prepare_searchqa.py
# 输出到 .cache/searchqa/publish；此命令只下载和处理，不上传。
```

脚本锁定 EvoOS 源版本，验证源文件校验和、跨分区唯一 ID、所有答案、原始提示词
重建和 Parquet 往返一致性；缓存和发布数据不进入 Git。

### Terminal-Bench 数据

同一 Hugging Face 仓库的 `terminal_bench` 配置提供 89 个原生任务的索引：

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "terminal_bench")
print(len(data["tasks"]))  # 89
```

索引列为 `id`、`question`、`task_path`、`task_checksum`、`category`、`difficulty`。
完整任务目录保存在 `terminal_bench/tasks.tar.gz`，`manifest.json` 记录上游版本与校验和。
`TerminalBench.load()` 自动下载固定版本的归档、核对 SHA-256 并安全解包，复用 Harbor
解析原生任务；`load_dataset` 只读取索引。没有官方 train/dev/test 分区，框架默认
`split: auto` 按 60%/20%/20% 划分；`data_path` 仍可指定本地原生任务目录。

```bash
uv run --python 3.12 --extra harbor python scripts/prepare_terminal_bench.py
# 输出到 .cache/terminal_bench/publish；此命令只下载和打包，不上传。
```

数据镜像不包含 Docker 镜像层；89 个任务仍引用 `alexgshaw/<task>:20251031` 镜像。
执行仍需要 Docker、可访问镜像与依赖源的网络，以及有相应工具能力的 Agent。
SearchQA 的已有文件和固定来源版本保持不变。完整运行配置及验证范围见
[Terminal-Bench 说明](docs/terminal-bench.md)。

## Agent：一个运行入口，自动获取文件版本

调用者使用 `agent = MyAgent(config.agent)` 创建目标 Agent。后端只实现一个
`_run`，执行入口是 `await agent.run(prompt, working_dir=None)`——提问、任务执行和
编辑文件走同一条路，始终返回完整的 Trajectory；编辑场景可以忽略最终 output，
但消息和用量仍然保留。
在它之上有两个便利入口，各自只要文本、失败即抛错：`await agent.ask(prompt)` 提问，
`await agent.edit(working_dir, prompt)` 编辑一个目录并返回它对这次编辑的说明。
两者都不提交 Snapshot。算法启动时用 `set_scope` 设置组件的默认可见和编辑权限。
Agent 没有 checkout 接口，也不记录演化历史。

### 当前职责划分

| 概念 | 负责什么 |
| --- | --- |
| Agent | 接入 harness、执行 prompt/Task、应用编辑权限、选择当前版本 |
| Snapshot | 保存完整文件、组件规则和版本来源；导出编辑目录、生成候选、保存与加载 |
| Worker | 算法中的生成或编辑角色，使用同一个 Agent `run` 接口，不要求独立基类 |
| Algorithm | 设置范围，组织候选生成与评估，根据评分决定是否接受候选 |
| Benchmark | 提供 Task，给执行结果评分 |
| Trajectory | 保存一次执行的输出、消息、用量、错误和评分 |

接入者在 harness 目录放置 `components.yaml` 并实现 `_run`，框架管理版本文件与执行上下文。算法只调用公共接口，
不需要知道 harness 使用 SDK 还是子进程。SkillOpt 与 runner 已通过这些接口接入，
下文示例展示相同的候选生成与选择流程。

### 如何接入一个 harness

一个 harness 一个目录。框架根据接入类所在模块定位目录，无需在类里声明
`source_dir` 或 `component_rules`。例如未来的内置 harness 可以采用以下布局：

```text
flashrsi/agents/my_agent/
├── __init__.py       # Agent 接入类
├── components.yaml  # 组件与文件映射
├── runtime/         # 原生运行代码
├── skills/
└── prompts/
```

原生 harness 可以保留自己的目录结构，用 `components.yaml` 指定对应的相对路径：

```yaml
code:
  - runtime/**
skill:
  - skills/**
prompt:
  - prompts/**
```

`__init__.py` 中的接入类主要实现 `_run`：

```python
class MyAgent(Agent):
    name = "my_agent"
    description = "My harness"

    async def _run(self, prompt, working_dir=None):
        # 用 self.files_dir 中的代码和配置调用原有 harness。
        result = await native_run(
            prompt=prompt,
            files_dir=self.files_dir,
            working_dir=working_dir,
            model=self.config["llm"].get("model_name"),
        )
        return Trajectory(
            output=result.text, messages=result.messages, usage=result.usage
        )
```

公开的 `run` 由基类实现，负责准备版本文件、固定本次执行版本与配置及清理文件。接入者实现
`_run`，不用自己处理 Snapshot、提交或版本目录的导出与清理。harness 自己的日志、
任务目录和进程生命周期仍由接入者管理。

| 路径 | 含义 | 使用时机 |
| --- | --- | --- |
| 接入模块所在目录 | 默认的文件来源根目录，包含 `components.yaml` | 初始化时自动定位，与当前工作目录无关 |
| `config.source_dir`（可选） | 覆盖默认根目录，新目录必须包含 `components.yaml` | 使用外部 harness 文件或本地实验副本 |
| `self.files_dir` | 本次执行实际使用的代码和配置目录 | `_run` 内加载代码、prompt、skills 或 SDK 设置 |
| `working_dir` | 任务工作目录或需要编辑的目标目录 | 传给原生 harness 的任务环境 |

运行时必须从 `self.files_dir` 加载可演化文件。开源 harness 可以从这里启动新进程；
闭源 harness 用这里的原生配置和扩展创建 SDK 会话。仅把路径写进 Snapshot，仍从原始
源码包或默认配置加载，会导致修改不生效。接入者必须在返回前等待子进程、SDK 会话及
所有使用该目录的工作结束；基类会在返回、异常或取消时清理文件。

Worker 的 `working_dir` 可以是另一个 Agent 的候选目录。Worker 自身的指令与工具
应从自己的 `files_dir` 加载，不能让目标目录中的配置替代 Worker 配置。具体 SDK
如何关闭隐式项目配置、显式加载扩展，由接入者按该 SDK 支持的接口完成。

构造 Agent 时传入单独的 Agent/Worker 配置映射：目标用 `config.agent`，Worker 用
`config.algorithm.worker`。误传完整实验配置会明确报错，避免 Worker 静默使用目标配置。
`source_dir` 相对路径按当前工作目录
解析，也支持 `~`；覆盖时同时从新目录加载映射，不回退到原目录。未指定来源且接入模块
旁没有 `components.yaml` 时，Agent 为无文件的 Worker，可正常调用 `run/rollout`，但没有
可演化 Snapshot。交互环境中定义的类也可显式传入来源目录。

自动定位使用具体接入类定义所在的模块；子类移到新模块后，需要在新目录提供映射或
显式指定来源。`components.yaml` 必须是“组件名 → 非空路径规则列表”，重复键和非法
路径会报错；`{}` 可以表示空文件版本。根目录的映射文件属于接入元数据，不进入 Snapshot。
规则若覆盖接入类所在文件或继承的 `_run` 实现文件，会在初始化时明确报错；其他接入辅助
代码也应留在规则范围之外。这样候选修改的是实际运行代码和资源。

### Snapshot 如何自动获取

构造时，框架自动定位目录、读取 `components.yaml`，再收集匹配的文件并建立初始 Snapshot。
使用者不需要先构造 Snapshot，接入者也不需要填写 ID、root 或 parent。普通执行只需：

```python
agent = MyAgent(config.agent)
result = await agent.run("回答这个问题")
result = await worker.run("改进这些文件", working_dir=candidate_dir)
```

最终组件规则复制并固定在 Snapshot 中，后续候选继承相同规则；实例上的
`agent.component_rules` 是只读属性，读取当前 Snapshot 的不可变规则。修改原目录中的
映射文件不会改变已有版本。每个文件只属于一个组件，规则不表示本轮允许编辑的范围。
目前已自动定位目录并加载映射；组件名称和路径仍在 YAML 中声明，预定义类别和自动识别
组件语义尚未实现。

`SnapshotFile.executable` 从原文件自动读取，保存脚本能否直接执行，不需要手工填写。
算法的可读、可写、隐藏权限由 `set_scope` 统一决定，不重复存到每个文件条目中。

只收集声明的执行文件，未匹配的文档等文件不进入版本。`.git`、虚拟环境、依赖安装目录、
缓存、真实 `.env` 文件、根目录下的 `logs/`、`runs/` 和日志产物自动跳过；
`.env.example`、`.env.template` 及 `src/logs/` 这类源码资源仍可按规则收集。
选中的符号链接、特殊文件和跨组件冲突会拒绝；目录链接可能包含被选中的文件时也会拒绝。
未声明的文件和目录跳过，不跟随链接。凭据从运行配置传给 SDK/模型，不由框架写入 Snapshot；
后端仍须确保声明的源码和配置内容没有硬编码凭据。

原目录在初始化后变化，不会隐式改变当前版本。每次 `run` 使用独立的版本文件副本，
执行产生的临时修改不会自动提交，也不会影响下一次运行或源目录。`files_dir` 只在运行
内部可访问。每批 `rollout` 固定版本，同时运行的其他候选和 `update` 都不影响该批次；
同一执行上下文内的 `snapshot` 也指向正在执行的版本和编辑权限。

### Trajectory 与 rollout

`_run` 返回 `Trajectory(output=..., messages=..., usage=...)`，无需创建虚构的 Task。
直接 `run` 的轨迹通常 `task=None`；基类 `rollout(tasks, snapshot=None)` 将每个
`Task.question` 传给 `run`，再把完整的原始 Task 关联回轨迹，保留状态、消息、指标、
用量和错误。现有 `Trajectory(task, status, output)` 写法仍有效。

基类在返回的 `messages` 首位加入 `RunConfig`，包含本次执行的脱敏角色配置和
`snapshot_id`（无文件 Worker 为 `None`）。这是传给适配器的配置，不会展开后端默认值、
完整模型请求；原生 messages 仍保留在它之后。返回错误轨迹时也记录
该信息；未处理异常和取消继续向调用者抛出。
普通配置值直接记录为 JSON；日期、二进制、集合等 YAML 特有值记录为
`{"type": "yaml", "value": "..."}`，其中 value 可用 `yaml.safe_load` 恢复。
保存到 `config.yaml` 的对应值仍保留原有 YAML 类型。

`snapshot` 是可选的候选评估参数：

```python
current = await target.rollout(tasks)  # 当前版本
candidate_results = await target.rollout(tasks, snapshot=candidate)  # 试跑候选
# 算法评分并决定接受之后，才调用 target.update(candidate)
```

试跑候选不会改变 `target.snapshot`，多个候选可以并发评估。每批任务固定自己的版本
和编辑权限；接入者的 `_run` 只读取 `self.files_dir`，无需接收 Snapshot 参数。

`rollout` 默认顺序执行，不负责评分，空输入返回空元组。返回的错误轨迹会被保留；
未处理的后端异常向调用者抛出。SearchQA 拒绝没有 Task 的直接运行记录，评分请使用
`rollout` 的结果。带 `Task.env` 的任务交给绑定的环境执行器；未绑定时会在任何任务
开始前明确报错。CLI runner 为 Terminal-Bench 自动绑定 Harbor；直接 Python 调用须先
执行 `flashrsi.integrations.harbor.bind(agent)`。环境执行器解释环境引用、准备容器，
再调用所选 Agent 原有的 `run`；Agent 不需要按 benchmark 实现执行钩子。

### 算法如何编辑和选择候选

算法启动时设置一次默认范围，再通过 `agent.snapshot` 获取当前版本：

```python
target.set_scope({"skill": "rw", "prompt": "r", "code": "none"})
```

这里有两张用途不同的映射：`component_rules` 是从 `components.yaml` 加载的
“组件 → 文件路径规则”，随快照保存；`set_scope` 接收“组件 → 权限”，由算法设置，
只影响运行期的编辑范围。

| 权限 | 编辑目录中的行为 |
| --- | --- |
| `rw` | 可见，可新增、修改、删除 |
| `r` | 可见、只读 |
| `none` | 隐藏，不允许改动 |

调用 `set_scope` 后，未列出的组件默认隐藏；重复调用整体替换默认范围。
未设置 scope 时所有组件可读写，`set_scope({})` 则隐藏全部组件。未知组件或权限立即报错。
范围仅控制交给演化 Worker 的编辑目录；目标 Agent 执行任务仍使用完整代码和配置。
文件操作直接使用 Snapshot：

- `snapshot.check_out(working_dir=...)`：在指定父目录下创建临时子目录并按范围导出，只读文件带只读标志，退出上下文清理。省略参数时使用系统临时目录。
- `baseline.commit(directory)`：自动检查归类与权限，保留未导出的隐藏文件，生成完整候选。
- `snapshot.save(path)` / `Snapshot.load(path)`：将完整文件、组件规则和版本信息保存为 JSON，或从中恢复。

`baseline` 只是修改前的 Snapshot。`commit` 不改变它，也不自动接受候选；新版本的
`parent_id` 指向它。`commit` 自动检查内容、删除、新增、重命名和可执行标志的改动，
只读文件即使被 Worker 改过权限后写入也不能提交。主动创建隐藏组件的路径也会被拒绝。
算法无需调用 `validate`；这个公共接口已移除。

Snapshot 构造和加载时校验文件标签与固定规则一致，规则也参与版本哈希。
`rollout(snapshot=...)` 和 `update` 自动检查版本兼容性及 Agent 当前权限，不能用
旧的宽权限快照或加载的候选绕过范围。历史版本或兄弟候选也可以使用，但相对当前版本的
差异必须符合权限。只有 `update` 会选择未来调用使用的版本。

权限是 Agent 绑定给 Snapshot 的临时编辑视图，不参与版本 ID、相等比较或 JSON 保存。
快照中的完整文件和历史信息保持不变。已获取的快照与正在执行的批次保持原来的权限视图，
`set_scope` 影响后续获取和调用。`load` 只恢复版本；传回 Agent 后重新使用该 Agent 的权限。
隐藏表示不导出到编辑目录，`Snapshot.files` 仍包含完整版本；此机制不提供进程级文件访问隔离。

路径规则从文件树根目录匹配，`*` 只匹配当前路径段，完整的 `**` 段匹配多层目录。
候选继承固定规则，因此已有路径保留标签，新文件也能自动归类；删除检查原组件；
重命名按删除加新增处理。
与自动收集不同，`commit` 和手动 `Snapshot.from_directory` 校验完整输入文件树，
不会静默忽略未分类文件或运行产物。保存文件保留 bytes、组件和可执行标记，使用
SHA-256 校验，`root_id/parent_id` 只记录在 Snapshot。保存不覆盖已有目标。
JSON 格式为 v2，包含 `component_rules`；旧 v1 文件没有分类规则，需要从来源目录
重新创建快照，加载时会明确提示。`load` 恢复文件版本，不恢复进程、SDK 会话或 Agent。

### 最小离线示例

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi.core import Agent, Task, Trajectory


class ExampleAgent(Agent):
    name = "example"
    description = "Offline example"

    async def _run(self, prompt, working_dir=None):
        answer = (self.files_dir / "skills/main.md").read_text(encoding="utf-8")
        return Trajectory(output=answer)


class Editor(Agent):
    name = "editor"

    async def _run(self, prompt, working_dir=None):
        (working_dir / "skills/main.md").write_text(prompt, encoding="utf-8")
        return Trajectory(output="已修改", usage={"example_calls": 1})


with TemporaryDirectory() as temporary:
    source = Path(temporary) / "files"
    (source / "skills").mkdir(parents=True)
    (source / "skills/main.md").write_text("initial answer", encoding="utf-8")
    (source / "components.yaml").write_text("skill: ['skills/**']\n", encoding="utf-8")
    target = ExampleAgent({"source_dir": source})
    target.set_scope({"skill": "rw"})
    tasks = (Task("capital", "capital?", ground_truth="Paris"),)

    # 这个离线示例用精确匹配评分；正式算法调用 benchmark.grade。
    def score(trajectories):
        return sum(item.output == item.task.ground_truth for item in trajectories)

    current_results = asyncio.run(target.rollout(tasks))

    baseline = target.snapshot
    with baseline.check_out() as directory:
        edited = asyncio.run(Editor().run("Paris", working_dir=directory))
        candidate = baseline.commit(directory)
    candidate_results = asyncio.run(target.rollout(tasks, snapshot=candidate))
    assert candidate_results[0].output == "Paris"
    assert target.snapshot is baseline
    if score(candidate_results) > score(current_results):
        target.update(candidate)
    assert asyncio.run(target.run("capital?")).output == "Paris"
```

[examples/agents/native_adapters.py](examples/agents/native_adapters.py) 使用两个独立的示例
harness 目录：[open_harness](examples/agents/open_harness/__init__.py) 和
[closed_harness](examples/agents/closed_harness/__init__.py)。它们都从自己的模块目录自动
加载 `components.yaml`，无需传入来源路径。开源后端实际启动候选 Python 源码，闭源后端
通过注入的假 SDK 显式传入原生指令和 skills，展示与编辑目标目录的区别。可直接执行：

```bash
uv run python examples/agents/native_adapters.py
```

Agent 基类阶段验证包括真实本地子进程、假 SDK、并发/取消和 SearchQA 本地评分闭环，未调用
真实模型或 Claude SDK。SkillOpt 已沿用这些接口接入，CLI 同时支持执行和准备模式。
`mvp_doc.md` 中旧签名尚未同步，仍由开发者维护；
这里记录本轮明确确认并实现的接口。

## MiniAgent

第 4 步接入 MiniAgent，可直接通过 Python 使用既有的 `run`、`rollout`、
候选评估和 `update` 接口。安装可选依赖：

```bash
uv sync --extra dev --extra miniagent
uv run --extra miniagent pytest
```

也可安装 `flashrsi-lite[miniagent]`。不安装这一 extra 仍可使用配置、Benchmark、
Snapshot 和其他 Agent；MiniAgent 的依赖在运行时由原生 runtime 导入。

接入代码调用原生 `run(question, model=..., max_turns=..., workspace_dir=..., runs_root=...)`，
使用其中的 `answer`、`stop_reason`、`usage` 和 `turns` 构造 Trajectory；返回值有 `messages`
时一并保留，没有则留空。编辑任务额外传入 `working_dir`。
`components.yaml` 声明版本文件，`_entry.py` 在子进程加载当前版本并返回原生结果；
runtime 不依赖框架类，日志格式由 harness 自己决定。
接入层直接使用传入的配置和原生结果，不重复校验字段类型或预检依赖、资源文件。

新增 Agent 先看 [最小接入指南](docs/agent-integration.md)：声明组件、实现 `_run`，
优先调用原生入口。下文的 MiniAgent 原生改动还包含能力增强，不是所有接入都需要做的步骤。

```python
import asyncio

from flashrsi.agents import MiniAgent
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config

config = load_config("example.yaml", overrides={"benchmark": {"limit": 3}})
agent = MiniAgent(config.agent)
benchmark = SearchQA(config)
benchmark.load()
graded = benchmark.grade(asyncio.run(agent.rollout(benchmark.dev)))
print(graded[0].output, dict(graded[0].metrics))

# 同一入口也可提问，或给 Worker 一个待编辑的目录。
answer = asyncio.run(agent.run("What is 2 + 2?"))
# edited = asyncio.run(worker.run("Improve the skill files", working_dir=directory))
```

默认 `agent.yaml` 加载 prompt、`skills/main.md` 和 `shell` 工具，不调用搜索服务。
`shell` 使用 `/bin/sh -c` 在任务目录执行命令，接受 `command`、可选 `cwd` 和
`timeout`（默认 60 秒），返回退出码、合并的 stdout/stderr、超时与截断标志；
输出最多保留 32 KiB。每次调用使用独立 shell，`cd` 和环境变量不跨调用保留，
正常结束的命令可以留下后台服务；服务的 stdout/stderr 应重定向到日志文件，
因为命令退出后工具会关闭输出收集。超时或取消会清理当前命令的进程组。
后台服务的生命周期由任务环境或调用者管理：Harbor 在 verifier 完成后随容器清理，
本地调用者负责停止自己启动的服务。实现和 schema 属于 Snapshot 的 `tool` 组件，
可通过版本中的 `agent.yaml.tools` 启用或关闭。

传入 `working_dir` 时还增加 `list_files`、`read_file`、`write_file`、
`delete_file` 四个文件工具，路径相对该目录；加载的 prompt、skill 和工具配置仍属于
Worker 自己。文件工具不允许路径逃逸或符号链接，提交候选时继续由 Snapshot 校验 scope。
新增 skill 文件后也需要在候选的 `agent.yaml.skills` 中启用；仅可编辑 skill 时，
可以修改已启用的 `skills/main.md`。

MiniAgent 的资源布局和 Snapshot 组件如下：

| 组件 | 文件 |
| --- | --- |
| `code` | `runtime/**`、`middleware/**`、`sub_agents/**` |
| `skill` | `skills/**` |
| `prompt` | `prompts/**` |
| `tool` | `tools/**`、`tool_descriptions/**` |
| `config` | `agent.yaml` |

每次运行在独立 Python 子进程中导入当前 Snapshot 的 `runtime/`，不依赖旧 FlashRSI
仓库。MiniAgent 接入类和进程桥接代码留在 Snapshot 外。临时日志与任务目录分别创建，
运行结束后清理；传入的编辑目录保留给调用者。超时或进程崩溃返回错误 Trajectory，
不从日志恢复部分轨迹；已经完成的文件编辑仍会保留。取消向上传播；
超时和取消先取消原生执行，让 shell 清理仍在执行的命令进程组，再结束并等待子进程；
超过两秒清理期限后强制终止。已经完成的命令留下的后台服务由任务环境管理。
本地子进程本身不提供容器或操作系统沙箱。绑定 Harbor 后，MiniAgent 可使用同一入口在
任务容器内执行 shell。shell 使用运行进程的系统权限，`cwd` 只是起始目录，
不采用上述文件工具的目录限制；Snapshot scope 仍用于校验提交的版本修改。

| 配置字段 | 默认值 | 含义 |
| --- | --- | --- |
| `llm.model_name` | 必填 | OpenAI 或兼容端点上的模型名 |
| `llm.api_key` | 执行时必填 | 在配置中填写 API key |
| `llm.base_url` | OpenAI 官方地址 | 可覆盖为兼容端点，不读取环境回退 |
| `max_turns` | `10` | 原生循环轮数，最后一轮请求直接回答 |
| `llm.max_tokens` | `4096` | 原生主循环和强制回答的输出预算；辅助调用沿用原生各自预算 |
| `llm.llm_max_retries` | `1` | 原生每次调用的最大尝试次数 |
| `llm.reasoning_effort` | 未设置 | 显式设置时原样传给模型 API |
| `llm.extra_body` | `{}` | 原样传给模型 API 的额外请求字段，主调用和辅助调用均生效 |
| `timeout` | `300` | 整次运行超时，单位秒 |
| `source_dir` | 内置目录 | 可选完整来源目录，须带 `components.yaml` 和实际 runtime/资源 |

所有模型通过 OpenAI SDK 调用 OpenAI 或兼容端点。主循环中 GPT/o 系列使用 Responses，
其余模型使用 Chat Completions；辅助文本调用使用 Chat Completions。模型名保留原值，
包括 `org/model`，仅兼容去除已有的 `openai/` 前缀。
模型的推理或其他专有选项由 `llm.reasoning_effort` 和 `llm.extra_body` 显式配置，
不根据模型名推断或自动启用。

适配类把 `llm`、`web` 和 `debug_llm_io` 直接作为参数通过 stdin JSON 传给原生 `run`。
运行时不读取 `FLASHRSI_MINIAGENT_*`、`FLASHRSI_SEARCH_URL` 等环境变量。
主调用和辅助调用默认共用 `llm`；`llm.side_model`、`llm.side_base_url` 可显式覆盖辅助调用。
网页工具使用角色配置 `web.search_url`、`web.browse_url`、`web.api_key`；默认未启用，
服务地址须显式提供。`debug_llm_io: true` 启用本轮原生请求调试日志。

题目、资源目录、模型配置与凭据一起通过 stdin 传递，父进程环境不变。
凭据不写入源码、Snapshot、命令行参数或请求文件，返回记录和内置 harness 日志会脱敏。
`Trajectory.messages` 在 `RunConfig` 后保存原生对话列表，`usage.model_calls` 保存原生记录的
用量、模型、轮次和耗时，`usage.turns` 保存循环轮数。统计范围沿用原生主循环、辅助调用和
强制回答，网页提取用量没有额外补齐；不再额外保存完整 provider 响应。API 错误保留已有对话和用量，
不会把失败当成成功答案。

`runtime/` 基于旧 FlashRSI 的 `miniagent/harness/`（来源提交
`5efe9b438483710060183c6c3ecbc5062b410a58`）移植，保留原生 ReAct、middleware、
自定义工具、Chat/Responses 连续调用；模型和工具配置改为显式函数参数。保留的小改动单独列在
[harness 改动清单](docs/agent-integration.md#harness-的小改动) 和
[原生差异文件](docs/miniagent-harness.patch)，原生函数接收普通字典，不依赖框架 Config 类或运行时 monkey patch。
未搬入旧框架的 registry、演化算法、ArtifactStore 或评测脚本。
默认资源来自旧版的文本 seed。Web 工具代码保留，但默认关闭，需要自行添加原生 schema
及配置搜索/浏览服务；本阶段不验证真实 Web 服务。

本阶段集成测试使用真实本地子进程、真实 OpenAI SDK 和本地模拟 HTTP 服务，验证两种
协议、skill/code 候选、文件编辑、SearchQA 离线评分、并发、取消和错误处理。
CLI 可通过 SkillOpt/runner 执行完整演化；`--prepare-only` 保留准备模式。

### Atria 真实模型验证

[examples/miniagent_atria.py](examples/miniagent_atria.py) 使用现有适配层，连接
`https://api.atria-asi.ai/v1` 上的 `Atria-Dawn-Preview`，无需新增 provider：

```bash
uv run --extra miniagent python examples/miniagent_atria.py
```

脚本读取 `ATRIA_API_KEY`；未设置时通过不回显的提示输入。它会实际调用模型，依次验证
问答、使用文件工具修改 skill、候选 Snapshot 生效，以及候选评估后基线保持原样。
配置、基线与候选 Snapshot、完整 Trajectory 保存在独立的 `runs/smoke-miniagent-local-*`
目录，配置中的密钥置空。2026-09-16 已通过上述真实调用验证。
同日使用 `benchmark.limit=30`、`seed=0`、`split=auto` 得到 3 条 dev 样本，
真实执行 `rollout` 后由 SearchQA 评分，3 条均完成，平均 EM/F1 均为 1.0；这是接入验证，
不代表完整数据集的模型表现。

当前调用使用非流式 Chat Completions，Atria 已验证支持；不要通过 `llm.extra_body`
设置 `stream: true`，原生循环需要完整响应对象。

## Claude Code

第 5 步通过官方 `claude-agent-sdk` 接入，沿用 `run`、`rollout`、候选评估和 `update`。
安装 SDK 可选依赖（包含原生 Claude CLI），无需依赖旧 FlashRSI 或系统 `claude`：

```bash
uv sync --extra dev --extra miniagent --extra claude-code
uv run --extra claude-code python examples/claude_code.py --model YOUR_MODEL
```

第二条命令会真实调用模型，验证问答、编辑 MiniAgent skill、Claude skill 候选生效、
基线保持原样以及 `update`。演示脚本在候选中添加并显式调用测试用 skill；默认 Agent
不包含该 skill。配置、Snapshot 和 Trajectory 保存到独立实验目录。
也可安装 `flashrsi-lite[claude-code]`。不安装此 extra 仍可导入和使用其他 Agent，
Claude SDK 只在 `ClaudeCode.run` 时导入。SDK 依赖范围为 `>=0.2.153,<0.3`，
当前锁定 0.2.153。

```python
import asyncio

from flashrsi.agents import ClaudeCode
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config

config = load_config(
    "example.yaml",
    overrides={
        "agent": {"name": "claude_code", "llm": {"model_name": "your-claude-model"}},
        "benchmark": {"limit": 30},
    },
)
agent = ClaudeCode(config.agent)
benchmark = SearchQA(config)
benchmark.load()
graded = benchmark.grade(asyncio.run(agent.rollout(benchmark.dev)))

# 作为 Worker 时传入 algorithm.worker 配置，仍调用同一 run 接口。
# worker = ClaudeCode(config.algorithm.worker)
# edited = await worker.run("Improve the skill files", working_dir=directory)
```

闭源 harness 只保存 SDK 能显式加载的资源：

| 组件 | 文件 | 原生加载方式 |
| --- | --- | --- |
| `prompt` | 可选 `CLAUDE.md`、`output-styles/**` | `CLAUDE.md` 内容经 SDK `system_prompt.append` 显式追加；输出样式按插件加载 |
| `skill` | `skills/**`、`commands/**` | 原生 skills 和命令，可包含支持资源 |
| `agent` | `agents/**` | 原生自定义 subagent 定义 |
| `hook` | `hooks/**` | `hooks/hooks.json` 及其调用的脚本 |
| `tool` | `.mcp.json`、`.lsp.json`、`servers/**` | MCP/LSP 声明及本地服务代码 |
| `config` | `.claude-plugin/plugin.json`、`settings.json` | 插件声明和显式加载的原生 settings |

默认使用 SDK 的原生 `claude_code` system prompt，不附加 `CLAUDE.md`、skill 或指定
解题流程。插件清单用于加载版本化扩展，默认 settings、hooks 和 MCP 声明为空，
不附加自定义 agent 或服务。需要 skill 时，按 Claude Code 原生目录和 frontmatter 格式
新增文件，随插件自动发现；不需要修改框架。这里采用原生插件布局
`skills/<name>/SKILL.md`，对应 `flashrsi:<name>`；普通项目则使用
`.claude/skills/<name>/SKILL.md`。演化示例只在候选中创建测试技能，默认资源不包含它。
组件规则允许候选新增对应文件。SDK、CLI、接入代码和运行产物不进入 Snapshot。
`code` 组件不存在，对它设置 scope 会立即报错；本地工具和 hook 源码
分别属于 `tool` 和 `hook`。

例如只演化自定义 agent 和工具，可以设置 `agent.set_scope({"agent": "rw", "tool": "rw"})`。
新增 `agents/reviewer.md` 使用原生 frontmatter（如 `name`、`description`、`tools`）和正文，
模型通过原生 Agent 工具调用它。`settings.json` 支持原生设置，例如 `outputStyle`；
模型、连接信息和配置中显式传入的 SDK 选项继续作为本次运行参数。
`settings.json.env` 不允许设置凭据（名称以 `API_KEY`、`TOKEN`、`SECRET`、`PASSWORD`
结尾）、`ANTHROPIC_BASE_URL`、provider 切换以及接入层管理的目录和持久化开关；
模型与认证通过运行 config 传入，目录和持久化开关由适配器管理。普通工具环境变量仍随 settings 版本生效。

插件输出样式在 `output-styles/*.md` 的 frontmatter 中设置 `force-for-plugin: true`，
可再加 `keep-coding-instructions: true` 保留原生编码指令。当前 bundled CLI 2.1.273
已验证这种加载方式；仅在 settings 中选择插件 `outputStyle` 时，CLI 虽报告选中，
正文未进入模型请求，因此不要依赖这种方式。

hook 命令引用 `"${CLAUDE_PLUGIN_ROOT}/hooks/check.py"`，MCP 的 `args` 引用
`${CLAUDE_PLUGIN_ROOT}/servers/server.py`。每次执行将 `CLAUDE_PLUGIN_ROOT` 设为当前
版本目录，由 CLI 原生展开；脚本解释器及服务依赖仍需在运行环境安装。
凭据通过运行 config 提供，由适配器传给 CLI，不能硬编码在这些版本文件里。`.lsp.json` 沿用原生插件加载，
LSP 进程和语言环境需自行准备；本轮未做真实 LSP 服务验证。

每次运行创建新的 SDK 会话：`self.files_dir` 提供 prompt 和插件，`working_dir`
作为工具工作的 cwd；不传后者时使用独立临时目录。显式设置 `setting_sources=[]`
关闭用户及目标目录的配置和 `CLAUDE.md` 自动加载，`strict_mcp_config=True` 关闭
隐式 MCP 配置，再显式传入当前版本的 `.mcp.json` 和 `settings.json`。
`CLAUDE.md` 可以不存在或为空；候选提供非空内容时，通过 SDK 的 `system_prompt.append` 追加；
这不会启用日常 CLI 的目录发现和分层加载规则。
Worker 编辑另一个 Agent 时仍使用自己的指令、扩展和工具配置。
运行时显式关闭 auto memory，避免同一工作目录的历史记忆影响候选评估。
`CLAUDE_CONFIG_DIR` 和 `CLAUDE_CODE_TMPDIR` 指向每次调用独立的临时目录，
会话 transcript 和子任务输出在 SDK 退出后清理，不进入 Snapshot。
`llm.auth: login` 时 `CLAUDE_SECURESTORAGE_CONFIG_DIR` 沿用原生凭据位置
（包括默认 macOS Keychain）；显式 API 凭据模式使用本轮独立目录，不回退到宿主登录。
这属于配置选择，不是操作系统文件隔离；原生工具仍可读取任务要求访问的文件。

| 配置字段 | 默认值 | 含义 |
| --- | --- | --- |
| `llm.model_name` | 必填 | 原样传给 Claude SDK 的模型名 |
| `llm.api_key` | 空 | 显式传给原生 CLI；与 `llm.auth_token`、`llm.oauth_token` 三选一 |
| `llm.auth` | `api_key` | 默认使用显式凭据；`login` 显式选择本机原生登录，容器不支持 |
| `llm.base_url` | Anthropic 官方地址 | 显式传给原生 CLI，不读取宿主端点回退 |
| `max_turns` | `10` | 原生会话轮数上限 |
| `max_budget_usd` | 未设置 | 原生单次调用费用上限 |
| `timeout` | `300` | 执行超时秒数；退出前仍等待 SDK 清理 |
| `completion_grace` | `0.5` | 已知子任务及其回复结束后，等待尾随 SDK 事件的静默窗口，单位秒 |
| `permission_mode` | `acceptEdits` | 原生工具权限模式，默认允许文件编辑 |
| `allowed_tools` | `[Read, Glob, Grep]` | 原生自动允许列表，SDK 的 `skills="all"` 另启用 Skill；按需要显式授权 Bash 等工具 |
| `tools` | 未设置 | 原生可用工具集合；`[]` 禁用内置工具 |
| `llm.effort` | 未设置 | 原样传给 SDK 的推理选项 |
| `cli_path` | 未设置 | 可选 CLI 路径；默认使用 SDK 自带版本，相对路径按当前工作目录解析 |
| `source_dir` | 内置目录 | 可选资源目录，需包含 `components.yaml`；扩展文件按需提供 |

此后端使用 Claude 原生协议，`llm.base_url` 应指向 Anthropic 兼容端点；
MiniAgent 的 OpenAI 兼容端点不能直接当作 Claude 端点使用。
当前适配器支持 Anthropic 兼容 API 和显式本机登录；宿主的云 provider 路由开关不会生效。凭据仅经 SDK 的子进程
环境传入，父进程环境不变，返回记录会脱敏。CLI stderr 经脱敏后写入 Python debug 日志。
错误 Trajectory 另附最多 8192 字符的 stderr 尾部，保留扩展解析与启动诊断。
会话保留本次运行内的原生 transcript，并清空继承的 `CLAUDE_CODE_SKIP_PROMPT_HISTORY`，
使 `SendMessage` 可以继续已完成的子 agent。原生 CLI 的其他缓存和诊断行为仍由其管理。

### 消息和多 agent

一次 `run` 返回一个 Trajectory，包含本次调用内部的主 agent 和 subagents。
`messages` 首位为基类记录的 `RunConfig`，随后是按 SDK 到达顺序保存的事件列表。
其中 `RunInput` 保存原始 prompt、
传给 SDK 的 system prompt 配置及 Snapshot ID。随后保留 SDK 消息及内容块的 dataclass
字段，以类名标注 `type`，包括工具调用/结果、任务事件、hook 事件和各轮 ResultMessage。
`forward_subagent_text=True` 开启子 agent 文本转发；SDK 暴露的其他内容块也原样转换。
这是 SDK 可见的记录，不保证恢复 CLI 内部未暴露的信息或完整原始请求。
`RunInput.system_prompt` 是 preset/append 配置，并非展开后的模型 system prompt；
`UserMessage` 也可能是工具结果或子任务输入。此事件列表不能直接作为模型会话重放，
也没有开启 token delta 记录。

无需新增嵌套 Trajectory 类型：子消息的 `parent_tool_use_id` 指向创建它的 Agent
工具调用；任务事件的 `task_id` 和 `tool_use_id` 关联进度与结束状态。一个流中多个
子 agent 的消息可以交错，父子关系通过这些 ID 保留，不靠消息相邻顺序猜测。

```python
result = await agent.run("Delegate two evidence checks and summarize the results")
child_events = [m for m in result.messages if m.get("parent_tool_use_id")]
task_events = [m for m in result.messages if m.get("task_id")]
```

接入层持续读取消息，等待已知有限子任务（`local_agent`、`local_workflow`）终止，
并收集后台完成通知触发的主 agent 回复。`TaskNotificationMessage` 和终止状态的
`TaskUpdatedMessage` 都能结束任务，输出取最终成功 Result 的答案。
常驻后台 shell、远程监控和长期 teammate 不作为这次有限执行的等待条件。
SDK 当前没有明确的“整个 run 已结束”事件，因此已知任务与通知处理结束后还会等待
`completion_grace` 静默窗口收集尾随事件；这不构成任意长期 agent team 的生命周期管理。
仍有未完成任务或回复时，`timeout` 到期返回错误并保留已收到的轨迹。
子 agent transcript 由原生 CLI 异步落盘：极快的模型在落盘前续接时仍可能遇到
`No transcript found`。接入层已允许持久化；本轮续接验证等待实际文件发布，
不宣称修复了 CLI 内部的这一时序问题。

`usage` 将各轮 Result 的 token 统计、`num_turns`、`duration_ms` 累加；
`model_usage`、`total_cost_usd`、`duration_api_ms` 是原生会话累计值，取最新结果，
不再与子消息的统计重复累加。主轮次 token 统计和包含子 agent 的按模型总量可能不同；
每轮原始 Result 和任务自身的用量仍留在 `messages`，便于核对。
`duration_ms` 是各轮执行耗时之和，不包含所有后台等待时间，不能当作完整墙钟耗时。
错误结果（包括 `subtype=success` 但 `is_error=True`）、SDK 执行错误、缺少结果和超时
均返回错误 Trajectory，保留已收到的消息和结果用量。原生 init 的插件加载错误、
MCP `failed` / `needs-auth` 也会终止运行；主动 `disabled` 的 MCP 不视为加载失败。
settings JSON 损坏或覆盖运行时保留字段，在调用模型前返回错误；`CLAUDE.md` 可省略。
`tool_deferred`、`aborted_streaming`、`aborted_tools` 不能报告为完成；当前没有暂停后恢复接口，
这些结果返回错误并保留原始待执行工具信息。
取消向上传播；执行期限不打断 SDK 的退出清理，SDK 会话先关闭，
再清理临时任务目录和版本目录。没有独立会话复用或恢复逻辑。

本步离线验证使用真实 SDK、SDK 自带 Claude CLI 和本地 Anthropic SSE 模拟服务，
覆盖 SearchQA 评分、原生 Skill 加载候选、原生 Read/Write 编辑 MiniAgent、hooks/settings、
MCP、commands/输出样式、前台与后台 subagents、子 agent 续接、历史 memory 隔离、
原生认证目录及扩展加载失败，以及冲突的目标配置不会替换 Worker 配置；
另用 CLI 协议替身验证超时、取消、失败、任务结束顺序和并发。
2026-09-17 的真实模型 smoke 已验证基础回答、Worker 文件编辑、baseline 隔离、
update 生效、后台双子 agent 消息收集及 SendMessage 上下文续接；candidate rollout
仍有超时，部分输出未通过严格格式断言，代理也出现模型路由失败。本次配置结构迁移
采用离线协议与本地服务回归，没有重新调用付费模型。
CLI 已支持 SkillOpt 演化与最终测试；Terminal-Bench 的接入及验证状态见
[Terminal-Bench 说明](docs/terminal-bench.md)。

### 协作者提交实验

参见 [统一实验提交规范](experiments/README.md)。运行目录仍写入被 Git 忽略的 `runs/`；
使用 `scripts/prepare_experiment_submission.py` 导出统一的 `experiments/<run-id>/`，
配置与汇总直接进 Git，完整日志压缩包使用 Git LFS。
