<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI 动态封面：深黑背景上，左侧 ElectricLogo 蓝白闪电与右侧大号白色字标并排。" width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center">
  FlashRSI 将 RSI 算法、benchmark 和原生 Agent harness 接入同一个框架，用于开发和评测 Agent 自我改进方法。目前支持 <b>12 种算法</b>、<b>4 个 benchmark 接入</b>和 <b>3 个 harness</b>（MiniAgent、Claude Code、Codex），覆盖指令搜索、技能学习与 harness 演化。
</p>

<!-- TODO: 发布前补充论文、项目主页、讨论区链接和许可证信息。 -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="论文，链接待补充"></a>
  <a href="https://github.com/ignorejjj/FlashRSI"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="GitHub 代码仓库"></a>
  <a href=""><img src="https://img.shields.io/badge/Project_Page-Live-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="项目主页，链接待补充"></a>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="观看演示"></a><br>
  <a href="docs/usage.zh-CN.md"><img src="https://img.shields.io/badge/Docs-Guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="使用指南"></a>
  <a href=""><img src="https://img.shields.io/badge/Discussions-Join-5865F2?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="讨论区，链接待补充"></a>
  <a href=""><img src="https://img.shields.io/badge/License-TBD-D22128?style=for-the-badge&amp;logo=opensourceinitiative&amp;logoColor=white" alt="许可证，待指定"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="#主要特性">主要特性</a> &nbsp;/&nbsp;
  <a href="#快速开始">快速开始</a> &nbsp;/&nbsp;
  <a href="#支持的算法">支持算法</a> &nbsp;/&nbsp;
  <a href="#支持的-benchmarks">Benchmarks</a> &nbsp;/&nbsp;
  <a href="#实验结果">实验结果</a>
</p>

<a id="demo"></a>
<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="Benchmark、RSI 算法和 harness 三个转轮停在一组组合，随后绘制 Training、Held-out、Near-domain 和 OOD-domain 示意曲线。" width="100%">
</p>

## 主要特性

- **组合算法与原生 harness。** 独立选择算法和兼容的 harness；MiniAgent、Claude Code、Codex 保留各自的原生执行与资源加载方式。
- **控制改进范围。** 将编辑限制在指令、skills、工具或 harness 代码中。Snapshot 保留完整的候选资源，让局部修改在原有上下文中接受评估。
- **保留算法自己的搜索逻辑。** 共用候选构造、执行和反馈设施，由各方法自行组织种群、搜索历史与筛选规则。
- **查看改进效果与过程。** 分离 train、dev、test，记录资源版本、任务轨迹与可用的用量统计；冻结选中的 Snapshot，开展 held-out 评估或迁移实验。

框架机制、harness 资源、Python API 与扩展接口见[使用指南](docs/usage.zh-CN.md)。

## 快速开始

### 1. 安装

使用 **Python 3.11+** 和 [uv](https://docs.astral.sh/uv/)：

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
uv sync --extra miniagent --extra llm
```

### 2. 一键运行

在 [examples/quickstart.yaml](examples/quickstart.yaml) 中，为 `agent.llm`（解题的 Target）和 `algorithm.worker.llm`（执行改进的 Worker）**分别**填写模型与 API key。使用自定义端点时，还需分别设置 `base_url`。然后运行：

```bash
uv run flashrsi run --config examples/quickstart.yaml
```

示例采用 **SkillOpt × MiniAgent**，在附带的 12 道本地 QA 题目上执行一个训练 batch、dev 候选筛选与最终 test 评估，无需下载数据集。Snapshot、轨迹和结果保存在 `runs/` 下。

<details>
<summary>从 shell 传入模型和 API key</summary>

在 shell 中设置 `TARGET_MODEL`、`WORKER_MODEL`、`TARGET_API_KEY` 和 `WORKER_API_KEY`，再显式传入：

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --model "$TARGET_MODEL" \
  --worker-model "$WORKER_MODEL" \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY"
```

</details>

使用 pip 安装、不调用模型的实验准备、更换组合与自定义实验，见[使用指南](docs/usage.zh-CN.md)。

## 支持的算法

| 算法 | 可编辑资源 | 搜索思路 |
| --- | --- | --- |
| [OPRO](examples/opro.yaml) | 指令 | 根据带评分的历史提出新指令。 |
| [GEPA](examples/gepa.yaml) | 指令 | 结合任务反馈反思与 Pareto 筛选。 |
| [EvoPrompt](examples/evoprompt.yaml) | 指令 | 使用 GA 或 DE 算子演化种群。 |
| [ACE](docs/ace.md) | 指令 / playbook | 通过反思积累并整理经验。 |
| [SkillOpt](examples/quickstart.yaml) | Skills | 结合 batch 编辑与 epoch 级指导更新。 |
| [Evo-Harness](docs/evo-harness.md) | Skills | 将在线经验整理成可复用的技能。 |
| [AHE](docs/ahe.md) | Harness 资源 | 保留合法编辑，根据后续诊断修订。 |
| [ADAS](docs/adas.md) | Harness 资源 | 结合自我反思，搜索已评分的设计档案。 |
| [DarwinX](docs/darwinx.md) | Harness 资源 | 在扩展种群的同时保留已有能力。 |
| [Meta-Harness](docs/meta-harness.md) | Harness 资源 | 检索搜索历史，诊断并编辑候选。 |
| [ModularRSI](docs/modular-rsi.md) | Harness 资源 | 分模块演化分支，再集成修改。 |
| [RRSI](docs/rrsi.md) | Harness 资源 | 结合重复试验、归因与成本进行选择。 |

这些实现将各方法适配到 FlashRSI 的资源与评估接口。具体组合取决于 harness 暴露的资源；直接编辑目录的方法需要 **Agent Worker**。实现选择见各方法说明。

## 支持的 Benchmarks

| Benchmark | 任务 | 评分 |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | 提供搜索上下文的短答案问答 | 答案 EM / F1 |
| [HotpotQA](examples/hotpotqa.yaml) | 基于给定 Wikipedia 上下文的多跳问答 | 答案 EM / F1 |
| [Terminal-Bench 2.0](docs/terminal-bench.md) | 通过 Harbor 执行的 Linux 终端任务 | 原生 verifier reward |
| [τ³ Banking](examples/tau3_banking.yaml) | 多轮银行业务任务 | 原生 tau2 reward |

QA 接入支持本地 **JSON、JSONL 和 Parquet** 数据。快速示例自带数据，完整 QA 默认数据源需要固定版本 Hugging Face 数据集的访问权限。Terminal-Bench 需要 Python 3.12+ 与 Docker；Harbor 和 tau2 分别安装在独立环境中。环境类 benchmark 的准备步骤见对应链接。

## 实验结果

**SkillOpt 在两个原生 harness 上优化 SearchQA 表现。** 解题模型为 `deepseek-v4-flash`，改进模型为 `deepseek-v4-pro`。两侧使用相同的 400 / 200 / 1,400 train / dev / test 划分、seed 42，以及 4 epochs / 40 fast steps 的预算。候选使用 dev 筛选，冻结最终 Snapshot 后再评估 test。

| Harness | 初始 test EM | 最终 test EM | 提升 |
| --- | ---: | ---: | ---: |
| MiniAgent | 76.43% | **82.93%** | **+6.50 个百分点** |
| Claude Code | 74.71% | **83.14%** | **+8.43 个百分点** |

<p align="center">
  <img src="experiments/skillopt-searchqa-deepseek-20260920-seed42/figures/test-em.png" alt="SkillOpt 在 1,400 道独立 SearchQA 测试题上的表现：MiniAgent 的 EM 从 76.43% 提升至 82.93%，Claude Code 从 74.71% 提升至 83.14%。" width="100%">
</p>

以上结果对应这一组 DeepSeek 迁移实验。[实验报告](experiments/skillopt-searchqa-deepseek-20260920-seed42/report.md)、[独立验收记录](experiments/skillopt-searchqa-deepseek-20260920-seed42/evidence/full-verification.json)和[复现说明](docs/searchqa-deepseek-reproduction.md)提供完整分数、用量及与上游实验协议的差异。

<details id="citation">
<summary>引用</summary>

<!-- TODO: 报告发布后补充链接和出版信息。 -->
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
