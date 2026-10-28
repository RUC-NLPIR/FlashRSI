<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI: a large white wordmark beside a blue-white ElectricLogo lightning mark on a deep black background." width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center">
  FlashRSI brings RSI algorithms, benchmarks, and native agent harnesses into one framework for developing and evaluating agent self-improvement. It supports <b>12 algorithms</b>, <b>4 benchmark adapters</b>, and <b>3 harnesses</b>—MiniAgent, Claude Code, and Codex—with experiments spanning instruction search, skill learning, and harness evolution.
</p>

<!-- TODO: add paper, project page, and discussion links; set the license before release. -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="Paper — link forthcoming"></a>
  <a href="https://github.com/ignorejjj/FlashRSI-Lite"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Code on GitHub"></a>
  <a href=""><img src="https://img.shields.io/badge/Project_Page-Live-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Project page — link forthcoming"></a>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Watch the demo"></a><br>
  <a href="docs/usage.md"><img src="https://img.shields.io/badge/Docs-Guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="Usage guide"></a>
  <a href=""><img src="https://img.shields.io/badge/Discussions-Join-5865F2?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Discussions — link forthcoming"></a>
  <a href=""><img src="https://img.shields.io/badge/License-TBD-D22128?style=for-the-badge&amp;logo=opensourceinitiative&amp;logoColor=white" alt="License — to be specified"></a>
</p>

<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="#features">Features</a> &nbsp;/&nbsp;
  <a href="#quick-start">Quick start</a> &nbsp;/&nbsp;
  <a href="#supported-algorithms">Algorithms</a> &nbsp;/&nbsp;
  <a href="#supported-benchmarks">Benchmarks</a> &nbsp;/&nbsp;
  <a href="#experimental-results">Results</a>
</p>

<a id="demo"></a>
<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="Benchmark, RSI algorithm, and harness reels settle on a combination, followed by illustrative Training, Held-out, Near-domain, and OOD-domain curves." width="100%">
</p>
<p align="center">
  <sub>Curves are illustrative. OpenHands, Pi, and Hermes are planned adapters.</sub>
</p>

## Features

- **Combine methods with native harnesses.** Select an algorithm and a compatible harness independently. MiniAgent, Claude Code, and Codex keep their native execution and resource loading.
- **Control what evolves.** Restrict edits to instructions, skills, tools, or harness code. A Snapshot keeps the complete candidate resources so local changes are evaluated in context.
- **Keep each method's search logic.** Algorithms share candidate construction, execution, and feedback while controlling their own populations, search history, and selection rules.
- **Inspect the improvement.** Separate train, dev, and test; retain resource versions, task trajectories, and available usage. Freeze a selected Snapshot for held-out evaluation or transfer experiments.

See the [usage guide](docs/usage.md) for the framework overview, harness resources, Python API, and extension interfaces.

## Quick start

### 1. Install

Use **Python 3.11+** and [uv](https://docs.astral.sh/uv/):

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ignorejjj/FlashRSI-Lite.git
cd FlashRSI-Lite
uv sync --extra miniagent --extra llm
```

### 2. Run

In [examples/quickstart.yaml](examples/quickstart.yaml), set the model and API key for **both** `agent.llm` (the target) and `algorithm.worker.llm` (the optimizer). For a custom endpoint, set each role's `base_url` as well. Then run:

```bash
uv run flashrsi run --config examples/quickstart.yaml
```

This runs **SkillOpt × MiniAgent** on a bundled 12-question QA example: one training batch, candidate selection on dev, and final evaluation on test. No dataset download is needed. Snapshots, trajectories, and results are saved under `runs/`.

<details>
<summary>Pass models and API keys from your shell</summary>

Set `TARGET_MODEL`, `WORKER_MODEL`, `TARGET_API_KEY`, and `WORKER_API_KEY` in your shell, then pass them explicitly:

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --model "$TARGET_MODEL" \
  --worker-model "$WORKER_MODEL" \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY"
```

</details>

For pip installation, preparation without model calls, different combinations, and custom experiments, see the [usage guide](docs/usage.md).

## Supported Algorithms

| Algorithm | Editable resources | Search strategy |
| --- | --- | --- |
| [OPRO](examples/opro.yaml) | Instructions | Propose instructions from scored history. |
| [GEPA](examples/gepa.yaml) | Instructions | Reflect on task feedback and select a Pareto frontier. |
| [EvoPrompt](examples/evoprompt.yaml) | Instructions | Evolve a population with GA or DE operators. |
| [ACE](docs/ace.md) | Instructions / playbook | Accumulate and curate experience through reflection. |
| [SkillOpt](examples/quickstart.yaml) | Skills | Combine batch edits with epoch-level guidance. |
| [Evo-Harness](docs/evo-harness.md) | Skills | Turn online experience into reusable skills. |
| [AHE](docs/ahe.md) | Harness resources | Retain legal edits and revise them using later diagnoses. |
| [ADAS](docs/adas.md) | Harness resources | Search an archive of designs with self-reflection. |
| [DarwinX](docs/darwinx.md) | Harness resources | Extend a population while preserving existing capabilities. |
| [Meta-Harness](docs/meta-harness.md) | Harness resources | Retrieve search history to diagnose and edit candidates. |
| [ModularRSI](docs/modular-rsi.md) | Harness resources | Evolve module branches, then integrate their changes. |
| [RRSI](docs/rrsi.md) | Harness resources | Use repeated trials, attribution, and cost-aware selection. |

These implementations adapt each method to FlashRSI's resource and evaluation interfaces. Supported combinations depend on the resources exposed by the harness; directory-editing methods require an **Agent Worker**. Method notes document the implementation choices.

## Supported Benchmarks

| Benchmark | Tasks | Scoring |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | Short-answer QA with supplied search context | Answer EM / F1 |
| [HotpotQA](examples/hotpotqa.yaml) | Multi-hop QA with supplied Wikipedia context | Answer EM / F1 |
| [Terminal-Bench 2.0](docs/terminal-bench.md) | Linux terminal tasks through Harbor | Native verifier reward |
| [τ³ Banking](examples/tau3_banking.yaml) | Multi-turn banking tasks | Native tau2 reward |

QA adapters accept local **JSON, JSONL, and Parquet** data. The quickstart bundles its own data; default full QA sources require access to the pinned Hugging Face dataset. Terminal-Bench requires Python 3.12+ and Docker. Install Harbor and tau2 in separate environments; follow the linked setup notes for environment benchmarks.

## Experimental Results

**SkillOpt on SearchQA, across two native harnesses.** The target uses `deepseek-v4-flash` and the optimizer uses `deepseek-v4-pro`. Both runs use the same 400 / 200 / 1,400 train / dev / test split, seed 42, and a budget of 4 epochs / 40 fast steps. Candidates are selected on dev; the selected Snapshot is frozen before test evaluation.

| Harness | Initial test EM | Final test EM | Gain |
| --- | ---: | ---: | ---: |
| MiniAgent | 76.43% | **82.93%** | **+6.50 pp** |
| Claude Code | 74.71% | **83.14%** | **+8.43 pp** |

<p align="center">
  <img src="experiments/skillopt-searchqa-deepseek-20260920-seed42/figures/test-em.png" alt="SkillOpt on 1,400 held-out SearchQA questions: MiniAgent test EM increases from 76.43% to 82.93%; Claude Code increases from 74.71% to 83.14%." width="100%">
</p>

These results cover a single DeepSeek transfer setting. The [experiment report](experiments/skillopt-searchqa-deepseek-20260920-seed42/report.md), [independent verification](experiments/skillopt-searchqa-deepseek-20260920-seed42/evidence/full-verification.json), and [reproduction guide](docs/searchqa-deepseek-reproduction.md) provide scores, usage, and differences from the upstream protocol.

<details id="citation">
<summary>Citation</summary>

<!-- TODO: add the report URL and publication metadata when available. -->
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
  <b>Gaoling School of Artificial Intelligence · Renmin University of China</b>
</p>
