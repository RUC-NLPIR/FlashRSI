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
class Task:
    task_id: str
    question: str                     # 交给 agent 的问题 / 指令
    ground_truth: Optional[str] = None   # 答案式 bench 的标准答案
    env: Optional[str] = None            # 环境式 bench 的镜像 / 任务目录
    metadata: Mapping[str, Any] = ...
```

整个benchmark的数据结构：
```python
class Benchmark:
    name: str
    description: str              
    metadata: dict # 记录来源等额外信息

    def load(self) -> Mapping[str, Tuple[Task, ...]]: ...
        # 读取task，并根据config映射为：{'train': [...], 'dev': .., 'test': ...}
    def grade(self, trajs: Tuple[Trajectory, ...]) -> Tuple[Trajectory, ...]: ...
        # 在traj的metrics字段填充dict，包含了该轨迹的所有评分信息以及primary_metric
```

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

    # 以下元数据由框架维护，算法无需手动填写
    id: str
    agent_type: str
    root_id: str
    parent_id: str | None
    format_version: int = 1

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> "Snapshot": ...
```

开源 Agent 的 Snapshot 包含其实际执行的源码和运行资源；闭源 Agent 的 Snapshot 包含 SDK 可控制的配置与扩展文件。FlashRSI 接入代码、依赖环境、凭据、日志和任务工作目录不进入 Snapshot。
文件映射与文件条目均不可变。普通编辑目录通过 Agent.commit() 转换为 Snapshot；持久化 Snapshot 通过 Snapshot.load() 恢复。
同一初始 Snapshot 的历史版本和兄弟候选可以切换。加载时检查 Agent 类型、格式和版本来源。

```python
class Agent:
    name: str
    description: str

    # 目标 Agent 必须初始化；纯 LLM worker 不要求持有 Snapshot
    snapshot: Snapshot

    # component 名称 -> 文件路径规则
    component_rules: Mapping[str, tuple[str, ...]]

    # 基类统一提供
    def set_scope(self, components: set[str]) -> None: ...

    def check_out(
        self, snapshot: Snapshot | None = None
    ) -> ContextManager[Path]: ...

    def commit(self, working_dir: Path) -> Snapshot: ...

    def update(self, snapshot: Snapshot) -> None: ...

    async def rollout(
        self, tasks,
    ) -> tuple[Trajectory, ...]: ...

    # 后端按支持的能力实现
    async def run(
        self, task: Task, snapshot: Snapshot
    ) -> Trajectory: ...

    async def ask(self, prompt: str) -> str: ...

    async def edit(
        self, working_dir: Path, prompt: str
    ) -> None: ...
```

| 操作 | 必须保证的行为 |
|---|---|
| 初始化 | Agent 根据 seed 和自身分类规则建立初始 Snapshot |
| `set_scope()` | 选择允许修改的 component，不改变文件标签；启动时确定 |
| `check_out()` | 创建独立目录，并在框架内部记住 checkout 时的基线 |
| `commit()` | 相对该基线检查编辑，返回候选，不切换当前版本 |
| `rollout()` | 基于当前版本进行rollout |
| `update()` | 校验并切换当前版本指针，不影响已经启动的执行 |
| `edit()` | 只修改传入目录，返回 `None`，不提交 target 的 Snapshot |

文件归类由目标 Agent 决定，算法只选择 scope。已有文件保留原分类；新增文件按固定规则分类；删除检查原分类；重命名按删除和新增处理。分类冲突或新增路径无法分类时拒绝提交。分类规则不能由 worker 修改。
scope 和兼容性校验在 commit、候选 rollout、update 入口统一执行。文件级 scope 不表达文件内部某几行的权限。




最好是一个agent（比如claudecode）就是一个子类，然后一开始就是一个snapshot（用变量储存），这个变量保存整个harness对应的文件树： 开源harness就是整个harness的代码。闭源harness就是一个我们基于sdk翻译出来的文件树。这文件树里面的每个文件包括两个内容：
1. 文件内容
2. 文件所属的agent组件类别。这个是便于后面算法指定evolve scope指定。在算法启动的时候，可以通过调用agent内部的方法来实现这种scope的赋值（按照component）。

然后所有agent的基类都有一个check_out方法，就是把当前的这个snapshot变量写到一个文件夹目录下。

这个snapshot可以是一个单独的数据类型，然后agent可以自由的加载不同的snapshot（前提都是自己派生出去的）。

除了check_out之外，agent再实现一个update方法来加载某一个文件路径的snapshot。感觉这样写可能会整齐一点：
```python
workdir = self.target.check_out()                    # snapshot -> 目录
await self.worker.edit(working_dir=workdir, prompt='...')
candidate = self.target.commit(workdir)              # 目录 -> 新 snapshot（此时还没换）

trajs = self.benchmark.grade(await self.target.rollout(dev, snapshot=candidate))
if mean(t.metrics[self.metric] for t in trajs) > self.best:
    self.target.update(candidate)                    # 到这一步才真的换；不调用 = 拒绝
```
然后每个hanress就只需实现基本的edit\ask\run功能，以及指定好这个check_out方法以及怎么加载回来



```python
class Trajectory:
    task: Task
    status: str                       #  "finished" | "error"
    output: str
    messages: Tuple[Mapping, ...] = ()  # agent 的中间步骤
    metrics: Mapping[str, float] = ()  # grade() 之后才有
    error_message: Optional[str] = None       # status == "error" 时必填
    usage: dict # 保存轨迹token消耗等信息
```

### 算法端
```python
class Algorithms
    name: str
    description: str
    def __init__(self, config, *, target, benchmark):
        self.worker = Agent(config)
        self.target = Agent(config...)
        self.benchmark = Benchmark.load_from_config(config)
    async def evolve(self) -> Agent
        training_tasks = self.benchmark.train
        await trajs = self.target.rollout(training_tasks)
        self.benchmark.grade(trajs)
        
        score = mean(t.metrics['main_score'] for t in trajs)
        if score > self.best: ...            
            # 基于worker进行edit
            workdir = self.target.check_out() 
            await self.worker.edit(working_dir=workdir, prompt='...')
            candidate = self.target.commit(workdir)              # 目录 -> 新 snapshot（此时还没换）

            trajs = self.benchmark.grade(await self.target.rollout(dev, snapshot=candidate))
            if mean(t.metrics[self.metric] for t in trajs) > self.best:
                self.target.update(candidate)                    # 到这一步才真的换；不调用 = 拒绝

        return self.target

```
```python
class Algorithm:
    name: str
    description: str
    def __init__(self, config, *, target, worker, benchmark):
        self.config = config
        self.target = target
        self.worker = worker
        self.benchmark = benchmark

    async def evolve(self) -> Snapshot:
        self.target.set_scope({"skill"})

        metric = self.benchmark.primary_metric
        dev = self.benchmark.dev
        current = self.target.snapshot

        baseline = self.benchmark.grade(
            await self.target.rollout(dev, snapshot=current)
        )
        best = mean(t.metrics[metric] for t in baseline)

        training = self.benchmark.grade(
            await self.target.rollout(
                self.benchmark.train, snapshot=current
            )
        )

        with self.target.check_out(current) as workdir:
            await self.worker.edit(
                working_dir=workdir,
                prompt=self._build_prompt(training),
            )
            candidate = self.target.commit(workdir)

        evaluated = self.benchmark.grade(
            await self.target.rollout(dev, snapshot=candidate)
        )
        score = mean(t.metrics[metric] for t in evaluated)

        if score > best:
            self.target.update(candidate)
            best = score

        return self.target

class SkillOpt(Algorithm):                           # 作者写的全部
    name = 'skillopt'
    description = '...'
    async def evolve(self) -> Agent: ...
```

## 4. 文件清单
flashrsi/
├── core/
│   ├── snapshot.py
│   ├── agent.py
│   ├── benchmark.py
│   ├── algorithm.py
│   └── trajectory.py
├── agents/
│   ├── miniagent/
│   └── claude_code/
├── algorithms/
│   └── skillopt/
├── benchmarks/
│   ├── searchqa/
│   └── terminal_bench/
├── integrations/
│   └── harbor.py
├── config.py
├── runner.py
└── cli.py


## 5. 严格要求

1. 本文档由开发者维护。AI 可以提出修改建议，不直接修改本文档。
2. 本文档列出的公共类、方法签名及行为约定，未经开发者同意不得新增或变更。
3. 现有契约下的具体实现、私有辅助函数和缺陷修复可以正常进行。
4. 本文档是 MVP 的唯一规范，其他设计文件作为参考

## 6. MVP计划
0. 设计好config的配置文件和代码，实现config，包括整个实验的working dir的设计。
1. 完成cli的代码
2. 完成benchmark的相关代码，接入searchqa benchmark
3. 完成其他agent的基类实现。整理清楚思路。
4. 接入miniagent
5. 接入claudecode agent
6. 接入skillopt这个算法
7. 接入terminial bench

