# FlashRSI-Lite

按 [mvp_doc.md](mvp_doc.md) 逐步实现。当前完成配置、实验目录、CLI 准备流程，
以及 Benchmark 核心模型和 SearchQA 接入。Agent 和算法执行将在后续步骤接入。

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
  --model deepseek-v4-flash \
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
子目录目前为空，实际执行与结果记录将在对应步骤实现。

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
按配置名选择实例的 runner、CLI 执行和 Agent 将在后续步骤接入。

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
