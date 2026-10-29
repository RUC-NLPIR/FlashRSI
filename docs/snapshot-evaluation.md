# 跨 benchmark 评估已保存的 Snapshot

在 benchmark A 上演化、选好版本后，可以把同一资源版本交给 benchmark B 的评分器。
评估入口只执行 B 的 `test`，不创建 Worker，不构造演化算法，也不继续训练或选优。
配置中的 `algorithm` 段会被忽略；Target 和 B 所需的 Judge、User Simulator、Postprocess 等仍须配置。

## 直接运行

先在 A 的 `result.json` 中读取 `snapshot_id`，找到同目录下
`snapshots/<snapshot_id>.json`。不要误选 `snapshots/worker.json`。

填写 [evaluate_hotpotqa.yaml](../examples/evaluate_hotpotqa.yaml) 的 Target 模型与凭据，然后从仓库根目录运行：

```bash
flashrsi evaluate --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run-A/snapshots/SELECTED_ID.json --check-only

flashrsi evaluate --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run-A/snapshots/SELECTED_ID.json
```

`--snapshot` 相对当前工作目录解析；直接 CLI 的 benchmark 专用路径也遵循原有的当前工作目录规则。
`--check-only` 检查兼容性、运行条件和测试数据，可能下载数据，但不调用模型、不创建实验结果目录。
它不验证远程模型认证或可用性。

示例仅评估公开的 HotpotQA validation 池中的 16 题，不声称官方 leaderboard test。
也可显式设置 `benchmark.data_path: {test: /absolute/path/to/native-data.jsonl}`，
此时使用 `split: auto` 并移除比例或 `split_counts`，以保留该 test 角色。
不要把 B 的测试数据用于继续调参后仍声称是独立的迁移测试。

## 自动准备依赖和资源

自动准备脚本也支持 `--snapshot`，并只安装 Target 与 benchmark 所需的依赖：

```bash
python scripts/run_experiment.py --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run-A/snapshots/SELECTED_ID.json --plan
python scripts/run_experiment.py --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run-A/snapshots/SELECTED_ID.json --check-only
python scripts/run_experiment.py --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run-A/snapshots/SELECTED_ID.json
```

启动器中的 benchmark 专用路径相对 YAML 文件解析，与直接 CLI 的既有行为不同；使用绝对路径可统一两种入口。
Docker、原生工具、数据授权和额外模型角色的要求不变。

## 兼容性与版本固定

全部 30 个接入的逐项分工见 [Harness 与任务环境边界](benchmark-harness-boundary.md)。

Snapshot 固定的是 Agent 的资源；任务环境由目标 benchmark 的接入层准备。
以 MiniAgent 从 AppWorld 迁移到 SpreadsheetBench2 为例：

| 随同一个 Snapshot 使用 | 由目标 benchmark 提供 |
| --- | --- |
| `runtime/` 中演化后的 agent loop、上下文管理和完成判断代码 | 任务容器、工作目录和初始数据 |
| `tools/`、工具描述、middleware、sub-agent | 环境服务、公共操作入口及其运行时说明 |
| prompt、skill、`agent.yaml` | 输入输出路径、任务完成要求和独立评分器 |

AppWorld 在运行时提供客户端及 `apis` 使用说明；这些不是 MiniAgent 的版本文件。
SpreadsheetBench2 使用自己的 Harbor 任务，提供工作簿、任务 Python 和输出路径，
不会加载 AppWorld 的数据库或客户端。切换环境不会覆盖 Snapshot 中已经演化的 loop、工具或技能，
也不会按组件名自动删除文件；迁移评估仍使用同一个 Snapshot ID。

这里的工具有两种归属：MiniAgent 的通用 shell 实现属于 Agent，随 Snapshot 固定；
AppWorld 的应用操作服务、SpreadsheetBench2 的工作簿及依赖属于任务环境，由各自接入层提供。
新增接入优先通过原生 shell/CLI 或 SDK 在运行时连接任务服务，不把任务专用配置写回 Agent 源码或版本目录。
任务工作目录与 Agent 的 `files_dir` 必须分开，评分文件只交给独立评分器。

MCP 同样按资源归属处理：Agent 自带的通用 MCP 配置和服务代码属于 Agent 资源；
任务专用 MCP 的服务、连接和说明应由该 benchmark 的接入层通过 harness 的原生配置能力提供，
凭据留在运行配置中。当前这两个 benchmark 均不要求 MCP；本轮没有新增通用 MCP 注入接口，
也不把已写入历史 Snapshot 的 MCP 配置静默替换成目标环境的配置。

框架负责连接正确的任务环境，不自动改写演化策略。若历史 prompt 或代码已经写死 AppWorld API，
在 SpreadsheetBench2 上仍可能失败；原样迁移测试会保留并记录这种结果。
这与客户端、工作簿或 Python 依赖没有准备好是两类问题。

- Target 的 Agent 类型、原始资源版本 `root_id`、组件规则必须与 Snapshot 兼容。
- 同一 Agent 名称不保证兼容；安装了不同版本的原生资源时可能出现 root 不一致。
  此时使用生成 A 时的项目版本，或让 `agent.source_dir` 指向当时的原始资源目录（含 `components.yaml`）。
  不要把演化后的文件重新捕获成新 root 来冒充原来的 Snapshot。
- 评估使用保存文件中的完整资源版本，不修改原 Snapshot。模型、连接、超时和工具权限来自 B 的 Target 配置，
  不会从 Snapshot 继承；需要公平比较时保持这些运行条件一致。
- 版本不兼容、文件损坏或空 test 会在执行任务前报错。B 的加载器仍按配置准备数据；只执行 test 不等于只下载 test。

## 输出

每次评估创建独立的 `evaluation-<agent>-<benchmark>-<timestamp>/` 目录：

| 文件 | 内容 |
| --- | --- |
| `evaluation.json` | 输入 Snapshot 路径、ID、root/parent、Agent 类型、B 的数据来源与 test 角色 |
| `snapshots/<id>.json` | 本次实际评估的完整资源版本 |
| `trajectories/000002-test.json` | B 的逐题结果、运行配置、模型用量和评分 |
| `result.json` | `mode: evaluate`、来源、`test_score`、`test_metrics`、`test_tasks` |
| `config.yaml` | 脱敏配置，不含 Worker 配置 |
| `end-summary.*` | 结果与用量汇总 |
| `error.json` | 创建结果目录后发生的异常 |

评分失败时保留 `trajectories/000001-rollout.json`，成功评分后由 test 记录取代，避免重复统计用量。
容器 benchmark 继续使用现有的产物归档。运行失败的题目按该 benchmark 的既有规则计分，
因此仍需检查逐题 `status`，不能把流程完成视为所有题目执行成功。
