# ACE 迁移

ACE 采用 Generator → Reflector → Curator 流程，支持 offline 与 online 两种模式，
复用 Algorithm、Snapshot、Worker 和 runner。

## 入口和执行流程

- 主循环：[algorithms/ace/__init__.py](../flashrsi/algorithms/ace/__init__.py)。
- 私有 playbook 协议：[\_playbook.py](../flashrsi/algorithms/ace/_playbook.py)。
- 角色提示：[\_prompts.py](../flashrsi/algorithms/ace/_prompts.py)。
- 小规模配置：[examples/ace.yaml](../examples/ace.yaml)。

先在 YAML 中分别填写 target 与 Worker 的模型、凭据及连接地址，再运行：

```bash
uv sync --extra all
uv run flashrsi run --config examples/ace.yaml
```

默认安装已包含 Claude Code 依赖。使用该目标时将 `agent.name` 改为 `claude_code`，
并为 `agent.llm` 单独配置 Anthropic 兼容模型及端点。Worker 仍可使用纯 LLM；
也可按现有配置选择 Agent Worker。算法通过 `worker.ask()` 获取文本。

1. offline 评估初始版本的 dev 分数，作为 best；online 不做这一步。
2. 每个 epoch 遍历 train，按 batch 执行当前版本。
   offline 用 `seed + epoch` 打乱；online 按原顺序流式消费。
3. Reflector 读取训练输入、答案、输出、状态、主指标等评分与错误信息。正确答案也反思。
   未达 `success_threshold` 且有剩余反思轮数时，把本次诊断加到原问题前重试；
   不修改 Snapshot，也不累积前几轮的诊断。Curator 读取最后一次诊断及其对应轨迹。
4. 把 helpful/harmful 标签写回对应 bullet 的计数；neutral 不改变计数。
5. 按 `curator_frequency` 调用 Curator。只接受 ADD；系统分配编号、按 section 插入，
   对规范化后的相同内容去重。合法增量立即成为 current，无逐步 dev 接受门槛。
   格式错误、非 ADD、超出条数或体积预算的提案被拒绝并记录，最近 4 次拒绝供后续 Curator 参考。
6. offline 每 `eval_steps` 个训练 batch 评估 dev，无论该步是否调用或接受 Curator。
   只有严格提升才改变 best。结束时补评尚未验证的 current，并切换到 best 的原 Snapshot。
   online 不评估 dev，也不恢复 best，直接保留流式演化出的版本。
7. runner 只在演化结束后评估 test；dev/test 轨迹不会交给 Reflector 或 Curator。

## offline 与 online

两种模式共用同一套 Reflector/Curator、ADD 协议、计数和持续应用；差别只在结束时如何交账。

| | offline | online |
| --- | --- | --- |
| train 顺序 | 每个 epoch 按 `seed + epoch` 打乱 | 保持原顺序，消费一次 |
| dev | 初始评估 + 按 `eval_steps` 周期评估 | 不访问；可以为空 |
| 最终版本 | 恢复 dev 最佳 Snapshot | 保留最后的 current |
| 算法自报分数 | `decision` 记录的 `kind: "promote"`、`score`（best 的 dev 分） | `decision` 记录的 `kind: "stream"`、`online_score` 与 `online_tasks` |

online 的「先预测和计分、后更新」在代码中只有一处：每个 batch 执行后立刻记录其主指标，
再进入 Reflector。因此 `online_score` 是各任务**第一次**遇到时、由当时那版 playbook
得到的分数；反思重试的分数、以及后续 playbook 的分数都不计入。这是流式累积指标，
不是 held-out 结果。

`online_score` 与 runner 最后写入 `result.json` 的 `test_score` 是两个不同口径：
前者来自 train 流的一次性执行，后者是最终版本在 test 上的独立评估。两者不可互相替代，
也不能相加或比较。

反馈边界与 offline 一致：Reflector 读到 `ground_truth`。
train 划分本来就带标签，两种模式共用同一份 evidence 渲染，算法不按模式分叉 prompt。
复现论文的无标签在线设定需要单独设计 evidence 协议，当前未实现。

## Playbook 如何加载

ACE 读 target 声明的 `instruction_file`，要求它属于 `prompt` 组件。
保留该文件原始前缀，在 `<!-- flashrsi:ace-playbook -->` 标记之后维护结构化 playbook。
空更新不会创建文件或新 Snapshot。重新使用已有 ACE 版本时读取原有后缀，不重复追加标记。
其他文件保持原样，新增能力不要求 harness 声明新的公开字段。

- MiniAgent：追加到 `prompts/system.md`，由原生运行时加载。
- Claude Code：创建或追加 `CLAUDE.md`，由既有 SDK 适配层通过 `system_prompt.append` 加载，
  保留原生 `claude_code` system prompt。

旧版默认演化 skill；Lite 此处使用 prompt，是为了让每次目标执行都收到 playbook，
避免依赖模型是否主动调用某个 skill。算法本身没有 harness 名称或文件布局分支。
原有指令中的普通列表不自动转换为 ACE bullet；计数与去重只处理管理后缀内的条目。

## 参数

| algorithm 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `mode` | `offline` | `offline` 或 `online`；决定整套结束策略 |
| `num_epochs` | 1 | train 遍历次数 |
| `batch_size` | 1 | 每次 Generator 处理的任务数 |
| `max_steps` | null | batch 数上限，不是模型调用次数；正整数或 null |
| `edit_budget` | 4 | 一次 Curator 提案的最大 ADD 数，去重前检查 |
| `eval_steps` | 100 | 按训练 batch 计数的 dev 评估间隔；online 不使用 |
| `max_reflection_rounds` | 3 | 每批最多反思轮数；最多重试轮数为此值减一 |
| `curator_frequency` | 1 | 每隔多少 batch 调用 Curator；只策展当前批的最后诊断 |
| `playbook_token_budget` | 80000 | 按 `ceil(字符数 / 4)` 估算的 playbook 体积上限；不是实际 tokenizer 限额，不含原指令 |
| `success_threshold` | 1.0 | 批内全部任务 finished 且主指标达到此值时停止重试 |
| `max_evidence_chars` | 24000 | 每次角色提示中训练证据的字符上限 |
| `seed` | 42 | offline 的 epoch 内 shuffle 种子；online 不使用 |

两种模式都要求 train 非空；offline 另外要求 dev 非空。
对 `Task.env` 不为空的环境任务，当前没有通用的反思上下文注入协议，
因此启用多轮重试会在启动时报错；设 `max_reflection_rounds: 1` 可使用已有环境执行适配，
具体的 ACE × 环境 benchmark 组合仍需端到端验证。

## 来源与迁移差异

直接参考旧版 FlashRSI commit `5efe9b438483710060183c6c3ecbc5062b410a58` 的
`src/flashrsi/algos/ace/{algorithm,playbook,prompts}.py` 与 `tests/test_ace_opro.py`。
其 `core/recipes.py` 锁定的上游为
[ace-agent/ace](https://github.com/ace-agent/ace/tree/82709de050e1db6e6ef2f07bcb0393560b94992a)，
commit `82709de050e1db6e6ef2f07bcb0393560b94992a`。
本实现依据旧实现迁移；尚未独立核验该上游 commit，不声称逐行复现论文实现。

保留 ADD-only、section/编号/计数、精确文本去重、Reflector/Curator、持续应用、周期 dev
和 best 恢复；未引入旧 Trainer、Recipe、State/checkpoint 管理体系，无额外生产依赖。
当前未实现断点恢复、语义去重、playbook 压缩或完整 reasoning 事件渲染。

与旧实现的具体差异：

- playbook 进入目标声明的指令文件，而不是旧版 `component_id` 指定的 skill。
- 为 Reflector 提供训练 `ground_truth`（可为空）；旧版提示要求分析标准答案但 evidence 没有输出该字段。
- 最后一轮反思后不再额外重试，使诊断与供 Curator 读取的轨迹一致；原始 Task 保持不变。
- dev 评估按训练步调度，不再嵌在成功 ADD 的分支中；只有计数变化的版本也能被验证。
- 最终通过现有 Snapshot 指针恢复 best，保留沿途的 Snapshot 和决策记录，不复制出一个新版本。
- 多行 ADD 内容收为一条 bullet，系统始终分配 ID 和初始计数；不会接受模型伪造的编号。
- 空操作、重复 ADD、未知/neutral 标签均保持文本和版本不变。
- online 不打乱 train，并显式记录流式累积分数。旧版 online 仍复用 offline 的 shuffle，
  也没有单独上报在线指标，因而无法与最终 test 区分口径。

## 验证状态

- CLI `--algorithm.mode online` 正确写入 resolved config；`--algorithm.mode stream`
  由基类 `_ranges` 在启动时拒绝，不执行任务或模型调用。

```bash
uv run pytest tests/test_ace.py tests/test_ace_native.py
```

机制测试覆盖持续应用、跨越降分、恢复最佳/平分保留、批次上限、反思隔离、计数、周期验证、
拒绝反馈、预算与协议、无操作、Worker 错误及记录持久化；online 另外覆盖不验证 dev、
保留降分版本、先计分后更新、顺序消费与空 dev 划分。
本地集成测试通过 runner、真实 MiniAgent 子进程/OpenAI SDK、真实 Claude SDK/CLI，
使用本地模拟模型服务和 SearchQA fixture；验证 playbook 出现在实际请求中、候选评分改变、
最终 test、脱敏配置、Snapshot 与汇总保存。online 的 runner 测试另外验证不产生 dev 评估记录，
且 `online_score` 与 `test_score` 是两个独立数字。

**尚未运行远程真实模型 smoke、HotpotQA 组合或全量实验；这里的模拟分数仅验证接入机制，
不代表演化效果。**
