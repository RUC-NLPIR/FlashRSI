# Evo-Harness 接入

论文：[Evo-Harness: Context-to-Harness Skill Compilation for Self-Evolving Agents](https://arxiv.org/abs/2608.15071v2)。
上游：[A-EVO-Lab/a-evolve，release/evo-harness](https://github.com/A-EVO-Lab/a-evolve/tree/release/evo-harness)，
固定 revision：`3c7c7b8c62a3f07da1d4407aa03f0ca079954bcf`，MIT License。

本接入移植单次在线学习和两级 skill 编译，执行模型权重保持冻结。
Curator 直接编辑目标 harness 的原生 skill 文件，由目标 Agent 在执行中选择、加载。
最终产物是普通 Snapshot；保存、恢复后直接 `Agent.rollout()` 即可使用，无需在推理时保留 Algorithm 或 Worker。

```text
固定批次 Snapshot → 原生 skill 发现/加载 → 单次执行并评分
                                              ↓ 失败
下一批 Snapshot ← 原生文件编译与提交 ← 候选经验反思
```

## 学习流程

- 按 benchmark 提供的 train 顺序消费一次；`batch_size` 划分批次，`max_steps` 限制批次数。
  不重复 epoch、不重试当前任务，也不在 dev 上选择版本。
- 同一批任务共用一个 Snapshot；整批完成后才反思、编译与更新。
- 仅对执行失败或低于 `success_threshold` 的结果反思。Worker 读取已完成的训练轨迹和反馈，
  返回 `lesson / trigger / evidence / scope_hint`，也可返回 `{"skip": true}`。
  使用基类证据处理，移除 RunConfig，截断时标记。
- Topic Curator 编译任务类型或接口相关程序；General Curator 比较本批经验，提取跨任务模式。
  两个角色依次调用同一个 Worker 的 `edit()`，通过原生文件工具创建、合并、修订或删除 skill。
- 每个新增或修订的版本只引用本批支持它的候选经验；general skill 至少引用
  `general_min_tasks` 个不同任务。旧版本的来源保存在 Snapshot 历史中，不能自动充当新规则的证据。
  未修改的 skill 保留来源。代码检查 ID 约束，共享模式的语义判断交给 Curator。
- 每级编辑作为一次原子提交处理：权限、来源、层级、数量或字符预算不合法则整级拒绝。
  原生无关 skill 按基线归属保护，不能添加 provenance 接管；也不能通过剥离 provenance
  留下未受管的程序。层级与来源检查依据真实 Snapshot 差异，额外 frontmatter 修改也会被检查。
  合法更新持续采用，不以 dev 或在线分数提升作为接受门槛。
- 记录的是每次更新前的在线成绩；runner 再对最终冻结 Snapshot 做独立 test。
  test 使用基类评分路径，不参与反思和编译。

## 复用与资源布局

不新增核心接口或版本管理类。实现复用 `Algorithm._evaluate/_record/_evidence/_trajectory_evidence`、
`Worker.ask/edit` 和 `Snapshot.check_out/commit`；权限、凭据脱敏、工作目录清理由现有框架负责。
算法只可写 `skill`，`config` 仅供读取。配置、prompt、runtime 和组件声明的保护
复用 Snapshot 的组件权限，不再定义算法自己的激活声明、配置字段协议或加载依赖映射。
原生无关 skill 按已有文件的归属保护；新目录不能遮蔽同名的平铺 skill。
来源、层级、预算检查留在算法中；发现和加载留在原生 harness 中。
这些检查不执行候选程序、不调用模型，也不引入成绩接受门槛。

受管 skill 使用原生目录和 YAML frontmatter，例如：

```text
skills/verify-evidence/SKILL.md
```

```yaml
---
name: verify-evidence
description: Verify supplied evidence on evidence-backed questions
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [train-0]
---
```

其后是可包含代码块的程序正文。`name/description` 用于原生发现，`flashrsi` 保存编译来源。
历史上将 JSON 库嵌入 prompt 的实验产物不属于此文件协议，需重新演化。

- **Claude Code**：复用原生 plugin skill 发现和 Skill 工具。若显式限制工具，需允许 `Skill`。
  默认原生 system prompt 保留，Curator 无需修改 CLAUDE.md。
- **MiniAgent**：保留 `agent.yaml.skills` 对已有 `skills/<name>.md` 的全文内联行为。
  原生 workspace loader 自动发现 `skills/<name>/SKILL.md`，存在目录技能时自动提供
  `read_skill`；添加、删除技能只需编辑文件，无需同步修改配置。目录技能只向首次请求
  提供 description，模型按需读取正文，来源元数据不进入正文。
  无目录技能时保持原有工具列表；显式启用的工具仍由原生配置控制。
  实现细节见 [harness 接入说明](agent-integration.md)。

Algorithm 不按 harness 或 benchmark 名称分支；Curator 根据 checkout 识别原生布局。
两类目标都通过普通执行路径消费最终文件。自定义 harness 需具备相应的原生 skill 能力；
本实现不会自动为自定义 runtime 添加加载器。仅声明 skill 组件不代表拥有发现能力；
使用自定义来源时，应先验证普通 Agent 能消费其目录技能。

## 参数与运行

见 [示例配置](../examples/evo_harness.yaml)。Worker 必须是能编辑目录的 Agent；
`algorithm.worker.type: llm` 在启动时报错。目标和 Worker 的模型、连接配置分别填写。

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `batch_size` | 4 | 每次固定版本消费的任务数 |
| `max_steps` | null | 最多消费的批次数；null 表示完整 train 流 |
| `success_threshold` | 1.0 | 低于此分数的训练执行需要反思 |
| `general_min_tasks` | 3 | 每个新增/修订 general 程序所需的本批任务数 |
| `max_general_skills` | 10 | general 库数量上限 |
| `max_topic_skills` | 30 | topic 库数量上限 |
| `max_skill_chars` | 2000 | 单条正文字符上限 |
| `max_library_chars` | 48000 | 库的规范化 YAML 元数据和正文总字符上限 |
| `max_evidence_chars` | 24000 | 反思及编译证据字符上限 |

```bash
uv run --extra all flashrsi run --config examples/evo_harness.yaml
```

默认采用保守的本批证据约束；`batch_size < general_min_tasks` 时无法新增或修订 general 程序。
若一个批次的失败经验不足，General Curator 应保留已有程序。

## 与上游的取舍

- 反思由独立 Worker 读取记录上下文，未续接 solver 的原生会话。
- 选择与加载交给原生 solver，而非独立 Selector 调用；没有算法级的注入数量或字符硬预算。
  因此移除了 `max_injected_skills/max_injected_chars`，库预算约束编译产物，不约束每次执行上下文。
- Curator 直接写原生文件，取代 JSON 操作协议及临时执行 Snapshot，保证最终 Snapshot 可独立执行。
- 来源门槛按当前修订版本的本批支持证据计算，不继承旧规则的证据计数。

这些取舍复用 FlashRSI 的执行和版本设计，也改变了选择与编译协议；本实现属于流程移植，
不能直接等同于论文的完整复现或比较论文成绩。

## 验证

```bash
uv run pytest tests/test_evo_harness.py tests/test_evo_harness_validation.py tests/test_evo_harness_native.py tests/test_miniagent_skills.py
```

专项覆盖一次消费、批内固定版本、失败反思、两级编译、采用合法退步版本、来源门槛、原子拒绝、
保存恢复、嵌套代码块、原生按需加载、可选工具和 Worker 错误传播。
原生集成测试通过真实 MiniAgent 子进程/OpenAI SDK、Claude SDK/CLI 与本地模拟服务，
验证 Worker 文件工具提交，以及恢复后的 Agent 直接 rollout；模拟成绩只验证接入行为。

尚未运行远程真实模型、真实容器 benchmark 或论文分数复现。

代码入口为 `evo_harness/__init__.py`；只另保留与仓库其他算法一致的 `_prompts.py`。
技能解析和预算由算法私有 `_skills()` 承担，提交的归属、层级和来源检查直接在
`_compile()` 中完成。
