## 1. 项目目标与定位

FlashRSI是一个让self-evolving算法通过统一的snapshot和worker接口，跨不同harness和benchmark演化的framework。用户能够用简单的命令行就运行起来各种演化算法，中间数据集会自动下载、算法能够自动适配各种harness。

FlashRSI 复现 self-evolving 算法：给定一个 agent 和一个 benchmark，
自动演化出一个更好的 agent，并留下可复现的记录。


整体数据流：
```
  Benchmark ──Task──→ Harness ──Trajectory──→ Benchmark.grade ──Score──┐
                         ↑                                             │
                      Snapshot                                         │
                         │                                             ↓
                         └────────── Algorithm ←────────────── 读轨迹、决定换不换
```

使用的例子类似下面这样：
```bash
flashrsi run \
  --benchmark searchqa \
  --algorithm skillopt \
  --agent miniagent \
  --model deepseek-v4-flash \
  --worker-model gpt-5 
```

Algorithm、Agent、Benchmark 是三个扩展点，由 runner 负责实例化和连接。Algorithm 通过公共接口调用 Agent 和 Benchmark，不依赖具体实现，也不根据它们的名称编写分支。
Agent 通过 Snapshot 表达可版本化的文件状态。算法通过编辑文件产生候选 Snapshot，评估候选后决定是否更新当前版本。
不同 Agent 使用各自的文件布局，通过统一的 component 名称表达演化范围。框架保证算法可迁移，不要求 Snapshot 跨 Agent 通用。
不支持算法所需组件或执行能力的组合，在启动时明确报错。

MVP 的验收目标：两个 benchmark（SearchQA + Terminal-Bench 2.0）、
两个 harness（Claude Code + MiniAgent）、一个算法（SkillOpt），
算法一行不改能在两个 harness 上跑。

整体需要满足：
1. 对算法开发者： 能够尽可能简单的基于我们的框架实现自己的算法，避免学习太多复杂抽象和名词概念
2. 对框架维护者： 框架需要尽可能模块化，易于维护
3. 对于benchmark开发者：框架需要能够尽可能简单的接入各种benchmark

## 2. 名词表
只有这五个词，写代码和写 YAML 都只用它们。

| 概念 | 定义 |
|---|---|
| Algorithm | 拥有完整演化流程，决定如何产生、评估和选择候选 |
| Benchmark | 提供任务、数据划分、评分规则和评分反馈 |
| Agent | 一种 harness 的接入实现，负责解释 Snapshot 并执行任务 |
| Worker | 为算法生成文本或编辑文件的角色，可使用 Agent 或纯 LLM 后端 |
| Snapshot | 某个 Agent 版本的不可变文件树，包含文件内容、组件归属和版本来源 |

## 3. 核心数据模型设计

### benchmark端：
单个任务的数据结构：
```python
@dataclass(frozen=True)
class Task:
    task_id: str
    question: str  # 交给 agent 的问题 / 指令
    ground_truth: str | None = None  # 答案式 bench 的标准答案
    env: str | None = None  # 环境式 bench 的镜像 / 任务目录
    metadata: Mapping[str, Any] = ...
```

整个benchmark的数据结构：
```python
class Benchmark:
    name: str
    description: str
    metadata: Mapping[str, Any]  # 记录来源等额外信息
    primary_metric: str  # grade() 必定填充的指标名，算法据此判断单条轨迹成败

    def __init__(self, config: Mapping[str, Any]) -> None:
        ...
        # 接收 config.benchmark；校验 name 与本类一致

    def load(self) -> Mapping[str, tuple[Task, ...]]:
        ...
        # 读取task，并根据config映射为：{'train': [...], 'dev': .., 'test': ...}

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        ...
        # 在traj的metrics字段填充dict，包含了该轨迹的所有评分信息以及primary_metric

    # 基类统一提供，load() 之后可读；未 load 时访问报错
    @property
    def train(self) -> tuple[Task, ...]: ...
    @property
    def dev(self) -> tuple[Task, ...]: ...
    @property
    def test(self) -> tuple[Task, ...]: ...
```

`grade()` 要求每条轨迹带有 Task，因此只接收 `rollout()` 的结果；`ask()` 和 `edit()` 产生的
Worker 轨迹不属于任何任务，不送去评分。

### Agent端
```python
@dataclass(frozen=True)
class SnapshotFile:
    content: bytes
    component: str
    executable: bool = False


@dataclass(frozen=True)
class Snapshot:
    files: Mapping[str, SnapshotFile]
    component_rules: Mapping[str, tuple[str, ...]]  # component 名称 -> 文件路径规则

    # 以下元数据由框架维护，算法无需手动填写
    id: str
    agent_type: str
    root_id: str
    parent_id: str | None
    format_version: int = 2

    # 目录与版本之间的转换
    def check_out(self, *, working_dir: Path | None = None) -> ContextManager[Path]: ...
    def commit(self, working_dir: Path) -> Snapshot: ...
    def changed_paths(self, candidate: Snapshot) -> tuple[str, ...]: ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> "Snapshot": ...
```

开源 Agent 的 Snapshot 包含其实际执行的源码和运行资源；闭源 Agent 的 Snapshot 包含 SDK 可控制的配置与扩展文件。FlashRSI 接入代码、依赖环境、凭据、日志和任务工作目录不进入 Snapshot。
文件映射与文件条目均不可变。普通编辑目录通过 `Snapshot.commit()` 转换为新的 Snapshot；持久化 Snapshot 通过 `Snapshot.load()` 恢复。
同一初始 Snapshot 的历史版本和兄弟候选可以切换。加载时检查 Agent 类型、格式和版本来源。

`check_out()` 和 `commit()` 都在 Snapshot 上，基线因此是显式的：`current.commit(workdir)` 的
父版本就是 `current` 本身。这样同一个版本可以同时存在多个 checkout，种群类算法（GEPA、
EvoPrompt）也能同时持有多个候选——若把基线记在 Agent 内部，一个 Agent 只能记住一个基线。
`working_dir` 让临时目录落在实验目录的 `working/` 下。

`component_rules` 参与 Snapshot 的 id 哈希：同样的文件配不同的分类规则是两个不同版本，改过
`components.yaml` 之后旧候选无法再被 `update` 进来。算法绑定的编辑 scope 反过来**不**参与
版本身份，同一个版本在不同 scope 下仍是同一个版本。

```python
class Agent:
    name: str
    description: str

    # 目标 Agent 必须初始化；纯 LLM worker 不持有 Snapshot，访问该属性报错
    snapshot: Snapshot

    # 由适配器旁的 components.yaml 声明，随 Snapshot 一起传递
    component_rules: Mapping[str, tuple[str, ...]]

    # 该 harness 视为主指令的文件；整体重写单个指令文件的算法据此定位目标
    instruction_file: str | None = None

    # 基类统一提供
    def set_scope(self, scope: Mapping[str, str]) -> None: ...

    def update(self, snapshot: Snapshot) -> None: ...

    async def rollout(
        self, tasks, *, snapshot: Snapshot | None = None
    ) -> tuple[Trajectory, ...]: ...

    async def run(self, prompt: str, working_dir: Path | None = None) -> Trajectory: ...

    async def ask(self, prompt: str) -> str: ...

    async def edit(self, working_dir: Path, prompt: str) -> str: ...

    # 后端唯一需要实现的方法
    async def _run(
        self, prompt: str, working_dir: Path | None = None
    ) -> Trajectory: ...
```

| 操作 | 必须保证的行为 |
|---|---|
| 初始化 | Agent 从适配器所在目录按 `components.yaml` 自动建立初始 Snapshot |
| `set_scope()` | 选择各 component 的权限（`rw` / `none`），不改变文件标签；启动时确定 |
| `Snapshot.check_out()` | 创建独立目录，导出该版本对当前 scope 可见的文件 |
| `Snapshot.commit()` | 相对该 Snapshot 检查编辑，返回候选，不切换当前版本 |
| `rollout()` | 基于当前版本或传入的候选执行任务，并把 Task 附回轨迹 |
| `update()` | 校验并切换当前版本指针，不影响已经启动的执行 |
| `edit()` | 只修改传入目录，返回该 Agent 对这次编辑的说明，不提交 target 的 Snapshot |

接入一个 harness 只需要两件事：在适配器旁放 `components.yaml`，以及实现 `_run`。
`run` / `ask` / `edit` / `rollout` 都由基类在 `_run` 之上提供，后端不必分别实现，也不管理版本。
`_run` 通过 `self.files_dir` 拿到本次执行的版本目录，通过 `self.config` 拿到本次固定的角色配置。

`edit()` 返回文本，是为了让编辑可被核对：AHE 用返回的说明对照 `changed_paths()` 的真实改动，
拒绝与自述不符的编辑。返回值不改变「提交由调用方决定」这一点。

`run()` 接收 prompt 而不是 Task：非环境任务的后端只看到问题文本，Task 由 `rollout()` 在结果上
附回；环境任务由绑定的执行 integration 处理，它能看到完整 Task。因此 `_run` 内不应假设可以
读到 `task.metadata`。

文件归类由目标 Agent 决定，算法只选择 scope。已有文件保留原分类；新增文件按固定规则分类；删除检查原分类；重命名按删除和新增处理。分类冲突或新增路径无法分类时拒绝提交。分类规则由 `components.yaml` 声明，不能由 worker 修改。
scope 和兼容性校验在 commit、候选 rollout、update 入口统一执行。文件级 scope 不表达文件内部某几行的权限。

一个 component 可以包含多个文件，也可以在初始版本中没有任何文件，因此 scope 不足以定位单个文件。`instruction_file` 由 Agent 声明哪个文件是它的主指令，供整体重写单个指令文件的算法使用；未声明时为 `None`。算法通过该属性取得路径，不按 harness 名称分支，也不从文件布局猜测；未声明该属性的 Agent 上，此类算法在启动时报错。声明的路径必须可归入该 Agent 自己的组件规则。

组件名称在各 harness 间保持同一套词汇，算法据此表达演化范围：`prompt`、`skill`、`code`、
`tool`、`agent`、`hook`、`config`。每个 harness 只声明自己实际拥有的那几个。

```python
@dataclass(frozen=True)
class Trajectory:
    task: Task | None = None  # Worker 的 ask/edit 轨迹没有 Task
    status: str = "finished"  #  "finished" | "error"
    output: str = ""
    messages: tuple[Mapping, ...] = ()  # agent 的中间步骤
    metrics: Mapping[str, float] = ...  # grade() 之后才有
    error_message: str | None = None  # status == "error" 时必填
    usage: Mapping[str, Any] = ...  # 保存轨迹token消耗等信息
```

Trajectory、Task、Snapshot、SnapshotFile 都不可变，映射字段在构造时转为只读视图。

### 算法端
```python
class Algorithm:
    name: str
    description: str

    # 算法声明要改哪些 component；基类据此调用 target.set_scope()
    # {"*"} 表示该 target 声明的全部 component
    evolve_scope = frozenset()

    # 参数的默认值与取值范围，由基类统一校验
    _defaults = {}
    _ranges = {}

    def __init__(self, config, *, target, worker, benchmark):
        self.config = config
        self.target = target
        self.worker = worker
        self.benchmark = benchmark

    async def evolve(self) -> Snapshot: ...

    # 可选钩子
    def _normalize(self) -> None: ...  # 别名规范化，在 _ranges 校验之前
    def _check(self) -> None: ...  # 需要数据或 target 才能判断的前置条件


class SkillOpt(Algorithm):  # 作者写的全部
    name = "skillopt"
    description = "..."
    evolve_scope = {"skill"}

    async def evolve(self) -> Snapshot: ...
```

算法作者需要记住的就是基类提供的这几个固定动作：

| 动作 | 用途 |
|---|---|
| `await self._evaluate(snapshot, tasks, label=...)` | 评估但不选中；返回的 `Results` 自带 `.score`（primary_metric 均值）和 `.per_task`（逐题分数） |
| `self._read_text(snapshot)` | 读取可见 component 的文本文件 |
| `self._candidate(baseline, files)` | 把文本改动写成候选 Snapshot |
| `self._promote(current, best, **details)` | 搜索结束时选中一个版本并记录决策 |
| `self._instruction_path()` | target 声明的主指令文件路径，含组件校验 |
| `self._record(label, payload)` | 写一条实验记录 |
| `self._evidence(rows)` / `self._trajectory_evidence(traj)` | 组装给 Worker 看的证据，按 `max_evidence_chars` 截断 |
| `await self.worker.ask(prompt)` | 向 Worker 提问，返回纯文本 |
| `await self.worker.edit(working_dir, prompt)` | 让 Worker 编辑一个目录，返回它对编辑的说明 |

Worker 调用的轨迹记录、凭据脱敏和失败报错由基类自动完成，算法不再自己记这一笔。
Worker 回复的解析（`<INS>` 标签、代码块）属于发问的 prompt 自己的知识，放在
`algorithms/_replies.py`，不在 Agent 上包一层返回类型。

一个典型的演化循环：

```python
async def evolve(self) -> Snapshot:
    current = self.target.snapshot
    best = (await self._evaluate(current, self.benchmark.dev, label="baseline")).score

    training = await self._evaluate(current, self.benchmark.train, label="train")

    with current.check_out() as workdir:
        await self.worker.edit(workdir, self._build_prompt(training))
        candidate = current.commit(workdir)

    score = (await self._evaluate(candidate, self.benchmark.dev)).score
    if score > best:
        self.target.update(candidate)  # 到这一步才真的换；不调用 = 拒绝

    return self.target.snapshot
```

## 4. 文件清单
```
flashrsi/
├── core/
│   ├── snapshot.py
│   ├── agent.py
│   ├── benchmark.py
│   ├── algorithm.py
│   └── trajectory.py        # Trajectory 与 Results
├── agents/
│   ├── miniagent/
│   ├── claude_code/
│   └── llm.py               # 纯 LLM Worker
├── algorithms/
│   ├── skillopt/  opro/  gepa/  evoprompt/  ace/  ahe/
│   └── _replies.py          # Worker 回复的解析
├── benchmarks/
│   ├── searchqa/  hotpotqa/  terminal_bench/  tau3_banking/
│   ├── _data.py             # 数据读取与确定性划分
│   ├── _qa.py               # 问答类 benchmark 的共用实现
│   ├── _archive.py          # 数据集归档下载
│   └── metrics.py           # EM / F1
├── integrations/
│   ├── harbor.py            # Terminal-Bench 容器执行
│   ├── tau2.py              # τ³ 用户模拟器
│   └── _container.py
├── _records.py              # 实验记录与凭据脱敏
├── _run_summary.py          # 用量统计与结束汇总
├── config.py
├── runner.py
└── cli.py
```

## 5. 严格要求

1. 本文档由开发者维护。AI 可以提出修改建议，不直接修改本文档。
2. 本文档列出的公共类、方法签名及行为约定，未经开发者同意不得新增或变更。
3. 现有契约下的具体实现、私有辅助函数和缺陷修复可以正常进行。
4. 本文档是 MVP 的唯一规范，其他设计文件作为参考

## 6. MVP计划
0. 设计好config的配置文件和代码，实现config，包括整个实验的working dir的设计。 ✅
1. 完成cli的代码 ✅
2. 完成benchmark的相关代码，接入searchqa benchmark ✅
3. 完成其他agent的基类实现。整理清楚思路。 ✅
4. 接入miniagent ✅
5. 接入claudecode agent ✅
6. 接入skillopt这个算法 ✅
7. 接入terminial bench ⏳ 数据、Harbor 执行与离线测试完成；真实容器与真实模型演化待验证（需 Docker）

已超出 MVP 范围的部分：算法另有 OPRO、GEPA、EvoPrompt、ACE、AHE；benchmark 另有 HotpotQA、
τ³ Banking。SkillOpt × SearchQA 已在两个 harness 上完成全量实验。
