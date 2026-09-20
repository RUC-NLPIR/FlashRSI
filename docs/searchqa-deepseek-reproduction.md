# SkillOpt × SearchQA × DeepSeek 双 harness 实验

本实验使用 `deepseek-v4-flash` 答题，`deepseek-v4-pro` 演化技能，分别在 MiniAgent
和 Claude Code 上运行 FlashRSI-Lite 的 SkillOpt。本文所说 worker 是答题模型；Lite
配置的 `algorithm.worker` 实际是 evolver，二者不要填反。

2026-09-19 本次执行目录为 `runs/skillopt-searchqa-deepseek`。两种 harness 的真实 smoke
均已完成；794 项离线/本机测试通过，后续并发、恢复与验收模块另有专项测试。
完整实验使用 protocol runner。后续复现请选择新的运行目录；同一代码和配置下可用同命令恢复：

```bash
.venv/bin/python scripts/run_searchqa_protocol_experiment.py \
  --profile full --run-root runs/skillopt-searchqa-deepseek-reproduction --execute
```

两侧已于 2026-09-20 完成，最终完整性与评分验收均通过。历史输出保存于 `runs/skillopt-searchqa-deepseek/full/logs/full-v2-protocol-<harness>.log`，
启动进程信息为 `full/evidence/` 下的 `full-process-<harness>.json`；实际完成情况以两个 harness 的
`result.json` 为准。原串行日志仍保留。
Smoke 中两侧候选均因 dev 打平被拒，不能声称有技能提升。

全量最终测试结果（每侧初始与最终各 1,400 题，4 epochs / 40 fast steps）：

| Harness | 初始 test EM | 最终 test EM | EM 提升 | test F1（前→后） | 配对 95% 区间（百分点） |
| --- | ---: | ---: | ---: | --- | --- |
| MiniAgent | 76.43% | 82.93% | +6.50 | 86.75% → 89.82% | +4.93～+8.14 |
| Claude Code | 74.71% | 83.14% | +8.43 | 85.25% → 90.25% | +6.64～+10.21 |

两侧最终技能均发生变化，分别接受 7 / 5 个候选。报告与逐角色服务用量见
`runs/skillopt-searchqa-deepseek/full/report.md`；独立重算验收见
`runs/skillopt-searchqa-deepseek/full/evidence/full-verification.json`，两侧均为 `passed`。
验收覆盖完整固定测试集、官方评分重算、4 个 epoch 的训练覆盖、3 次 slow/meta
更新记录、严格 dev gate、最终技能哈希及配对区间。临时失败尝试保留于缓存错误记录，
不能将最终有效轨迹无错误理解为运行中从未发生服务故障。

期间网关额度耗尽导致停机；用户确认充值后按原配置继续，17,074 份恢复前缓存均校验
不变，证据在 `runs/skillopt-searchqa-deepseek/full/evidence/quota-resume-20260920T012205Z/`。
这些是 DeepSeek 迁移实验结果：Claude Code 的最终 EM 比论文 GPT-5.5 同 harness
85.9% 低约 2.76 个百分点，不能称为官方原模型数值复现。

这是**迁移复现实验**。论文没有 DeepSeek 或 MiniAgent 的对应结果；只有完整测试完成后，
才能判断本设置与论文的距离。模型名由网关提供，不代表本地验证过底层权重版本。

## 入口与凭据

在 FlashRSI-Lite 目录执行。已有 `.venv` 中的 Python 3.12、OpenAI SDK、Claude Agent
SDK 与数据依赖可以直接复用。两份可审查配置为
[`miniagent.yaml`](../examples/searchqa_deepseek/miniagent.yaml) 和
[`claude_code.yaml`](../examples/searchqa_deepseek/claude_code.yaml)。

本地 `.env` 保存 `FLASHRSI_BASE_URL` 和 `FLASHRSI_API_KEY`，权限为 0600，已被 Git
忽略。脚本在内存中向两侧分别注入凭据，保存的配置和轨迹会脱敏。环境变量优先于文件。
不要把真实 key 放进 YAML、命令行参数、技能或版本库。

网关需同时支持 OpenAI Chat Completions 和 Anthropic Messages。
MiniAgent 与 evolver 使用 `/v1` 基地址，Claude Code 使用移除末尾 `/v1` 后的根地址。
此接口组合已做真实模型最小请求检查；单请求成功不等于完整 harness 或实验成功。

先生成计划，不调用模型：

```bash
.venv/bin/python scripts/run_searchqa_experiment.py --profile smoke
```

运行两种 harness 的小样本演化闭环：

```bash
.venv/bin/python scripts/run_searchqa_experiment.py --profile smoke --execute
```

闭环通过后运行全量：

```bash
.venv/bin/python scripts/run_searchqa_experiment.py --profile full --execute
```

脚本默认串行运行两种 harness，每种内部并发 4。可用 `--harness miniagent` 或
`--harness claude_code` 单独运行，也可用 `--concurrency 2` 降低并发。
`--run-root` 选择独立实验系列目录。默认目录为 `runs/skillopt-searchqa-deepseek`。

| profile | train / dev / test | 演化预算 | 用途 |
| --- | --- | --- | --- |
| smoke | 4 / 4 / 8 | 1 epoch，最多 1 step | 检查两条原生链路、反思与候选评估 |
| pilot | 40 / 40 / 100 | 1 epoch，最多 1 step | 可选的小规模诊断，不当作论文结果 |
| full | 400 / 200 / 1400 | 4 epochs，40 个 fast steps | 全量迁移复现 |

全量每个 harness 约有 1,600 次训练题执行、最多 8,000 次 fast candidate dev 执行，
另有初始 dev、slow update 和初始/最终共 2,800 次 test 执行，以及 evolver 调用。
实际数量依赖空编辑、候选和 slow update；并发不是费用上限。程序不通过 test 调参。

## 数据、选择与统计

数据来自本地 `.cache/searchqa/publish/searchqa`，每个 parquet 的 SHA256 必须匹配
准备时的 manifest。原始 2,000 题来自 SkillOpt 的固定划分；smoke/pilot 仅在各 split
内部按 seed 42 抽样，两个 harness 使用相同题目。若本地数据缺失，先执行
`scripts/prepare_searchqa.py`；来源和校验细节见脚本与数据卡。

官方数据对照证据：2,000 个 ID 的 split 与官方一致，question/context/answers 与锁定的
`lucadiliello/searchqa` 原数据一致。本子集最大 context 长度 4,820，小于官方 6,000
字符截断阈值。

实验专用 benchmark 使用官方 `hard` 作为演化主指标：最后一个 `<answer>` 标签内的
文本，无标签时最后一个非空行，再用官方 ASCII 标点/SQuAD normalization 做 exact
match。`f1` 也按官方抽取后计算。`exact_match` 与 `lite_f1` 保留 Lite 原评分用于诊断。
评分函数已对固定上游实现做离线差分验证；核心 SearchQA 的公共行为没有修改。

SkillOpt 仅观察 train 反馈，用 dev 严格提升接受候选。完成全部演化并冻结最终 snapshot
之后，才分别评估初始和最终技能的同一份 test。报告 hard、F1、改善/退步题数和配对
bootstrap 95% 区间。接口错误会保存证据并在一次重试失败后停机，不将服务故障当成
低准确率继续演化。

两种 harness 从同一官方空白技能正文起步，避免给其中一侧预置答案规则。MiniAgent
保留其原生 system prompt；Claude Code 保留原生 system prompt，通过本地 plugin 的
`flashrsi:searchqa` 技能加载规则。前者文件为 `skills/main.md`，后者为
`skills/searchqa/SKILL.md`，native frontmatter 是 harness 适配差异。

2026-09-19 18:03:35（北京时间）的完整已完成缓存前缀审计覆盖 7,172 次答题和 380 次
evolver 调用。MiniAgent 的 4,000/4,000 条记录均与对应快照重建的原生 system/技能内容
一致；Claude Code 有 3,170/3,172 条记录包含成功的 `flashrsi:searchqa` 调用及回答前的
对应技能正文注入。另外两次直接回答未调用 Skill，分别发生在初始 baseline 和第 9 步
候选 dev；后者以 79.0% 对 79.5% 被拒绝。两条原始回答仍按预定规则计分，未重跑或豁免。
这些数字仅描述该截止时间前的记录，不能作为最终全程激活率。

所有已检查调用的模型配置与 Flash 答题、Pro 演化一致；Claude/Pro 的响应模型标签也
一致。Mini 保存的 `usage.model_calls.model` 是请求侧选择，未保留服务原始响应的
model 字段，因此不能把它当作独立响应证明。技能内容载入也不等于模型语义上遵循了
每条规则。逐条记录、固定文件清单与两条缺失见证保存在
`runs/skillopt-searchqa-deepseek/full/evidence/native-model-prefix-20260919T100335.869256Z/`；
只读复核脚本为框架中的 `scripts/audit_native_model_prefix.py`，完成后应再次覆盖全部记录。

## 与论文的可比性

| 论文 Table 1，GPT-5.5 | 初始 SearchQA | SkillOpt |
| --- | ---: | ---: |
| Direct model call | 77.7% | 87.3% |
| Codex | 81.8% | 87.3% |
| Claude Code | 81.9% | 85.9% |

来源：[SkillOpt 论文 Table 1](https://arxiv.org/html/2605.23904v1#S3.T1)，
[官方固定源码](https://github.com/microsoft/SkillOpt/tree/79124b37e9a6371e13b753f8bcd7adb1e493ade1)。

对齐项包括 400/200/1400 数据成员、官方 hard/F1 评分、相同初始技能、4 epochs、
batch 40、reflection minibatch 8、merge batch 8、slow/meta update 和 dev gate。
以下差异需要随结果一起保留，不能宣称论文逐字或逐调用复现：

- 模型换成 DeepSeek，MiniAgent 不属于论文的三种 harness；使用 high reasoning，
  论文 SearchQA 的默认配置为 medium。Claude 的原生 SDK 不提供与 Chat 完全等价的
  max_tokens/temperature 参数，所以不声称两个协议的生成参数完全相同。
- Lite 使用固定 edit budget 4，论文主配置为 cosine 4→2。论文 constant-budget 消融
  的 SearchQA 也报告 87.3%，但这不保证换模型仍然相同。
- Lite 按 `seed + epoch` 打乱，官方按 `seed + epoch * 1000`；Lite 先切 minibatch
  再分成功/失败，官方先分组再分 minibatch；rejected buffer、prompt 与多文件 patch
  协议也有实现差异。
- 输入保留 Lite 的 supplied-context/short-answer 包装，系统提示与技能激活遵循
  各 harness 原生行为。官方使用自己的 `<answer>` 包装与执行环境。
- Lite 对 slow candidate 也执行严格 dev gate；官方公开主分支当前默认关闭此项，
  但官方 checkpoint 文档明确论文运行启用了 gate。
- 本次运行还使用下文记录的请求重试、超长轨迹进度事件清理和无效补丁拒绝协议。
  超时或输出截断后的重试只依据执行状态，不依据答案是否正确；所有固定题目仍需完成。
  这些额外尝试增加实际调用量，因此相同训练轮数不表示与论文具有相同的模型调用预算。
  失败尝试、自动恢复和无效补丁记录随实验保留，不能只用最终准确率宣称逐调用复现。

## 中断恢复与结果

每个实验保存 `plan.json`，锁定模型参数、源代码 hash、数据 hash 和初始 snapshot。
配置或源代码变化时必须使用新 `--run-root`，避免混合实验。

本次有一项明确记录的迁移例外：串行版本迁移到独立 Worker 请求并发 4 的实验入口，
并添加上下文溢出后的进度事件清理。`--adopt-serial-plan` 只在原源码指纹、数据、
初始技能和全部原配置完全一致时允许迁移；它只接受列出的新增执行元数据。原计划保存在
`serial-plan.json`，新旧计划与处理规则保存在 `parallel-migration.json`，没有改写旧缓存。
已完成结果不能迁移。该选项只需首次迁移使用，当前 v2 已完成迁移。

并发类保留原串行版逐字提示、Worker 调用序号、反思分组、合并树、ranking 和选择规则。
15 项离线测试覆盖并发上限、两 epoch 的 slow/meta、取消清理、最终 snapshot 和真实
CachedLLM 的缓存键等价。两侧并发版真实 smoke 已完成并通过独立验收；两侧技能均未改变，
前后 test 波动不能视作演化收益。

随后 Claude Code 的第 10 个 fast step 生成了一份无法精确应用的补丁：四条选中编辑的
第一条替换目标在当前技能中出现 0 次。原程序会终止。`RecoverableSkillOpt` 将这种
**已完成反思、合并、排序但无法应用**的补丁记录为 `invalid_patch`，保留当前技能并把
错误加入有界 rejected 反馈；不生成 candidate、不调用 dev、不编造 score。该 step
仍消耗原预算。并行反思/合并/排序中的解析错误仍终止，避免取消时改变缓存调用序号。
顺序执行的 meta/slow 格式错误也明确记录；meta 无效时保留旧 meta，slow 无效时保留
当前技能。HTTP、I/O 和其他非补丁异常继续报错。

此项通过 `--adopt-patch-recovery` 做第二次受限迁移；旧计划为
`pre-patch-recovery-plan.json`，新旧指纹及规则为 `patch-recovery-migration.json`。
模型参数、数据、所有原代码指纹和缓存均保持一致，只增加声明的拒绝策略及其源码 hash。
当前 v2 已升级，恢复运行使用本页开头的新入口，不再使用旧串行/并发/仅补丁恢复入口。
新增 21 项专项测试覆盖合法路径等价、拒绝原子性、继续下一批、缓存序号及 slow/meta；
实际 Claude 前 10 步已做无网络缓存重放，126 次 Worker 调用全部命中，独立验证复现了
第 10 步补丁错误并确认保留原技能。证据在
`runs/skillopt-searchqa-deepseek/full/evidence/patch-recovery-cached-replay/audit.json`。
之后 Claude 第 15 步也出现无法应用的补丁；该步按同一策略拒绝并继续。
独立复核重现了补丁错误、确认没有候选或分数字段，并检查下一批训练仍使用原最佳快照；
证据为 `runs/skillopt-searchqa-deepseek/full/evidence/claude-step15-invalid-patch-audit.json`。

2026-09-19 21:54（北京时间）恢复记录：两侧之前均因 evolver 返回非法 JSON 而停止，
MiniAgent 完成 fast step 20、Claude Code 完成 fast step 23，分别停在下一步的 Worker
阶段；尚未执行最终测试。此前已完成协议恢复迁移，但进程记录仍指向旧入口。本次通过
新版入口的双侧无模型 dry-run，确认完整配置、数据与源码指纹匹配后，启动独立实验及
原有有界守护进程。恢复、报告和验收相关的 75 项定向测试通过。

`ProtocolSafeLLM` 对 fast reflection/merge/rank 的格式错误，在同一逻辑调用内以原始
prompt 和原模型参数最多追加两次请求。原回复缓存保持不变，额外回复保存于
`cache/protocol_retries/`；重启复用这些回复，不重置次数、不改变后续调用序号。两次
仍无有效回复则停止；slow/meta 保留原拒绝规则。此执行协议是额外的论文差异，新增
请求量在报告中单列为 `worker_protocol_retry`。

迁移证据为各侧的 `pre-protocol-recovery-plan.json` 和
`protocol-recovery-migration.json`。中断前缓存清单位于
`runs/skillopt-searchqa-deepseek/full/evidence/protocol-recovery-20260919T134459Z/cache-prefix-sha256.json`，
本次缓存复核结果为 setup 目录的 `resume-cache-prefix-verification.json`。
单独恢复一侧时在本页开头命令中加入 `--harness miniagent` 或
`--harness claude_code`；先确认对应实验和守护进程均已停止，避免重复启动。

Claude Code 的 `SystemMessage/subtype=thinking_tokens` 会为每个推理 token 发出数字
进度通知。一次反思因 30,125 条此类通知膨胀至 8,375,155 字符，服务报约 336 万输入
tokens，超过 104 万上下文上限。新 Worker **先发送原提示**；仅遇到明确上下文溢出时，
去掉这种纯数字进度事件后重试。实际推理文本、工具调用与返回、问题、答案、评分和其他
系统事件均保留；该故障输入清理后为 162,224 字符。原始 target 轨迹不变，Worker 记录
保存两次实际输入及 `ContextLengthRecovery`，成功的旧请求可原样复用。此项是执行恢复
差异，不能宣称所有请求与未修复版本逐字相同。4 项专项测试验证恢复条件与内容保留；
10 项迁移测试验证指纹拒绝、证据保留、重放和并行文件写入。

同一命令重启会创建新的 attempt，从头重放算法，复用**同一调用序号**已完成的模型
请求。不同 epoch/不同评估仍会重新采样，不会仅因 snapshot 和 task 相同就偷换成旧
结果。尚未完成的请求重新执行。此机制位于独立实验脚本，不是 Lite 核心的 checkpoint
接口；已完成实验不会重复收费运行。

当前两侧另有独立 `supervise_searchqa_experiment.py` 守护进程，状态在各实验目录的
`supervisor.json`，日志为 setup 目录的 `supervisor-<harness>.log`。它观察真实 PID，
仅在进程确实结束后，对 429/部分 5xx、超时、连接失败或没有生成完整答案的 length
错误按同一命令退避恢复。每个请求最多自动恢复 3 次，每侧总计最多 32 次；其他错误
或超限标为 `needs_attention`，不会跳过题目、改模型参数或伪造分数。守护进程的 7 项
测试覆盖错误分类、进程身份和恢复命令。已有守护进程时不要重复启动。

上下文恢复已在真实 Pro 请求上成功：清理后的实际输入为 44,405 tokens，完整输出
5,064 tokens。迁移前 1,503 份完成缓存哈希全部不变，证据为
`runs/skillopt-searchqa-deepseek/full/evidence/parallel-recovery-live-audit.json`。

```text
runs/skillopt-searchqa-deepseek/<profile>/
  data-manifest.json
  summary.json
  miniagent/  claude_code/
    plan.json  status.json  result.json
    seed/  cache/  final_skills/
    attempts/skillopt-<harness>-searchqa-<timestamp>/
      config.yaml  snapshots/  trajectories/  result.json
```

只有 `result.json` 的 `status: finished` 加完整 test 数量才能证明完成；`plan.json`
或 `status: running` 不能证明运行存活。检查进程 PID 与实时日志确认状态。
最终技能在 `final_skills/`，每次反思、patch、候选与接受/拒绝记录在对应 attempt。
不要把 smoke 的小样本分数当作全量测试成绩。

两侧单独启动时，共享 `summary.json` 可能暂时只包含最后结束的一侧；各自的
`<harness>/result.json` 才是完成依据。确认两侧结果均为 finished、运行进程均已退出后，
再执行本文开头不带 `--harness` 的完整命令，程序会复用两侧已完成结果并重建合并汇总，
不会再次调用模型。下方报告脚本直接读取两个独立结果，不依赖临时的单侧 summary。

随时从已保存证据生成报告，不会调用模型或改变实验：

```bash
.venv/bin/python scripts/summarize_searchqa_experiment.py \
  --run-root runs/skillopt-searchqa-deepseek --profile full
```

报告为 `<profile>/report.md` 与 `report.json`，包含每步 dev 分数、前后 test、配对区间、
技能是否改变与服务报告的 token 用量。尚未执行的测试保留为空，不用 dev 代替 test。

本次运行另保存了独立绘图脚本 `scripts/plot_searchqa_results.py`。
它从报告生成带报告 hash 的 PNG/SVG 和绘图清单，保存在 `full/figures/`。dev 图明确标注
200 题开发集，无效补丁放在无分数事件行；只有两侧完成且前后各 1,400 条测试执行齐全时，
才生成单独的 test 图。绘图库使用 uv 隔离环境，不改实验的 `.venv` 或依赖锁文件：

```bash
uv run --no-project --python 3.13 --with 'matplotlib==3.10.7' python \
  scripts/plot_searchqa_results.py \
  --report runs/skillopt-searchqa-deepseek/full/report.json
```

完成后从原始回答独立重算评分并检查实验完整性：

```bash
.venv/bin/python scripts/verify_searchqa_experiment.py \
  --run-root runs/skillopt-searchqa-deepseek --profile full \
  --output runs/skillopt-searchqa-deepseek/full/evidence/full-verification.json
```

退出码 0 表示已保存证据通过，1 表示证据不一致，2 表示尚未完成。检查覆盖固定数据
hash、官方评分重算、相同测试题、测试晚于训练、每个 epoch 的完整训练覆盖、严格 dev
选择、最终 snapshot 内容 hash 和汇总数字。完整实验还要求在第 20/30/40 个 fast step
之后存在计划中的三组 slow/meta 证据：对应的前后 snapshot、按 seed 抽出的同序 20 题、
原始比较 prompt、有效 meta 的继承、slow 技能变更及其 dev gate；无效回复必须有对应的
无分数拒绝记录。该检查不等于独立重跑或对网关底层权重的验证。
验收脚本现有 48 项定向测试通过；比较题的顺序按 benchmark 的 hash 排序再进行算法抽样，
其中一项测试直接使用真实 benchmark loader 核对。更新后对已有串行和并行版本的双 harness 真实 smoke
记录再次只读复核，四侧均通过。Smoke 只有一个 epoch，不包含 slow/meta 更新。

实验日志不再单独附带框架源码包，复现使用框架中的代码、保存的实验配置及数据。
`runs/skillopt-searchqa-deepseek/full/evidence/*source*.json` 保留各阶段的代码 SHA256、recipe 指纹与迁移记录，
`environment.json` 保留实际依赖版本；这些 JSON 中引用的历史 ZIP 已按用户要求移除。
删除和脚本迁移清单见 `source-cleanup-20260920.json`。框架目前存在未提交改动，
记录的基线 commit 不单独代表实验执行版本；后续保存框架版本时应包含实验脚本及相关改动。

## 实验结束汇总与日志整理（2026-09-20）

普通 runner 及 SearchQA runner 现在都会在完成或报错退出后写入实验目录中的
`end-summary.md`、`end-summary.json`，并打印汇总到 stdout。内容包括测试成绩、
候选接受数量（若适用）、按角色和成功/失败拆分的 token、缓存读取/写入、用量缺失
条目、日志中已有的 SDK 费用及其计价依据。摘要生成失败只发出警告，不触发模型重试。
强制终止或未落盘请求无法补出不存在的用量。

缓存实验仅统计 canonical cache，包含 `cache/errors` 和 `cache/protocol_retries`；
不重复计算恢复 attempt 中的重放轨迹，也不累加 prompt 中嵌套的历史 usage。
普通 runner 统计已保存的顶层 trajectory。缓存 token 属于输入 token 的子集；
SDK `total_cost_usd` 与 `model_usage.costUSD` 不重复累计。无费用字段用 `null`，
不得当作零费用；网关实际费用未记录，不根据模型名称猜测价格。

已完成的本次实验可用前文 summarize 命令离线补建报告，无需再次执行模型。
本次汇总代码更新改变了源码指纹；历史 full 目录保留原有配置与源码 hash 供核对，
后续真实运行使用新的 `--run-root`，不要修改旧指纹绕过保护。

日志总入口为 `runs/README.md`。已删除前期 smoke/接口/本地 harness 测试及离线恢复
重放副本，保留逐文件删除 SHA256 清单、离线恢复 audit 和所有正式失败/恢复证据。
正式实验日志没有因成绩差而删减。当前仍是本地原始证据集，含绝对路径和服务地址；
开源时从副本脱敏，保留数据来源声明，并重新核验完整性。
