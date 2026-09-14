# FlashRSI-Lite

按 [mvp_doc.md](mvp_doc.md) 逐步实现。当前完成配置、实验目录与 CLI 准备流程。
Benchmark、Agent 和算法执行将在后续步骤接入。

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
| `benchmark` | `name`, `split` | Benchmark 与 train/dev/test 划分比例 |
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
顶层仍为上述四个类别，`benchmark.split` 仍按 train/dev/test 比例校验。

`benchmark.split` 默认是 `train: 0.6, dev: 0.2, test: 0.2`。各比例在 0 到 1
之间，总和必须为 1；实际数据划分将在 Benchmark 接入时实现。

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
