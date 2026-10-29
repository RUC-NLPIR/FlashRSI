<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI 动态封面：深黑背景上，蓝白电弧沿左侧闪电和右侧大号白色字标流动。" width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>One click to reproduce any RSI algorithm with any benchmark and harness.</i></p>

<p align="center">
  FlashRSI 集成 <b>12 种 RSI 算法</b>、<b>30 个 benchmark</b> 和 <b>3 个 harness</b>（MiniAgent、Claude Code、Codex），用于复现、比较和开发 Agent 自我改进方法。
</p>

<!-- TODO: 发布前补充论文、项目主页和讨论区链接。 -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="论文，链接待补充"></a>
  <a href="https://github.com/ignorejjj/FlashRSI"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="GitHub 代码仓库"></a>
  <a href=""><img src="https://img.shields.io/badge/Project_Page-Live-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="项目主页，链接待补充"></a>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="观看演示"></a><br>
  <a href="docs/usage.zh-CN.md"><img src="https://img.shields.io/badge/Docs-Guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="使用指南"></a>
  <a href=""><img src="https://img.shields.io/badge/Discussions-Join-5865F2?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="讨论区，链接待补充"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-D22128?style=for-the-badge&amp;logo=apache&amp;logoColor=white" alt="Apache-2.0 许可证"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="#主要特性">主要特性</a> &nbsp;/&nbsp;
  <a href="#快速开始">快速开始</a> &nbsp;/&nbsp;
  <a href="#支持的算法">支持算法</a> &nbsp;/&nbsp;
  <a href="#支持的-harnesses">Harnesses</a> &nbsp;/&nbsp;
  <a href="#支持的-benchmarks">Benchmarks</a> &nbsp;/&nbsp;
</p>

<a id="demo"></a>
<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="Benchmark、RSI 算法和 harness 三个转轮停在一组组合，随后绘制 Training、Held-out、Near-domain 和 OOD-domain 示意曲线。" width="100%">
</p>

## 主要特性

- 🧩 **自由组合。** 独立选择 RSI 算法、benchmark 和 harness。
- 🎯 **控制改进范围。** 演化指令、skills、工具或 harness 代码。
- 📸 **记录候选版本。** 用 Snapshot 保存完整的候选资源。
- 📊 **检验泛化效果。** 追踪独立测试分数、任务轨迹与开销。

[使用文档 →](docs/usage.zh-CN.md)

<p align="center">
  <a href="assets/readme/framework-overview.svg">
    <img src="assets/readme/framework-overview.png" alt="FlashRSI 框架概览：12 种 RSI 算法、不可变 AgentSnapshot、3 个 Agent harness 和 30 个 benchmark。" width="100%">
  </a>
</p>

## 快速开始

### 1. 安装

推荐 Linux / WSL + Python 3.12。

```bash
git clone https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### 2. 一键运行

使用仓库自带的 12 道 QA 题目，运行 **SkillOpt × SearchQA × MiniAgent**。

**命令行**

先在 shell 中设置 `TARGET_API_KEY` 和 `WORKER_API_KEY`，分别对应 Target 和 Worker；两者互不继承。自定义端点还需分别设置各角色的 `llm.base_url`。

```bash
flashrsi run \
  --algorithm skillopt --benchmark searchqa --agent miniagent \
  --model gpt-5-mini --worker-model gpt-5-mini \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY" \
  --benchmark.data_path examples/data/quickstart.jsonl \
  --benchmark.split '{train: 0.5, dev: 0.25, test: 0.25}' \
  --algorithm.num_epochs 1 --algorithm.max_steps 1
```

**[YAML](examples/quickstart.yaml)**

在 [examples/quickstart.yaml](examples/quickstart.yaml) 中分别填写 `agent.llm` 和 `algorithm.worker.llm` 的模型、密钥及可选端点，再运行：

```bash
flashrsi run --config examples/quickstart.yaml
```

结果保存在 `runs/`，见[分数、Snapshot 与轨迹说明](docs/running-experiments.md#read-the-results)。自动准备环境见[一键实验指南](docs/experiment-launcher.zh-CN.md)。

## 支持的算法

| 算法（论文） | 可编辑资源 | 示例 |
| --- | --- | --- |
| [OPRO](https://arxiv.org/abs/2309.03409) | 指令 | [Config](examples/opro.yaml) |
| [GEPA](https://arxiv.org/abs/2507.19457) | 指令 | [Config](examples/gepa.yaml) |
| [EvoPrompt](https://arxiv.org/abs/2309.08532) | 指令 | [Config](examples/evoprompt.yaml) |
| [ACE](https://arxiv.org/abs/2510.04618) | 指令 / playbook | [Config](examples/ace.yaml) |
| [SkillOpt](https://arxiv.org/abs/2605.23904) | Skills | [Config](examples/quickstart.yaml) |
| [Evo-Harness](https://arxiv.org/abs/2608.15071v2) | Skills | [Config](examples/evo_harness.yaml) |
| [AHE](https://arxiv.org/abs/2604.25850) | Harness 资源 | [Config](examples/ahe.yaml) |
| [ADAS](https://arxiv.org/abs/2408.08435) | Harness 资源 | [Config](examples/adas.yaml) |
| [DarwinX](https://arxiv.org/abs/2608.07545) | Harness 资源 | [Config](examples/darwinx.yaml) |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | Harness 资源 | [Config](examples/meta_harness.yaml) |
| [ModularRSI](https://arxiv.org/abs/2609.14857) | Harness 资源 | [Config](examples/modular_rsi.yaml) |
| [RRSI](https://arxiv.org/abs/2609.24972) | Harness 资源 | [Config](examples/rrsi.yaml) |

实现适配到 FlashRSI 的资源与评估接口。Evo-Harness 和 harness 资源编辑方法需要 Agent Worker；具体条件见[选型与运行指南](docs/running-experiments.md#choose-an-algorithm-and-harness)。

## 支持的 Harnesses

| Harness | 可编辑资源 | 示例 |
| --- | --- | --- |
| [MiniAgent](docs/usage.zh-CN.md#原生-harness) | 指令、skills、工具、运行代码与配置 | [Config](examples/quickstart.yaml) |
| [Claude Code](docs/usage.zh-CN.md#原生-harness) | 指令、skills、子 Agent、hooks、工具服务与 settings | [Config](examples/searchqa_deepseek/claude_code.yaml) |
| [Codex](docs/codex.md) | 指令、skills、子 Agent、hooks、插件、记忆、工具与配置 | [Config](examples/codex.yaml) |

## 支持的 Benchmarks

当前注册 **30 个 benchmark**。每项均提供配置示例；数据、服务与环境要求见[配置索引](docs/benchmark-quickstart.md)。组合需满足 harness 的资源与执行能力要求，注册不代表所有组合均已完成真实验证。

| Benchmark | 任务 | 评分 | 运行入口 |
| --- | --- | --- | --- |
| **问答** | | | |
| [SearchQA](flashrsi/benchmarks/searchqa) | 提供搜索片段的短答案问答 | 答案 EM / F1 | [Setup](docs/searchqa-deepseek-reproduction.md) · [Config](examples/searchqa_skillopt.yaml) |
| [HotpotQA](flashrsi/benchmarks/hotpotqa) | Wikipedia 多跳问答 | 答案 EM / F1；fullwiki 模式支持 joint F1 | [Setup](docs/hotpot-independent-evolution.md) · [Config](examples/hotpotqa_opro.yaml) |
| [MuSiQue](flashrsi/benchmarks/musique) | 组合式多跳问答 | 答案 EM / F1；可选支撑段落 F1 | [Setup](docs/musique-independent-evolution.md) · [Config](examples/modular_rsi_musique.yaml) |
| [TriviaQA](flashrsi/benchmarks/triviaqa) | 基于 Wikipedia 上下文的知识问答 | 支持答案别名的 EM / F1 | [Setup](docs/triviaqa-independent-evolution.md) · [Config](examples/modular_rsi_triviaqa.yaml) |
| [Natural Questions](flashrsi/benchmarks/nq) | Wikipedia 问答，短答案与 yes/no 子集 | 本地文本 EM / F1 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/nq_opro.yaml) |
| [2WikiMultiHopQA](flashrsi/benchmarks/twowiki_multihopqa) | 基于给定上下文的多跳问答 | 答案 EM / F1 | [Setup](docs/twowiki-independent-evolution.md) · [Config](examples/twowiki_multihopqa_opro.yaml) |
| **推理与数学** | | | |
| [BBEH](flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard 复杂推理 | 官方逐题准确率 | [Setup](docs/lightweight-benchmarks.md) · [Config](examples/bbeh_opro.yaml) |
| [SuperGPQA](flashrsi/benchmarks/supergpqa) | 研究生级别多项选择题 | 答案字母准确率 | [Setup](docs/lightweight-benchmarks.md) · [Config](examples/supergpqa_opro.yaml) |
| [HLE](flashrsi/benchmarks/hle) | Humanity's Last Exam，仅文本子集 | 官方 Judge 准确率 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/hle_opro.yaml) |
| [MATH](flashrsi/benchmarks/math) | 竞赛数学 | Math-Verify 等价性准确率 | [Setup](docs/math-independent-evolution.md) · [Config](examples/modular_rsi_math500.yaml) |
| [AIME](flashrsi/benchmarks/aime) | AIME 2025 / 2026 数学题 | 整数答案准确率 | [Setup](docs/coding-math-benchmarks.md) · [Config](examples/aime_opro.yaml) |
| [LiveMathBench](flashrsi/benchmarks/livemathbench) | 多次采样的数学评测 | G-Pass@k / mG-Pass@k | [Setup](docs/benchmark-quickstart.md) · [Config](examples/livemathbench_opro.yaml) |
| **代码** | | | |
| [SWE-bench Verified](flashrsi/benchmarks/swe_bench) | 代码仓库 issue 修复 | 官方 verifier 修复率 | [Setup](docs/swe-independent-evolution.md) · [Config](examples/swe_bench_verified_opro.yaml) |
| [SWE-bench Pro V2](flashrsi/benchmarks/swe_bench_pro) | 代码仓库修复，all / hard 题集 | 官方容器复评修复率 | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/swe_bench_pro_opro.yaml) |
| [DeepSWE](flashrsi/benchmarks/deepswe) | 仓库修复，原生 Harbor v1.3 任务接口 | 独立容器 verifier reward | [Setup](docs/deepswe.md) · [Config](examples/deepswe_opro.yaml) |
| **网页研究** | | | |
| [BrowseComp](flashrsi/benchmarks/browsecomp) | 网络信息搜索 | 官方答案 Judge 准确率 | [Setup](docs/web-research-services.md) · [Config](examples/browsecomp_serper_jina.yaml) |
| [DeepSearchQA](flashrsi/benchmarks/deepsearchqa) | 单答案与集合答案的网络搜索 | 官方 autorater F1 | [Setup](docs/web-research-services.md) · [Config](examples/deepsearchqa_serper_jina.yaml) |
| [WideSearch](flashrsi/benchmarks/widesearch) | 表格型广泛信息搜索 | 官方表格评分 | [Setup](docs/web-research-services.md) · [Config](examples/widesearch_opro.yaml) |
| **文档与工具使用** | | | |
| [OfficeQA-Pro](flashrsi/benchmarks/officeqa_pro) | 文档检索问答 | 数值 / 文本答案准确率 | [Setup](docs/web-research-services.md) · [Config](examples/officeqa_pro_opro.yaml) |
| [Harvey LAB](flashrsi/benchmarks/harvey_lab) | 法律文档任务 | 双 Judge rubric 全部通过率 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/harvey_lab_opro.yaml) |
| [JobBench](flashrsi/benchmarks/jobbench) | 专业文件交付 | 官方加权 rubric reward | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/jobbench_opro.yaml) |
| [SpreadsheetBench 2](flashrsi/benchmarks/spreadsheetbench2) | Debugging / Financial_Model / Template | 原生 LibreOffice verifier；暂不含 Visualization | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/spreadsheetbench2_opro.yaml) |
| [AppWorld](flashrsi/benchmarks/appworld) | 应用与 API 自动化 | 官方任务完成 reward | [Setup](docs/appworld-independent-evolution.md) · [Config](examples/modular_rsi_appworld.yaml) |
| [BFCL V4](flashrsi/benchmarks/bfcl) | 多轮函数调用，仅 Base track | 官方会话成功率 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/bfcl_opro.yaml) |
| [WorkBench](flashrsi/benchmarks/workbench) | 工作场景工具操作 | 原生数据库结果正确率 | [Setup](docs/workbench.md) · [Config](examples/workbench_opro.yaml) |
| [TravelPlanner](flashrsi/benchmarks/travelplanner) | 旅行行程规划，仅 sole-planning track | 最终约束通过率 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/travelplanner_opro.yaml) |
| **交互环境** | | | |
| [τ²-bench](flashrsi/benchmarks/tau2) | 航空、零售、电信多轮对话，文本模式 | 原生 reward 均值 | [Setup](docs/tau2-bench.md) · [Config](examples/tau2_opro.yaml) |
| [τ³ Banking](flashrsi/benchmarks/tau3_banking) | 多轮银行客服 | 原生 tau2 reward | [Setup](docs/benchmark-quickstart.md) · [Config](examples/tau3_banking_opro.yaml) |
| [Terminal-Bench 2.0 / 2.1](flashrsi/benchmarks/terminal_bench) | 通过 Harbor 执行的 Linux 终端任务 | 原生 verifier reward | [Setup](docs/terminal-bench.md) · [Config](examples/terminal_bench21_opro.yaml) |
| [ALFWorld](flashrsi/benchmarks/alfworld) | 纯文本交互环境 | 原生 TextWorld won / success | [Setup](docs/alfworld.md) · [Config](examples/alfworld_opro.yaml) |

示例使用不同算法；ModularRSI 等方法还需准备相应模块与数据配置，见[选型与运行指南](docs/running-experiments.md)。

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
