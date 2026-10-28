<p align="center">
  <img src="assets/readme/cover.svg" alt="FlashRSI 品牌封面：闪电与相互连接的模块化 Agent 版本。" width="100%">
</p>

<h1 align="center">FlashRSI</h1>
<h3 align="center">优化你已有的 Agent。</h3>

<p align="center">
  一个统一的 Agent 自我改进框架。<br>
  选择 benchmark、RSI 算法和 harness，开始搜索，检验改进。
</p>

<!-- TODO: 发布前补充论文、项目主页和数据集链接。 -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B84B35?style=flat-square&amp;logo=arxiv&amp;logoColor=white" alt="论文，链接待补充"></a>
  <a href=""><img src="https://img.shields.io/badge/Project-Page-273D3A?style=flat-square" alt="项目主页，链接待补充"></a>
  <a href=""><img src="https://img.shields.io/badge/Dataset-Hugging_Face-B48A31?style=flat-square&amp;logo=huggingface&amp;logoColor=white" alt="数据集，链接待补充"></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/Python-3.11%2B-366B82?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.11 及以上"></a>
</p>

<p align="center">
  <b>12</b> 种 RSI 算法 &nbsp;·&nbsp; <b>3</b> 个原生 harness &nbsp;·&nbsp; <b>4</b> 个 benchmark 接入<br>
  <sub>计划接入的 harness：OpenHands · Pi · Hermes</sub>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> &nbsp;/&nbsp;
  <a href="#演示">演示</a> &nbsp;/&nbsp;
  <a href="#工作原理">工作原理</a> &nbsp;/&nbsp;
  <a href="#支持组件">支持组件</a> &nbsp;/&nbsp;
  <a href="#扩展-flashrsi">扩展接入</a> &nbsp;/&nbsp;
  <a href="#引用">引用</a>
</p>

---

FlashRSI 将递归自我改进（RSI）方法接入已有的 Agent。你可以在同一个目标上比较指令搜索、技能学习和 harness 演化，也可以将兼容的方法用于另一个原生 harness。

每次实验都会保留 Agent 资源、搜索决策和评估证据。你可以查看具体修改、比较候选版本，再冻结选中的版本，在新任务上检验效果。

## 快速开始

### 1. 安装

在本仓库目录中，使用 **Python 3.11+** 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra miniagent --extra llm
```

<details>
<summary>使用 pip 安装</summary>

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[miniagent,llm]'
```

后续命令中的 `uv run flashrsi` 相应改为 `flashrsi`。

</details>

### 2. 准备实验

```bash
uv run flashrsi run --config examples/quickstart.yaml --prepare-only
```

这条命令会创建实验目录并保存配置，不需要 API key，也不会调用模型。

快速示例附带 **12 道本地 QA 题目**，划分为互不重叠的 train、dev 和 test，无需下载数据集即可体验流程。它用于演示框架，研究结果请使用完整 benchmark 数据集。

### 3. 运行一步改进

在 [examples/quickstart.yaml](examples/quickstart.yaml) 中，分别填写两个角色的模型和 API key。使用自定义端点时，还需填写 `base_url`。

| 角色 | 配置位置 | 职责 |
| --- | --- | --- |
| **Target** | `agent.llm` | 使用指定资源版本完成 benchmark 任务。 |
| **Worker** | `algorithm.worker.llm` | 提出改进；使用 Agent Worker 时，也可以直接编辑候选文件。 |

```bash
uv run flashrsi run --config examples/quickstart.yaml
```

示例采用 **SkillOpt × MiniAgent**，运行一个训练 batch，在 dev 上评估候选，最后测试选中的版本。Target 和 Worker 各自使用独立的模型与连接配置。

<details>
<summary>从 shell 传入凭据</summary>

配置加载器按字面读取 YAML 值。使用环境变量时，请在 shell 中展开：

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --model "$TARGET_MODEL" \
  --worker-model "$WORKER_MODEL" \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY"
```

</details>

### 4. 更换组合

所有配置字段都可以用点路径命令行参数覆盖。例如，将快速示例从技能学习改为指令搜索：

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --algorithm opro \
  --algorithm.max_steps 1 \
  --algorithm.num_candidates 2
```

使用其他 harness 或任务集时，可以从对应配置开始：

| 尝试内容 | 配置 | 额外依赖 |
| --- | --- | --- |
| Codex 同时作为 Target 和 Worker | [examples/codex.yaml](examples/codex.yaml) | `codex` |
| 多跳问答 | [examples/hotpotqa.yaml](examples/hotpotqa.yaml) | Target 和 Worker 对应的 extras |
| Terminal-Bench 2.0 | [examples/terminal_bench.yaml](examples/terminal_bench.yaml) | `harbor`、Python 3.12+、Docker |
| τ³ Banking | [examples/tau3_banking.yaml](examples/tau3_banking.yaml) | `tau2` 和上游 benchmark |

请为选中的每个角色安装相应 extras。环境类 benchmark 还需要额外准备，具体见下方接入说明。

## 演示

<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="FlashRSI：benchmark、算法和 harness 三个转轮各前进一格并停稳，随后依次绘制 Training、Held-out、Near-domain 和 OOD-domain 示意曲线。" width="100%">
</p>

Training、Held-out、Near-domain 和 OOD-domain 曲线均为示意。

## 工作原理

<p align="center">
  <img src="assets/readme/framework.svg" alt="算法编辑 Snapshot 中允许修改的组件；原生 harness 执行完整候选，benchmark 返回搜索反馈。搜索结束后，在独立 test 任务上评估选中的 Snapshot。" width="100%">
</p>

### 局部编辑，完整执行

一个 skill 的效果依赖周围的指令、工具和执行逻辑。**Snapshot** 记录 harness 声明的完整资源版本；编辑 **scope** 决定算法能读取和修改哪些部分，执行时仍保留其余资源。

原生 harness 继续负责资源加载和执行。开放源码的 harness 可以暴露运行代码；通过 CLI 或 SDK 接入的 harness 可以暴露指令、配置和扩展。凭据、依赖、任务目录和运行状态不进入资源版本。

### 共用操作，各自搜索

OPRO 使用带评分的历史，EvoPrompt 维护种群，SkillOpt 结合快速编辑与较慢的指导更新。它们共用候选构造、执行和评分设施，算法自己决定何时提出候选、如何保留搜索记忆，以及采用哪个版本。

**评估候选和激活候选是两个操作。** 候选的父版本记录资源从哪里继承；算法提出这个候选时，可以参考多个版本的证据。

### 搜索中提供反馈，搜索后检验效果

Benchmark 提供分数、逐题结果、轨迹及可用的用量统计。算法自行选择哪些证据用于反思和筛选。Harness 决定 Agent 如何执行，benchmark 决定任务如何评分。

搜索结束后，runner 在 test 划分上评估选中的 Snapshot。你也可以冻结这个版本，在另一个 benchmark 上测试迁移效果。

## 支持组件

以下清单对应当前的 **FlashRSI-Lite 实现**。具体组合取决于算法所需的资源和 benchmark 的执行环境。

### RSI 算法

| 方法 | 搜索思路 | 可编辑资源 |
| --- | --- | --- |
| [OPRO](examples/opro.yaml) | 根据带评分的历史提出新指令。 | 指令 |
| [GEPA](examples/gepa.yaml) | 结合反思与逐题 Pareto 选择。 | 指令 |
| [EvoPrompt](examples/evoprompt.yaml) | 使用 GA 或 DE 算子演化种群。 | 指令 |
| [ACE](docs/ace.md) | 通过反思和整理积累 playbook。 | 指令 / playbook |
| [SkillOpt](flashrsi/algorithms/skillopt/__init__.py) | 结合 batch 编辑与 epoch 级指导更新。 | Skills |
| [Evo-Harness](docs/evo-harness.md) | 将在线经验编译为可复用 skills。 | Skills |
| [AHE](docs/ahe.md) | 保留合法编辑，根据后续诊断修订。 | Harness 声明的资源 |
| [ADAS](docs/adas.md) | 结合自我反思，搜索已评分的设计档案。 | Harness 声明的资源 |
| [DarwinX](docs/darwinx.md) | 在扩展种群的同时保留已有能力。 | Harness 声明的资源 |
| [Meta-Harness](docs/meta-harness.md) | 检索完整搜索历史，诊断并编辑候选。 | Harness 声明的资源 |
| [ModularRSI](docs/modular-rsi.md) | 分模块演化分支，再集成修改。 | Harness 声明的资源 |
| [RRSI](docs/rrsi.md) | 结合重复试验、归因和成本进行选择。 | Harness 声明的资源 |

这些实现将各方法适配到框架的资源与评估接口。具体实现选择和验证情况见各方法说明。直接编辑目录的方法需要 **Agent Worker**；ModularRSI 还需要独立的演化任务。

### 原生 harness

| Harness | 执行方式 | 版本化资源 |
| --- | --- | --- |
| [MiniAgent](flashrsi/agents/miniagent) | 原生 Python Agent | 指令、skills、工具、配置及声明的运行代码 |
| [Claude Code](docs/agent-integration.md) | 官方 Agent SDK | 指令、skills、commands、agents、hooks、MCP/LSP 注册及 settings |
| [Codex](docs/codex.md) | 原生 `codex exec` CLI | 指令、skills、agents、hooks、MCP 服务、插件 bundle、记忆资源、规则和配置 |

**计划接入：** OpenHands、Pi、Hermes，演示中一并展示。

同一个 Agent 接口既可以作为解题的 Target，也可以作为编辑文件的 Worker。对于请求文本或结构化编辑建议的方法，还可以使用纯 **LLM Worker**。

### Benchmarks

| Benchmark | 任务 | 评分 |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | 提供搜索上下文的短答案问答 | 答案 EM / F1 |
| [HotpotQA](examples/hotpotqa.yaml) | 基于给定 Wikipedia 上下文的多跳问答 | 答案 EM / F1 |
| [Terminal-Bench 2.0](docs/terminal-bench.md) | 通过 Harbor 执行的 Linux 终端任务 | 原生 verifier reward |
| [τ³ Banking](examples/tau3_banking.yaml) | 多轮银行业务任务 | 原生 tau2 reward |

QA 接入支持本地 **JSON、JSONL 和 Parquet** 数据。默认 benchmark 数据源使用私有 Hugging Face 数据集中的固定版本，需要读取权限。使用已发布的划分时，请保留 `split: auto`，以维持原有的 held-out 划分。

Terminal-Bench 和 τ³ 各有环境要求。Harbor 与 tau2 的上游依赖存在冲突，需要安装在不同环境中。当前验证范围见对应配置和接入说明。

## Python API

自定义实验时，可以直接使用相同的组件：

```python
import asyncio

from flashrsi.agents import LLM, MiniAgent
from flashrsi.algorithms import SkillOpt
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config


async def main():
    config = load_config("examples/quickstart.yaml")
    target = MiniAgent(config.agent)
    worker = LLM(config.algorithm.worker)
    benchmark = SearchQA(config.benchmark)
    algorithm = SkillOpt(
        config.algorithm, target=target, worker=worker, benchmark=benchmark
    )

    selected = await algorithm.evolve()
    results = benchmark.grade(await target.rollout(benchmark.test, snapshot=selected))
    selected.save("snapshot.json")
    print([dict(item.metrics) for item in results])


asyncio.run(main())
```

需要自行控制流程时，用 `snapshot.check_out()` 和 `snapshot.commit()` 构造候选，调用 `target.rollout(tasks, snapshot=candidate)` 评估，再用 `target.update(candidate)` 将其选为后续运行使用的版本。

## 实验记录

每次 CLI 运行都会创建独立目录：

```text
runs/<algorithm>-<agent>-<benchmark>-<timestamp>/
├── config.yaml           # 保存的配置，凭据已脱敏
├── snapshots/            # 资源版本及其继承关系
├── trajectories/         # Target 执行、Worker 调用和搜索决策
├── result.json           # 选中的 Snapshot 和最终 test 结果
├── end-summary.json      # 供程序读取的实验摘要
└── end-summary.md        # 供人工阅读的实验摘要
```

分数和轨迹始终关联到产生它们的资源版本。Target 与 Worker 分别记录，便于同时查看解题行为和改进开销。用量统计以各原生 harness 实际提供的信息为准。

## 扩展 FlashRSI

| 接入内容 | 需要实现 | 参考入口 |
| --- | --- | --- |
| **Harness** | 声明资源组件，通过 `Agent._run` 接入原生执行。 | [Agent 接入说明](docs/agent-integration.md) |
| **RSI 方法** | 声明编辑与观察 scope，在 `Algorithm.evolve` 中组织搜索。 | [算法实现](flashrsi/algorithms) |
| **Benchmark** | 提供任务和评分；需要环境执行时，绑定执行器。 | [Benchmark 接口](flashrsi/core/benchmark.py) |

下面的小型离线示例演示资源 checkout、文件编辑、候选评估和激活：

```bash
uv run python examples/agents/native_adapters.py
```

示例使用本地子进程和明确模拟的 SDK。更详细的早期实现记录见[归档说明](docs/implementation-notes.zh-CN.md)。

<details>
<summary>开发检查与图片生成</summary>

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

封面使用[可编辑的动态 SVG](assets/readme/cover.svg) 制作，附[静态预览](assets/readme/cover.png)和[设计说明](assets/readme/cover-design.md)。演示 GIF 由 [scripts/render_readme_hero.py](scripts/render_readme_hero.py) 使用 Pillow 生成，训练和评估曲线均为示意。图片已保存在 `assets/readme/`，查看 README 无需运行渲染脚本。

</details>

## 引用

<!-- TODO: 报告发布后补充链接和出版信息。 -->
```bibtex
@misc{jin2026flashrsi,
  title  = {FlashRSI: A Unified Framework for Agent Self-Evolution},
  author = {Jiajie Jin and Yuze Li and Yuyang Hu and Guanting Dong and
            Xiaoxi Li and Xinyu Yang and Zhicheng Dou and Yutao Zhu},
  year   = {2026}
}
```

---

<p align="center">
  <b>中国人民大学 · 高瓴人工智能学院</b><br>
  研究 Agent 如何改进，以及改进在什么条件下成立。
</p>
