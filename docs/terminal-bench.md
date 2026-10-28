# Terminal-Bench 2.0 / 2.1

`benchmark.name: terminal_bench` 通过 Harbor 执行 Linux 容器任务，并读取原生 verifier reward。
默认 `version: "2.0"`；2.1 用 `version: "2.1"`。两个版本共用一个适配器，计为一个 benchmark。

## 数据与环境

当前默认从公开上游 Git 仓库取得固定提交的原生任务；不再要求私有 Hugging Face 镜像。
可用 `benchmark.data_path` 指向一个原生 task 或包含 task 文件夹的目录。
旧镜像配置仍由对应数据加载器处理，但不是当前默认入口。

| 版本 | 固定上游 | 提交 |
| --- | --- | --- |
| 2.0 | [laude-institute/terminal-bench-2](https://github.com/laude-institute/terminal-bench-2) | `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c` |
| 2.1 | [harbor-framework/terminal-bench-2-1](https://github.com/harbor-framework/terminal-bench-2-1) | `7131e4375048a0e408a8fb404b5f499d726b695b` |

需要 Python 3.12+、Git、Docker Linux daemon 和 Docker Compose。推荐 Linux / WSL + Python 3.12。
一键入口按 `harbor` extra 安装固定 Harbor 版本。配置明确的 `split_counts` 或比例；
单一任务集合的实验 train/dev/test 是用户定义的划分，不是官方排行榜划分。

## 运行

先填写 [2.1 + OPRO 示例](../examples/terminal_bench21_opro.yaml) 中 Target 与 Worker 各自的模型和凭据：

```bash
python scripts/run_experiment.py --config examples/terminal_bench21_opro.yaml --plan
python scripts/run_experiment.py --config examples/terminal_bench21_opro.yaml --check-only
python scripts/run_experiment.py --config examples/terminal_bench21_opro.yaml
```

2.0 + Claude Code + SkillOpt 可参考 [terminal_bench.yaml](../examples/terminal_bench.yaml)。
Claude Code 的 shell / 文件工具应按示例授权。Codex 的源码模式另需容器内可用的 Rust 工具链和构建依赖，
见 [Codex 指南](codex.md)；此次 main 合入不表示已完成 Codex × Terminal 的真实验证。

`--check-only` 验证依赖、Docker 和任务初始化，不运行模型或 verifier。
运行前应确认模型协议、镜像拉取与预算。普通 `flashrsi run` 不执行一键脚本的依赖安装流程。

Harbor 负责 trial 的环境生命周期和原生评分；框架保留 Snapshot、轨迹、分数和日志。
Harbor 已收集的交付文件和原生评分日志会在临时目录清理前保存到实验的
`artifacts/harbor/trial-*/`，轨迹中记录对应路径；详细说明见[查看结果](experiment-launcher.zh-CN.md#查看结果)。
真实组合验证与历史证据见 本地记录 `smoke-matrix.md`。
