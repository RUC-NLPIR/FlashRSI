<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI: blue-white electric arcs trace a lightning logo and the large white wordmark on a deep black background." width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>One click to reproduce any RSI algorithm with any benchmark and harness.</i></p>

<p align="center">
  FlashRSI brings together <b>12 RSI algorithms</b>, <b>30 benchmarks</b>, and <b>3 harnesses</b> (MiniAgent, Claude Code, and Codex) to reproduce, compare, and develop agent self-improvement methods.
</p>

<!-- TODO: add paper, project page, and discussion links; set the license before release. -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="Paper — link forthcoming"></a>
  <a href="https://github.com/ignorejjj/FlashRSI"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Code on GitHub"></a>
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
  <a href="#supported-harnesses">Harnesses</a> &nbsp;/&nbsp;
  <a href="#supported-benchmarks">Benchmarks</a> &nbsp;/&nbsp;
  <a href="#experimental-results">Results</a>
</p>

<a id="demo"></a>
<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="Benchmark, RSI algorithm, and harness reels settle on a combination, followed by illustrative Training, Held-out, Near-domain, and OOD-domain curves." width="100%">
</p>

## Features

- 🧩 **Mix and match.** Choose your RSI algorithm, benchmark, and harness.
- 🎯 **Control what evolves.** Improve instructions, skills, tools, or harness code.
- 📸 **Version each candidate.** Keep its resources together in a Snapshot.
- 📊 **Evaluate generalization.** Track held-out scores, task trajectories, and usage.

[Documentation →](docs/usage.md)

<p align="center">
  <a href="assets/readme/framework-overview.svg">
    <img src="assets/readme/framework-overview.png" alt="FlashRSI framework overview: 12 RSI algorithms, immutable AgentSnapshots, three agent harnesses, and 30 benchmarks." width="100%">
  </a>
</p>

## Quick start

### 1. Install

```bash
git clone https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
pip install -e .
```

### 2. Run

Run **SkillOpt × SearchQA × MiniAgent** on the 12-question QA sample included in the repository.

**Command line**

```bash
flashrsi run \
  --algorithm skillopt --benchmark searchqa --agent miniagent \
  --model gpt-5-mini --worker-model gpt-5-mini \
  --benchmark.data_path examples/data/quickstart.jsonl \
  --algorithm.num_epochs 1 --algorithm.max_steps 1
```

**[YAML](examples/quickstart.yaml)**

```bash
flashrsi run --config examples/quickstart.yaml
```

Results are saved under `runs/`. See [test scores, the selected Snapshot, and trajectories](docs/running-experiments.md#read-the-results).

## Supported Algorithms

| Algorithm (paper) | Editable resources | Example |
| --- | --- | --- |
| [OPRO](https://arxiv.org/abs/2309.03409) | Instructions | [Config](examples/opro.yaml) |
| [GEPA](https://arxiv.org/abs/2507.19457) | Instructions | [Config](examples/gepa.yaml) |
| [EvoPrompt](https://arxiv.org/abs/2309.08532) | Instructions | [Config](examples/evoprompt.yaml) |
| [ACE](https://arxiv.org/abs/2510.04618) | Instructions / playbook | [Config](examples/ace.yaml) |
| [SkillOpt](https://arxiv.org/abs/2605.23904) | Skills | [Config](examples/quickstart.yaml) |
| [Evo-Harness](https://arxiv.org/abs/2608.15071v2) | Skills | [Config](examples/evo_harness.yaml) |
| [AHE](https://arxiv.org/abs/2604.25850) | Harness resources | [Config](examples/ahe.yaml) |
| [ADAS](https://arxiv.org/abs/2408.08435) | Harness resources | [Config](examples/adas.yaml) |
| [DarwinX](https://arxiv.org/abs/2608.07545) | Harness resources | [Config](examples/darwinx.yaml) |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | Harness resources | [Config](examples/meta_harness.yaml) |
| [ModularRSI](https://arxiv.org/abs/2609.14857) | Harness resources | [Config](examples/modular_rsi.yaml) |
| [RRSI](https://arxiv.org/abs/2609.24972) | Harness resources | [Config](examples/rrsi.yaml) |

Implementations adapt each method to FlashRSI's resource and evaluation interfaces. Evo-Harness and harness-editing methods need an Agent Worker; see [method requirements](docs/running-experiments.md#choose-an-algorithm-and-harness).

## Supported Harnesses

| Harness | Editable resources | Example |
| --- | --- | --- |
| [MiniAgent](docs/usage.md#native-harnesses) | Instructions, skills, tools, runtime code, configuration | [Config](examples/quickstart.yaml) |
| [Claude Code](docs/usage.md#native-harnesses) | Instructions, skills, agents, hooks, tool servers, settings | [Config](examples/searchqa_deepseek/claude_code.yaml) |
| [Codex](docs/codex.md) | Instructions, skills, agents, hooks, plugins, memory, tools, configuration | [Config](examples/codex.yaml) |

## Supported Benchmarks

`main` includes SearchQA, HotpotQA, Terminal-Bench 2.0, and τ³ Banking. The full **28-benchmark collection** is on the [collection branch](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke), which supports MiniAgent and Claude Code. See [version and environment setup](docs/running-experiments.md#choose-a-version).

| Benchmark | Task | Metric | Get started |
| --- | --- | --- | --- |
| **Question answering** | | | |
| [SearchQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/searchqa) | Short-answer QA with search snippets | Answer EM / F1 | [Setup](docs/running-experiments.md#benchmarks-on-main) · [Config](examples/quickstart.yaml) |
| [HotpotQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/hotpotqa) | Multi-hop Wikipedia QA | Answer EM / F1; joint F1 in fullwiki mode | [Setup](docs/running-experiments.md#benchmarks-on-main) · [Config](examples/hotpotqa.yaml) |
| [MuSiQue](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/musique) | Compositional multi-hop QA | Answer EM / F1; optional support F1 | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/musique-independent-evolution.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/modular_rsi_musique.yaml) |
| [TriviaQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/triviaqa) | Trivia QA with Wikipedia context | Alias-aware EM / F1 | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/triviaqa-independent-evolution.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/modular_rsi_triviaqa.yaml) |
| [Natural Questions](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/nq) | Wikipedia QA, short-answer and yes/no subset | Local text EM / F1 | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| [2WikiMultiHopQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/twowiki_multihopqa) | Multi-hop QA with supplied context | Answer EM / F1 | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/twowiki_multihopqa_opro.yaml) |
| **Reasoning and mathematics** | | | |
| [BBEH](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard reasoning | Official per-answer accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/lightweight-benchmarks.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/bbeh_opro.yaml) |
| [SuperGPQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/supergpqa) | Graduate-level multiple-choice questions | Answer-letter accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/lightweight-benchmarks.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/supergpqa_opro.yaml) |
| [HLE](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/hle) | Humanity's Last Exam, text-only subset | Official judge accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| [MATH](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/math) | Competition mathematics | Math-Verify equivalence accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/math-independent-evolution.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/modular_rsi_math500.yaml) |
| [AIME](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/aime) | AIME 2025 / 2026 mathematics | Exact integer accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/coding-math-benchmarks.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/aime_opro.yaml) |
| [LiveMathBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/livemathbench) | Mathematics with repeated sampling | G-Pass@k / mG-Pass@k | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| **Coding** | | | |
| [CRUXEval-O](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/cruxeval_output) | Python function output prediction | Python literal equality accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/coding-math-benchmarks.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/cruxeval_output_opro.yaml) |
| [SWE-bench Verified](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/swe_bench) | Repository issue repair | Official verifier resolved rate | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/swe-independent-evolution.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/modular_rsi_swe_bench.yaml) |
| [SWE-bench Pro V2](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/swe_bench_pro) | Repository repair, all / hard sets | Official container regrade resolved rate | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| **Web research** | | | |
| [BrowseComp](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/browsecomp) | Web research | Official answer judge accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/browsecomp_serper_jina.yaml) |
| [DeepSearchQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/deepsearchqa) | Web research with single or set answers | Official autorater F1 | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/web-research-services.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/deepsearchqa_serper_jina.yaml) |
| [WideSearch](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/widesearch) | Broad web research with tabular answers | Official table score | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| **Documents and tool use** | | | |
| [OfficeQA-Pro](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/officeqa_pro) | Document research | Numeric / text answer accuracy | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/web-research-services.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/officeqa_pro_opro.yaml) |
| [Harvey LAB](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/harvey_lab) | Legal document work | Dual-judge rubric, all-criteria pass rate | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| [JobBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/jobbench) | Professional file deliverables | Official weighted rubric reward | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| [AppWorld](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/appworld) | Application and API automation | Official task-completion reward | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/appworld-independent-evolution.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/modular_rsi_appworld.yaml) |
| [BFCL V4](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/bfcl) | Multi-turn function calling, Base track | Official conversation success | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| [WorkBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/workbench) | Workplace tool use | Native database outcome correctness | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/workbench.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/workbench_opro.yaml) |
| [TravelPlanner](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/travelplanner) | Travel itineraries, sole-planning track | Final constraint pass rate | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| **Interactive environments** | | | |
| [τ²-bench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/tau2) | Airline, retail, and telecom dialogue, text mode | Mean native reward | [Setup](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/tau2-bench.md) · [Config](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/examples/tau2_opro.yaml) |
| [τ³ Banking](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/tau3_banking) | Multi-turn banking support | Native tau2 reward | [Setup](docs/running-experiments.md#benchmarks-on-main) · [Config](examples/tau3_banking.yaml) |
| [Terminal-Bench 2.0](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/terminal_bench) | Linux terminal tasks through Harbor | Native verifier reward | [Setup](docs/terminal-bench.md) · [Config](examples/terminal_bench.yaml) |

Config links open available YAML examples; entries with only Setup have no ready-made YAML. ModularRSI examples also need separate evolution data and module files; see the [run guide](docs/running-experiments.md#benchmark-collection).

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
