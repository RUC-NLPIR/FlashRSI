# FlashRSI-Lite

按 [mvp_doc.md](mvp_doc.md) 逐步实现。当前完成配置、实验目录、CLI 准备流程、
Benchmark 核心模型与 SearchQA 接入、Snapshot 和 Agent 基类，以及 MiniAgent 后端。
Claude Code、算法和 runner 执行将在后续步骤接入。

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

`--model` 对应 `agent.model_name`，`--worker-model` 对应
`algorithm.worker.model_name`。`--output-dir` 设置实验输出根目录。
所有配置参数都支持 `--完整.字段.路径 值` 或 `--完整.字段.路径=值`，层级不受限制。
新增参数无需注册 CLI 选项，值按 YAML 解析：

```bash
uv run flashrsi run --config example.yaml --prepare-only \
  --benchmark.limit 20 \
  --algorithm.rounds 3 \
  --algorithm.worker.model_name gpt-5 \
  --algorithm.worker.temperature=0.7 \
  --agent.tools '[{name: search, timeout: 30}]'
```

也保留可重复的 `--set 路径=值` 写法：

```bash
uv run flashrsi run --config example.yaml --prepare-only \
  --set benchmark.limit=20 \
  --set algorithm.rounds=3 \
  --set algorithm.worker.temperature=0.7 \
  --set 'agent.tools=[{name: search, timeout: 30}]'
```

优先级为默认值 < YAML < 常用命令行参数 < 点路径参数和 `--set`。
点路径参数和 `--set` 混用时，同一路径以最后一次设置为准；两者都优先于常用参数。
省略的参数保留 YAML 中的值；列表可整体设置，路径指向映射中的键。
负数可直接作为值；以 `-` 开头的普通字符串使用等号写法，例如 `--agent.prompt=-text`。

`python -m flashrsi` 与 `flashrsi` 使用同一入口，`flashrsi run --help` 查看参数。
目前不加 `--prepare-only` 会明确报错并返回非零状态，不创建目录；
接入 runner 后，普通 `run` 才会执行演化。准备模式不下载数据或调用模型。

## 配置

以 [example.yaml](example.yaml) 为准。`load_config` 返回支持属性访问的 `Config`：

| 部分 | 字段 | 用途 |
| --- | --- | --- |
| `run` | `output_dir` | 实验输出根目录 |
| `benchmark` | `name`, `split` | Benchmark 与自动/比例划分策略 |
| `agent` | `name`, `model_name`, `api_key`, `base_url` | 目标 Agent 及模型连接配置 |
| `algorithm` | `name`, `worker` | 演化算法及它使用的 Worker |

每个类别及 `algorithm.worker` 都可直接添加额外参数，无需修改配置类。
额外参数支持嵌套映射和列表，并会在覆盖、保存、重新加载时保留。
配置层继续校验已有公共字段；额外参数的含义由对应模块处理。

```python
config = load_config("example.yaml")
print(config.benchmark.name)
print(config.algorithm.worker.model_name)

config.benchmark.limit = 100
config.algorithm.worker.temperature = 0.7
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

`algorithm.worker.type` 可以是 `llm` 或 `agent`。Worker 同样使用 `model_name`、
`api_key`、`base_url`；当 `type: agent` 时，还需要 `name` 来选择 harness，例如：

```yaml
algorithm:
  name: skillopt
  worker:
    type: agent
    name: claude_code
    model_name: your-model
    api_key:
    base_url:
```

Agent 和 Worker 都必须指定 `model_name`。`api_key`、`base_url` 可以留空，
其后端默认行为将在模型接入时实现。配置层不读取环境变量，也不检查模型是否可用。
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
    overrides={"algorithm": {"worker": {"model_name": "another-model"}}},
)
```

`run.output_dir` 相对 YAML 所在目录解析；通过 `overrides` 设置时相对当前工作目录。
未传 YAML 时也相对当前工作目录。返回配置中的 `output_dir` 为绝对路径。

## 实验目录

调用 `prepare_run_dir(config)` 会自动在 `run.output_dir` 下创建当前实验目录。
`flashrsi run --prepare-only` 已接入这个函数。

目录名为 `{algo}-{agent_name}-{bench}-{time}`，时间采用本地时间，精确到微秒。
例如：

```text
runs/skillopt-miniagent-searchqa-20260914-163000-123456/
├── config.yaml       # 解析后的配置；两个 api_key 字段置空
├── snapshots/        # 初始版本和候选版本
├── trajectories/     # rollout 与评分结果
└── working/          # checkout、任务执行等临时目录
```

重复调用创建新目录；若时间戳碰撞，则增加一微秒重试，已有实验保持原样。
运行时配置保留传入的 API key，写入磁盘的配置副本将其置空。
CLI 准备模式下这些子目录仍为空。通过 Python 使用 Snapshot 时可将 `working/`
传给 `Snapshot.check_out()`，并显式保存版本；runner 自动执行与结果记录将在后续步骤接入。

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

当前没有自动注册机制；`flashrsi.benchmarks` 只是导出 `SearchQA` 类。
没有必要的 `SearchQABenchmark` 别名已移除。Benchmark 可单独通过 Python 使用，
按配置名选择实例的 runner 和 CLI 执行将在后续步骤接入。

### 数据集准备与独立使用

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

## Agent：一个运行入口，自动获取文件版本

调用者使用 `agent = MyAgent(config)` 创建 Agent，执行时只使用
`await agent.run(prompt, working_dir=None)`。提问、任务执行和编辑文件使用同一个入口，
始终返回完整的 Trajectory；编辑场景可以忽略最终 output，但消息和用量仍然保留。
算法启动时用 `set_scope` 设置组件的默认可见和编辑权限。Agent 没有独立的 `ask`、
`edit` 或 checkout 接口，也不记录演化历史。

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
不需要知道 harness 使用 SDK 还是子进程。Algorithm 和 runner 的正式实现留在后续步骤，
下文示例展示它们会使用的现有接口。

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
            model=self.config.get("model_name"),
        )
        return Trajectory(
            output=result.text, messages=result.messages, usage=result.usage
        )
```

公开的 `run` 由基类实现，负责准备版本文件、固定本次执行版本及清理文件。接入者实现
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

`config` 可为完整实验配置（使用其中的 `agent` 部分），也可为单独的 Agent/Worker
配置映射。Worker 通常传 `config.algorithm.worker`。`source_dir` 相对路径按当前工作目录
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
agent = MyAgent(config)
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
`rollout` 的结果。基类暂不执行带 `Task.env` 的任务，会在任何任务开始前明确报错；
容器和终端环境由后续 benchmark 执行适配处理，不把镜像名猜作本地工作目录。

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
真实模型或 Claude SDK。Claude Code、SkillOpt 和 runner 的正式接入仍留在
后续步骤，CLI 只支持准备模式。`mvp_doc.md` 中旧签名尚未同步，仍由开发者维护；
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
agent = MiniAgent(config)
benchmark = SearchQA(config)
benchmark.load()
graded = benchmark.grade(asyncio.run(agent.rollout(benchmark.dev)))
print(graded[0].output, dict(graded[0].metrics))

# 同一入口也可提问，或给 Worker 一个待编辑的目录。
answer = asyncio.run(agent.run("What is 2 + 2?"))
# edited = asyncio.run(worker.run("Improve the skill files", working_dir=directory))
```

默认 `agent.yaml` 只加载 prompt 和 `skills/main.md`，使用题目附带的上下文，不调用
搜索服务。传入 `working_dir` 时增加 `list_files`、`read_file`、`write_file`、
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
两种情况都先结束并等待子进程，POSIX 上也结束同一进程组内的工具进程。
这不提供容器或操作系统沙箱。带 `Task.env` 的任务仍由基类明确拒绝，等待后续环境接入。

| 配置字段 | 默认值 | 含义 |
| --- | --- | --- |
| `model_name` | 必填 | OpenAI 或兼容端点上的模型名 |
| `api_key` | 空 | 优先使用配置，否则读取 `OPENAI_API_KEY` |
| `base_url` | 空 | 优先使用配置，否则读取 `OPENAI_BASE_URL` 或使用 SDK 默认地址 |
| `max_turns` | `10` | 原生循环轮数，最后一轮请求直接回答 |
| `max_tokens` | `4096` | 原生主循环和强制回答的输出预算；辅助调用沿用原生各自预算 |
| `llm_max_retries` | `1` | 原生每次调用的最大尝试次数 |
| `reasoning_effort` | 未设置 | 显式设置时原样传给模型 API |
| `extra_body` | `{}` | 原样传给模型 API 的额外请求字段，主调用和辅助调用均生效 |
| `timeout` | `300` | 整次运行超时，单位秒 |
| `source_dir` | 内置目录 | 可选完整来源目录，须带 `components.yaml` 和实际 runtime/资源 |

所有模型通过 OpenAI SDK 调用 OpenAI 或兼容端点。主循环中 GPT/o 系列使用 Responses，
其余模型使用 Chat Completions；辅助文本调用使用 Chat Completions。模型名保留原值，
包括 `org/model`，仅兼容去除已有的 `openai/` 前缀。
模型的推理或其他专有选项由 `reasoning_effort` 和 `extra_body` 显式配置，
不根据模型名推断或自动启用。

适配类把模型连接和预算配置写入子进程的原生环境变量。
`model_name` 对应 `FLASHRSI_MINIAGENT_MODEL` / `FLASHRSI_MINIAGENT_SIDE_MODEL`，
`base_url` 对应 `FLASHRSI_MINIAGENT_BASE_URL` / `FLASHRSI_MINIAGENT_SIDE_BASE_URL`，
`api_key` 和 `extra_body` 分别对应 `FLASHRSI_MINIAGENT_API_KEY` 和
`FLASHRSI_MINIAGENT_EXTRA_BODY`（JSON）。主调用和辅助调用使用相同配置。
父进程环境不变，已有 `FLASHRSI_MINIAGENT_*` 模型设置由本次配置覆盖。

题目、资源目录和运行参数通过 stdin 传递，密钥通过子进程环境传递。
凭据不写入源码、Snapshot、命令行参数或请求文件，返回记录和内置 harness 日志会脱敏。
`Trajectory.messages` 保存原生对话列表，`usage.model_calls` 保存原生记录的
用量、模型、轮次和耗时，`usage.turns` 保存循环轮数。统计范围沿用原生主循环、辅助调用和
强制回答，网页提取用量没有额外补齐；不再额外保存完整 provider 响应。API 错误保留已有对话和用量，
不会把失败当成成功答案。

`runtime/` 基于旧 FlashRSI 的 `miniagent/harness/`（来源提交
`5efe9b438483710060183c6c3ecbc5062b410a58`）移植，保留原生 ReAct、middleware、
自定义工具、Chat/Responses 连续调用及原生环境变量入口。保留的小改动单独列在
[harness 改动清单](docs/agent-integration.md#harness-的小改动) 和
[原生差异文件](docs/miniagent-harness.patch)，没有框架 config/client 注入或运行时 monkey patch。
未搬入旧框架的 registry、演化算法、ArtifactStore 或评测脚本。
默认资源来自旧版的文本 seed。Web 工具代码保留，但默认关闭，需要自行添加原生 schema
及配置搜索/浏览服务；本阶段不验证真实 Web 服务。

本阶段集成测试使用真实本地子进程、真实 OpenAI SDK 和本地模拟 HTTP 服务，验证两种
协议、skill/code 候选、文件编辑、SearchQA 离线评分、并发、取消和错误处理。
CLI 仍只执行 `--prepare-only`，完整演化运行待 SkillOpt/runner 接入。

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

当前调用使用非流式 Chat Completions，Atria 已验证支持；不要通过 `extra_body`
设置 `stream: true`，原生循环需要完整响应对象。
