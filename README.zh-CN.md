<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI 动态封面：深黑背景上，蓝白电弧沿左侧闪电和右侧大号白色字标流动。" width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>One click to reproduce any RSI algorithm with any benchmark and harness.</i></p>

<p align="center">
  FlashRSI 集成 <b>12 种 RSI 算法</b>、<b>30 个 benchmark</b> 和 <b>3 个 harness</b>（MiniAgent、Claude Code、Codex），用于复现、比较和开发 Agent 自我改进方法。
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

- 🧩 **自由组合。** 独立选择 RSI 算法、benchmark 和 harness。
- 🎯 **控制改进范围。** 演化指令、skills、工具或 harness 代码。
- 📸 **记录候选版本。** 用 Snapshot 保存完整的候选资源。
- 📊 **检验泛化效果。** 追踪独立测试分数、任务轨迹与开销。

[使用文档 →](docs/usage.zh-CN.md)

## 快速开始

### 1. 安装

推荐 Linux / WSL + Python 3.12。以下命令只展开代码和文档，跳过 `experiments/` 与 LFS 大文件。

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --filter=blob:none --sparse https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
git sparse-checkout set flashrsi docs examples scripts tests assets
pip install -e .
```

### 2. 一键运行

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

**YAML**

在 [examples/quickstart.yaml](examples/quickstart.yaml) 中分别填写 `agent.llm` 和 `algorithm.worker.llm` 的模型、密钥及可选端点，再运行：

```bash
flashrsi run --config examples/quickstart.yaml
```

### 自动配置依赖的入口

推荐 Linux / WSL + Python 3.12。填写 [examples/quickstart_launch.yaml](examples/quickstart_launch.yaml) 中两个角色的模型与密钥后，从项目根目录运行：

```bash
python scripts/run_experiment.py --config examples/quickstart_launch.yaml --plan
python scripts/run_experiment.py --config examples/quickstart_launch.yaml --check-only
python scripts/run_experiment.py --config examples/quickstart_launch.yaml
```

脚本按所选组合创建独立 Python 环境；此示例使用随源码附带的 12 道题。
`--check-only` 检查初始化，不调用模型。入口差异、额外服务和产物说明见[一键实验指南](docs/experiment-launcher.zh-CN.md)。
普通 `flashrsi run` 使用上面的 `quickstart.yaml`；一键脚本使用 `quickstart_launch.yaml`，二者的数据路径基准不同。

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

当前版本注册 **30 个适配器**。完整示例和前置条件见[配置索引](docs/benchmark-quickstart.md)，真实运行覆盖见[Smoke 验证表](docs/smoke-matrix.md)；注册不代表任意组合均已完成真实实验。

| Benchmark | 任务 | 评分 |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | 提供搜索片段的短答案问答 | 答案 EM / F1 |
| [HotpotQA](flashrsi/benchmarks/hotpotqa) | Wikipedia 多跳问答 | 答案 EM / F1；fullwiki 模式支持 joint F1 |
| [MuSiQue](flashrsi/benchmarks/musique) | 组合式多跳问答 | 答案 EM / F1；可选支撑段落 F1 |
| [TriviaQA](flashrsi/benchmarks/triviaqa) | 基于 Wikipedia 上下文的知识问答 | 支持答案别名的 EM / F1 |
| [Natural Questions](flashrsi/benchmarks/nq) | Wikipedia 问答，短答案与 yes/no 子集 | 本地文本 EM / F1 |
| [2WikiMultiHopQA](flashrsi/benchmarks/twowiki_multihopqa) | 基于给定上下文的多跳问答 | 答案 EM / F1 |
| [BBEH](flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard 复杂推理 | 官方逐题准确率 |
| [SuperGPQA](flashrsi/benchmarks/supergpqa) | 研究生级别多项选择题 | 答案字母准确率 |
| [HLE](flashrsi/benchmarks/hle) | Humanity's Last Exam，仅文本子集 | 官方 Judge 准确率 |
| [MATH](flashrsi/benchmarks/math) | 竞赛数学 | Math-Verify 等价性准确率 |
| [AIME](flashrsi/benchmarks/aime) | AIME 2025 / 2026 数学题 | 整数答案准确率 |
| [LiveMathBench](flashrsi/benchmarks/livemathbench) | 多次采样的数学评测 | G-Pass@k / mG-Pass@k |
| [SWE-bench Verified](flashrsi/benchmarks/swe_bench) | 代码仓库 issue 修复 | 官方 verifier 修复率 |
| [SWE-bench Pro V2](flashrsi/benchmarks/swe_bench_pro) | 代码仓库修复，all / hard 题集 | 官方容器复评修复率 |
| [BrowseComp](flashrsi/benchmarks/browsecomp) | 网络信息搜索 | 官方答案 Judge 准确率 |
| [DeepSearchQA](flashrsi/benchmarks/deepsearchqa) | 单答案与集合答案的网络搜索 | 官方 autorater F1 |
| [WideSearch](flashrsi/benchmarks/widesearch) | 表格型广泛信息搜索 | 官方表格评分 |
| [OfficeQA-Pro](flashrsi/benchmarks/officeqa_pro) | 文档检索问答 | 数值 / 文本答案准确率 |
| [Harvey LAB](flashrsi/benchmarks/harvey_lab) | 法律文档任务 | 双 Judge rubric 全部通过率 |
| [JobBench](flashrsi/benchmarks/jobbench) | 专业文件交付 | 官方加权 rubric reward |
| [AppWorld](flashrsi/benchmarks/appworld) | 应用与 API 自动化 | 官方任务完成 reward |
| [BFCL V4](flashrsi/benchmarks/bfcl) | 多轮函数调用，仅 Base track | 官方会话成功率 |
| [WorkBench](flashrsi/benchmarks/workbench) | 工作场景工具操作 | 原生数据库结果正确率 |
| [TravelPlanner](flashrsi/benchmarks/travelplanner) | 旅行行程规划，仅 sole-planning track | 最终约束通过率 |
| [τ²-bench](flashrsi/benchmarks/tau2) | 航空、零售、电信多轮对话，文本模式 | 原生 reward 均值 |
| [τ³ Banking](flashrsi/benchmarks/tau3_banking) | 多轮银行客服 | 原生 tau2 reward |
| [Terminal-Bench 2.0 / 2.1](flashrsi/benchmarks/terminal_bench) | 通过 Harbor 执行的 Linux 终端任务 | 原生 verifier reward |
| [DeepSWE](flashrsi/benchmarks/deepswe) | 仓库修复，原生 Harbor v1.3 任务接口 | 独立容器 verifier reward |
| [SpreadsheetBench 2](flashrsi/benchmarks/spreadsheetbench2) | Debugging / Financial_Model / Template | 原生 LibreOffice verifier；暂不含 Visualization |
| [ALFWorld](flashrsi/benchmarks/alfworld) | 纯文本交互环境 | 原生 TextWorld won / success |

环境按 benchmark 准备：文本问答与推理类使用本地数据或固定版本的 Hugging Face 数据；网络搜索类可能需要搜索服务与独立 Judge 凭据；文档类需要语料或文件工具；交互与代码任务使用各自原生环境，按需安装 Docker / Harbor。具体步骤见各实现，以及该分支的[数学与代码](docs/coding-math-benchmarks.md)、[网络搜索](docs/web-research-services.md)、[τ²-bench](docs/tau2-bench.md)和 [Terminal-Bench](docs/terminal-bench.md) 指南。

## 实验结果

以下为上游 main 的历史结果引用；本地同步未下载或合入 `experiments/`，也未重新运行这些实验。

**SkillOpt 在两个原生 harness 上优化 SearchQA 表现。** 解题模型为 `deepseek-v4-flash`，改进模型为 `deepseek-v4-pro`。两侧使用相同的 400 / 200 / 1,400 train / dev / test 划分、seed 42，以及 4 epochs / 40 fast steps 的预算。候选使用 dev 筛选，冻结最终 Snapshot 后再评估 test。

| Harness | 初始 test EM | 最终 test EM | 提升 |
| --- | ---: | ---: | ---: |
| MiniAgent | 76.43% | **82.93%** | **+6.50 个百分点** |
| Claude Code | 74.71% | **83.14%** | **+8.43 个百分点** |

以上结果对应这一组 DeepSeek 迁移实验。[实验报告](https://github.com/ignorejjj/FlashRSI/blob/f66a875925bf14f05b013f33a82e59e686a9f787/experiments/skillopt-searchqa-deepseek-20260920-seed42/report.md)、[独立验收记录](https://github.com/ignorejjj/FlashRSI/blob/f66a875925bf14f05b013f33a82e59e686a9f787/experiments/skillopt-searchqa-deepseek-20260920-seed42/evidence/full-verification.json)和[复现说明](docs/searchqa-deepseek-reproduction.md)提供完整分数、用量及与上游实验协议的差异。

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
