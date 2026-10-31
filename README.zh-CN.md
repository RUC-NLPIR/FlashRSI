<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI 动态封面：深黑背景上，蓝白电弧沿左侧闪电和右侧大号白色字标流动。" width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>一键在不同 Agent 与任务上复现、比较和开发 RSI 方法。</i></p>

<p align="center">
  FlashRSI 集成 <b>12 种 RSI 算法</b>、<b>30 个 benchmark</b> 和 <b>3 个 harness</b>（MiniAgent、Claude Code、Codex），用于复现、比较和开发 Agent 自我改进方法。
</p>

<p align="center">
  <a href="https://arxiv.org/search/?query=FlashRSI&amp;searchtype=all"><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="Search arXiv for FlashRSI"></a>
  <a href="https://huggingface.co/datasets/RUC-NLPIR/FlashRSI"><img src="https://img.shields.io/badge/Datasets-Hugging%20Face-FF8C00?style=for-the-badge&amp;logo=huggingface&amp;logoColor=white" alt="FlashRSI datasets on Hugging Face"></a>
  <a href="https://deepwiki.com/RUC-NLPIR/FlashRSI"><img src="https://img.shields.io/badge/Ask%20DeepWiki-8B5CF6?style=for-the-badge" alt="Ask DeepWiki about FlashRSI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-D22128?style=for-the-badge&amp;logo=apache&amp;logoColor=white" alt="Apache-2.0 License"></a><br>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Watch the live demo"></a>
  <a href="https://ruc-nlpir.github.io/FlashRSI/project.html"><img src="https://img.shields.io/badge/Project_Page-Visit-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="FlashRSI project page"></a>
  <a href="https://ruc-nlpir.github.io/FlashRSI/usage.zh-CN.html"><img src="https://img.shields.io/badge/Docs-Read_the_guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="FlashRSI documentation"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="#主要特性">主要特性</a> &nbsp;/&nbsp;
  <a href="#快速开始">快速开始</a> &nbsp;/&nbsp;
  <a href="#支持的算法">支持算法</a> &nbsp;/&nbsp;
  <a href="#整体实验结果">整体实验结果</a> &nbsp;/&nbsp;
  <a href="#支持的-harnesses">Harnesses</a> &nbsp;/&nbsp;
  <a href="#支持的-benchmarks">Benchmarks</a> &nbsp;/&nbsp;
</p>

<a id="demo"></a>
<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="Benchmark、RSI 算法和 harness 三个转轮停在一组组合，随后绘制 Training、Held-out、Near-domain 和 OOD-domain 示意曲线。" width="100%">
</p>

## 主要特性

- 🧩 **可配置实验框架。** 在同一个 YAML/CLI 实验中组合 RSI 算法、Target harness、Worker、benchmark
  和各自的模型配置；资源范围与执行角色可以直接切换。
- 🧪 **30 个 Benchmark 与 12 种 RSI 方法。** 覆盖问答、推理、数学、代码、网页研究、文档、工具调用
  和交互任务，提供 **29 个套件的 34 份 Hugging Face 固定配置**，以及 OPRO、GEPA、EvoPrompt、ACE、
  SkillOpt、Evo-Harness、AHE、ADAS、DarwinX、Meta-Harness、ModularRSI、RRSI 的可运行适配。
- 🧠 **原生 Harness 与可复现证据。** 支持 MiniAgent、Claude Code 和 Codex，将 prompts、skills、工具、
  配置、hooks、plugins、memory 与 runtime 资源纳入版本化 Snapshot；每次运行集中保存候选版本、轨迹、
  指标、用量和任务产物。
- 🚀 **简单工作流与完整文档。** 使用 `flashrsi run` 演化、`flashrsi evaluate` 评估 Snapshot，配套方法
  示例、可搜索文档网站和 GitHub Pages 支持；Pi、Hermes、OpenCode 正在接入。

[使用文档 →](docs/usage.zh-CN.md)

<p align="center">
  <a href="assets/readme/framework-overview.jpg">
    <img src="assets/readme/framework-overview.jpg" alt="FlashRSI 框架概览：12 种 RSI 算法、不可变 AgentSnapshot、3 个 Agent harness 和 30 个 benchmark。" width="100%">
  </a>
</p>

## 快速开始

### 1. 安装

推荐 Linux / WSL + Python 3.12。

```bash
git clone https://github.com/RUC-NLPIR/FlashRSI.git
cd FlashRSI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[all]"
```

需要运行 Harbor 任务时，再安装 Harbor extra：

```bash
python -m pip install -e ".[all,harbor]"
```

τ²-bench 由一键实验入口按固定版本单独安装，不能和 Harbor 放在同一个环境中。

### 2. 一键运行

使用仓库自带的 12 道 QA 题目，运行 **SkillOpt × SearchQA × MiniAgent**。

**命令行**

先在 shell 中设置 `TARGET_API_KEY` 和 `WORKER_API_KEY`，分别对应 Target 和 Worker；两者互不继承。自定义端点还需分别设置各角色的 `llm.base_url`。

```bash
flashrsi run \
  --config examples/quickstart.yaml \
  --algorithm skillopt \
  --benchmark searchqa \
  --agent-harness miniagent \
  --model gpt-5-mini \
  --worker-model gpt-5-mini \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY"
```

**[YAML](examples/quickstart.yaml)**

在 [examples/quickstart.yaml](examples/quickstart.yaml) 中分别填写 `agent.llm` 和 `algorithm.worker.llm` 的模型、密钥及可选端点，再运行：

```bash
flashrsi run --config examples/quickstart.yaml
```

结果保存在 `runs/`，见[分数、Snapshot 与轨迹说明](docs/running-experiments.md#read-the-results)。自动准备环境见[一键实验指南](docs/experiment-launcher.zh-CN.md)。

## 支持的算法

FlashRSI 目前实现 12 种 RSI 方法：

| 方法 | Scope | 搜索组织 | 使用的反馈 |
| --- | --- | --- | --- |
| [OPRO](https://arxiv.org/abs/2309.03409) | 指令搜索 | 评分历史 · 反思 · 候选群体 | 训练分数、输出 |
| [GEPA](https://arxiv.org/abs/2507.19457) | 指令搜索 | 候选池与反思 | 分数、轨迹 |
| [EvoPrompt](https://arxiv.org/abs/2309.08532) | 指令搜索 | GA / DE 候选群体 | 开发集分数 |
| [SkillOpt](https://arxiv.org/abs/2605.23904) | Skill 演化 | 快速 / 慢速更新 | 训练轨迹、开发集分数 |
| [Evo-Harness](https://arxiv.org/abs/2608.15071v2) | Skill 演化 | 任务流积累 | 失败轨迹 |
| [ACE](https://arxiv.org/abs/2510.04618) | 上下文演化 | Playbook 积累 | 任务反馈、反思 |
| [AHE](https://arxiv.org/abs/2604.25850) | 迭代式 Harness 优化 | 连续编辑 | 轨迹、诊断、编辑审计 |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | 迭代式 Harness 优化 | 基于文件的历史 | 代码、分数、轨迹 |
| [RRSI](https://arxiv.org/abs/2609.24972) | 迭代式 Harness 优化 | 历史引导的修订 | 轨迹、分数、Token 成本 |
| [ADAS](https://arxiv.org/abs/2408.08435) | 归档搜索 | 设计归档 | 设计记录、开发集分数 |
| [DarwinX](https://arxiv.org/abs/2608.07545) | 分支演化 | 分支与重组 | 重复结果、轨迹 |
| [ModularRSI](https://arxiv.org/abs/2609.14857) | 分支演化 | 独立分支；集成 | 成功 / 失败轨迹 |

这些方法均适配了 FlashRSI 的资源与评估接口。Evo-Harness 和 Harness 资源编辑方法需要 Agent Worker；具体条件见[选型与运行指南](docs/running-experiments.md#choose-an-algorithm-and-harness)。

### 整体实验结果

我们在统一设置下评估这些方法：

- **演化模型：** `deepseek-v4-pro`
- **Worker 模型：** `deepseek-v4.1-flash`
- **Harness：** Claude Code 和 Mini-Agent
- **Benchmark：** 12 个 benchmark 套件

分数均为百分比；括号内表示相对对应初始 Harness 的百分点变化。

| 方法 | Harness | SearchQA | HotpotQA | Terminal-Bench 2.0 | AppWorld |
| --- | --- | ---: | ---: | ---: | ---: |
| [SkillOpt](https://arxiv.org/abs/2605.23904) | Claude Code | 83.14 (+9.21) | 60.98 (+3.66) | 70.00 (+6.67) | 84.52 (+19.64) |
| [SkillOpt](https://arxiv.org/abs/2605.23904) | Mini-Agent | 82.93 (+6.50) | 59.76 (+1.22) | 66.67 (0.00) | 91.67 (+26.19) |
| [OPRO](https://arxiv.org/abs/2309.03409) | Claude Code | 81.43 (+7.50) | 62.20 (+4.88) | 63.33 (0.00) | 66.07 (+1.19) |
| [OPRO](https://arxiv.org/abs/2309.03409) | Mini-Agent | 80.71 (+4.28) | 60.98 (+2.44) | 66.67 (0.00) | 59.52 (-5.96) |
| [AHE](https://arxiv.org/abs/2604.25850) | Claude Code | 79.36 (+5.43) | 60.98 (+3.66) | 70.00 (+6.67) | 91.67 (+26.79) |
| [AHE](https://arxiv.org/abs/2604.25850) | Mini-Agent | 78.57 (+2.14) | 57.32 (-1.22) | 60.00 (-6.67) | 71.43 (+5.95) |
| [ACE](https://arxiv.org/abs/2510.04618) | Claude Code | 83.93 (+10.00) | 63.41 (+6.09) | 66.67 (+3.34) | 91.07 (+26.19) |
| [ACE](https://arxiv.org/abs/2510.04618) | Mini-Agent | 84.71 (+8.28) | 63.41 (+4.87) | 70.00 (+3.33) | 91.67 (+26.19) |
| [EvoPrompt](https://arxiv.org/abs/2309.08532) | Claude Code | 74.07 (+0.14) | 58.54 (+1.22) | 63.33 (0.00) | 61.90 (-2.98) |
| [EvoPrompt](https://arxiv.org/abs/2309.08532) | Mini-Agent | 76.71 (+0.28) | 59.76 (+1.22) | 76.67 (+10.00) | 64.29 (-1.19) |
| [GEPA](https://arxiv.org/abs/2507.19457) | Claude Code | 82.43 (+8.50) | 62.20 (+4.88) | 66.67 (+3.34) | 67.86 (+2.98) |
| [GEPA](https://arxiv.org/abs/2507.19457) | Mini-Agent | 84.64 (+8.21) | 59.76 (+1.22) | 70.00 (+3.33) | 75.00 (+9.52) |
| [ADAS](https://arxiv.org/abs/2408.08435) | Claude Code | 81.36 (+7.43) | 60.98 (+3.66) | 73.33 (+10.00) | 89.88 (+25.00) |
| [ADAS](https://arxiv.org/abs/2408.08435) | Mini-Agent | 84.86 (+8.43) | 60.98 (+2.44) | 66.67 (0.00) | 79.76 (+14.28) |
| [DarwinX](https://arxiv.org/abs/2608.07545) | Claude Code | 80.50 (+6.57) | 60.98 (+3.66) | 63.33 (0.00) | 70.83 (+5.95) |
| [DarwinX](https://arxiv.org/abs/2608.07545) | Mini-Agent | 79.29 (+2.86) | 60.98 (+2.44) | 66.67 (0.00) | 69.05 (+3.57) |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | Claude Code | 85.07 (+11.14) | 62.20 (+4.88) | 70.00 (+6.67) | 90.48 (+25.60) |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | Mini-Agent | 79.14 (+2.71) | 59.76 (+1.22) | 73.33 (+6.66) | 88.10 (+22.62) |
| [ModularRSI](https://arxiv.org/abs/2609.14857) | Claude Code | 81.07 (+7.14) | 59.76 (+2.44) | 60.00 (-3.33) | 56.55 (-8.33) |
| [ModularRSI](https://arxiv.org/abs/2609.14857) | Mini-Agent | 78.64 (+2.21) | 59.76 (+1.22) | 70.00 (+3.33) | 69.05 (+3.57) |
| [RRSI](https://arxiv.org/abs/2609.24972) | Claude Code | 82.79 (+8.86) | 60.98 (+3.66) | 76.67 (+13.34) | 92.86 (+27.98) |
| [RRSI](https://arxiv.org/abs/2609.24972) | Mini-Agent | 81.64 (+5.21) | 59.76 (+1.22) | 76.67 (+10.00) | 84.52 (+19.04) |
| [Evo-Harness](https://arxiv.org/abs/2608.15071v2) | Claude Code | 75.36 (+1.43) | 60.98 (+3.66) | 66.67 (+3.34) | 81.55 (+16.67) |
| [Evo-Harness](https://arxiv.org/abs/2608.15071v2) | Mini-Agent | 80.64 (+4.21) | 59.76 (+1.22) | 66.67 (0.00) | 77.38 (+11.90) |

## 支持的 Harnesses

FlashRSI 当前支持三种 Harness 接入，其他接入正在规划中。

| Harness | 可编辑资源 | 接入说明 | 状态 |
| --- | --- | --- | --- |
| [MiniAgent](docs/usage.zh-CN.md#原生-harness) | 指令、skills、工具、运行代码与配置 | 原生 Python 入口，直接映射文件并使用资源角色标签。 | 可用 |
| [Claude Code](docs/agent-integration.md) | 指令、skills、子 Agent、hooks、MCP/LSP 与 settings | 映射产品公开的稳定接口，专有内部实现仍由原生 Harness 负责。 | 可用 |
| [Codex](docs/codex.md) | 指令、skills、子 Agent、hooks、插件、记忆、规则与配置 | 基于固定 Rust 基线的 Python 语义移植，在隔离进程中从 Snapshot 执行选定资源。 | 可用 |
| [Pi](docs/agent-integration.md) | 指令、skills、工具与 settings | Adapter 设计和版本映射正在进行。 | 规划中 |
| [Hermes](docs/agent-integration.md) | 指令、工具、skills 与运行时配置 | Adapter 设计和原生执行检查正在进行。 | 规划中 |
| [OpenCode](docs/agent-integration.md) | 指令、工具、插件与 settings | 资源清单和 Snapshot 绑定正在进行。 | 规划中 |

## 支持的 Benchmarks

FlashRSI 支持 **30 个 benchmark 套件**，覆盖问答、推理、数学、代码、网页研究、文档、工具使用和交互任务。下表列出各套件的任务类型和主指标。**29 个套件提供 34 份固定的 Hugging Face 配置**，同时保留原生数据源。具体数据、服务与环境要求见[配置索引](docs/benchmark-quickstart.md)。

| 领域 | Benchmark | 任务 | 主指标 |
| --- | --- | --- | --- |
| 问答 | [SearchQA](flashrsi/benchmarks/searchqa) | 提供搜索片段的短答案问答 | Exact Match |
| 问答 | [HotpotQA](flashrsi/benchmarks/hotpotqa) | Wikipedia 多跳问答 | Joint F1 |
| 问答 | [MuSiQue](flashrsi/benchmarks/musique) | 组合式多跳问答 | Answer F1 |
| 问答 | [TriviaQA](flashrsi/benchmarks/triviaqa) | 基于 Wikipedia 上下文的知识问答 | Exact Match |
| 问答 | [Natural Questions](flashrsi/benchmarks/nq) | Wikipedia 问答，短答案与 yes/no 子集 | Exact Match |
| 问答 | [2WikiMultiHopQA](flashrsi/benchmarks/twowiki_multihopqa) | 基于给定上下文的多跳问答 | Exact Match |
| 推理 | [BBEH](flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard 复杂推理 | Accuracy |
| 推理 | [SuperGPQA](flashrsi/benchmarks/supergpqa) | 研究生级别多项选择题 | Accuracy |
| 推理 | [HLE](flashrsi/benchmarks/hle) | Humanity's Last Exam，仅文本子集 | Accuracy |
| 数学 | [MATH](flashrsi/benchmarks/math) | 竞赛数学 | Accuracy |
| 数学 | [AIME](flashrsi/benchmarks/aime) | AIME 2025 / 2026 数学题 | Accuracy |
| 数学 | [LiveMathBench](flashrsi/benchmarks/livemathbench) | 多次采样的数学评测 | mG-Pass@k |
| 代码 | [SWE-bench Verified](flashrsi/benchmarks/swe_bench) | 代码仓库 issue 修复 | Resolved rate |
| 代码 | [SWE-bench Pro V2](flashrsi/benchmarks/swe_bench_pro) | 代码仓库修复，all / hard 题集 | Resolved rate |
| 代码 | [DeepSWE](flashrsi/benchmarks/deepswe) | 仓库修复，通过 Harbor 运行 DeepSWE v1.1 任务 | Reward |
| 代码 | [Terminal-Bench 2.0 / 2.1](flashrsi/benchmarks/terminal_bench) | 通过 Harbor 执行的 Linux 终端任务 | Reward |
| 网页研究 | [BrowseComp](flashrsi/benchmarks/browsecomp) | 网络信息搜索 | Accuracy |
| 网页研究 | [DeepSearchQA](flashrsi/benchmarks/deepsearchqa) | 单答案与集合答案的网络搜索 | F1 |
| 网页研究 | [WideSearch](flashrsi/benchmarks/widesearch) | 表格型广泛信息搜索 | Score |
| 文档 | [OfficeQA-Pro](flashrsi/benchmarks/officeqa_pro) | 文档检索问答 | Accuracy |
| 文档 | [Harvey LAB](flashrsi/benchmarks/harvey_lab) | 法律文档任务 | All-pass rate |
| 文档 | [JobBench](flashrsi/benchmarks/jobbench) | 专业文件交付 | Reward |
| 文档 | [SpreadsheetBench 2](flashrsi/benchmarks/spreadsheetbench2) | Debugging / Financial_Model / Template | Reward |
| 工具使用 | [AppWorld](flashrsi/benchmarks/appworld) | 应用与 API 自动化 | Reward |
| 工具使用 | [BFCL V4](flashrsi/benchmarks/bfcl) | 多轮函数调用，仅 Base track | Reward |
| 工具使用 | [WorkBench](flashrsi/benchmarks/workbench) | 工作场景工具操作 | Correctness |
| 工具使用 | [TravelPlanner](flashrsi/benchmarks/travelplanner) | 旅行行程规划，仅 sole-planning track | Final pass rate |
| 交互环境 | [τ²-bench](flashrsi/benchmarks/tau2) | 航空、零售、电信多轮对话，文本模式 | Reward |
| 交互环境 | [τ³ Banking](flashrsi/benchmarks/tau3_banking) | 多轮银行客服 | Reward |
| 交互环境 | [ALFWorld](flashrsi/benchmarks/alfworld) | 纯文本交互环境 | Success rate |

<details>
<summary><strong>常见问题</strong></summary>

### 如何添加新的 benchmark？

实现一个产出 `Task` 并评估 `Trajectory` 的 `Benchmark`（或 `NativeBenchmark`），在 `flashrsi/benchmarks/__init__.py` 中注册，添加配置示例，并记录数据来源、版本、划分策略、指标和环境要求。可参考[benchmark 配置索引](docs/benchmark-quickstart.md)和[benchmark 接口](flashrsi/core/benchmark.py)。

### 如何添加新的算法？

继承 `Algorithm`，声明可观察和可编辑的资源范围，并将提议、筛选和记忆逻辑放在 `evolve` 中。使用共享的 Snapshot checkout、rollout 和评分操作，不要把算法策略移入 runner。可从现有[算法实现](flashrsi/algorithms)和[使用指南](docs/usage.zh-CN.md#扩展-flashrsi)开始。

### 如何添加新的 Harness？

在 `components.yaml` 中声明可编辑资源，实现调用原生入口的 `Agent` adapter，并返回 `Trajectory`。对于闭源产品映射接口文件，对于大型开源系统实现最小可信运行时，对于干净的开源 Harness 直接映射带角色标签的文件。详见 [Agent integration](docs/agent-integration.md)。

### 什么是 Snapshot？

Snapshot 是实验中选定 Harness 资源的不可变、可执行版本，包含定义行为的文件以及父子关系和变更记录；凭据、任务数据、日志和其他运行时状态保存在 Snapshot 之外。Snapshot 通常保存为 `runs/<run-id>/snapshots/<snapshot-id>.json`，其文件内容使用规范化 Base64 编码，ID 是文件内容和版本元数据的 SHA-256 哈希。

</details>

<details id="citation">
<summary>引用</summary>

```bibtex
@misc{jin2026flashrsi,
  title  = {FlashRSI: A Unified Framework for Agent Self-Improvement},
  author = {Jiajie Jin and Yuze Li and Yuyang Hu and Guanting Dong and
            Xiaoxi Li and Xinyu Yang and Zhicheng Dou and Yutao Zhu},
  year   = {2026}
}
```

</details>

---

<p align="center">
  <b>中国人民大学 · 高瓴人工智能学院</b>
</p>
