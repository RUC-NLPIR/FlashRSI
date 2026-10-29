<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI: blue-white electric arcs trace a lightning logo and the large white wordmark on a deep black background." width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>One click to reproduce any RSI algorithm with any benchmark and harness.</i></p>

<p align="center">
  FlashRSI brings together <b>12 RSI algorithms</b>, <b>30 benchmarks</b>, and <b>3 harnesses</b> (MiniAgent, Claude Code, and Codex) to reproduce, compare, and develop agent self-improvement methods.
</p>

<!-- TODO: add paper, project page, and discussion links. -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="Paper — link forthcoming"></a>
  <a href="https://github.com/ignorejjj/FlashRSI"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Code on GitHub"></a>
  <a href=""><img src="https://img.shields.io/badge/Project_Page-Live-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Project page — link forthcoming"></a>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Watch the demo"></a><br>
  <a href="docs/usage.md"><img src="https://img.shields.io/badge/Docs-Guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="Usage guide"></a>
  <a href=""><img src="https://img.shields.io/badge/Discussions-Join-5865F2?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Discussions — link forthcoming"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-D22128?style=for-the-badge&amp;logo=apache&amp;logoColor=white" alt="Apache-2.0 License"></a>
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

Use Linux / WSL with Python 3.12.

```bash
git clone https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### 2. Run

Run **SkillOpt × SearchQA × MiniAgent** on the bundled 12-question QA sample.

**Command line**

Set `TARGET_API_KEY` and `WORKER_API_KEY` in your shell for the two independent roles. For custom endpoints, also set each role's `llm.base_url`.

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

Set the model, API key and optional endpoint for both `agent.llm` and `algorithm.worker.llm` in [examples/quickstart.yaml](examples/quickstart.yaml), then run:

```bash
flashrsi run --config examples/quickstart.yaml
```

Results are saved under `runs/`; see [scores, Snapshots, and trajectories](docs/running-experiments.md#read-the-results). For automatic environment setup, see the [launcher guide](docs/experiment-launcher.zh-CN.md).

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

FlashRSI registers **30 benchmarks**, each with a configuration example. See the [configuration index](docs/benchmark-quickstart.md) for data, services, and environment requirements. Combinations depend on harness resources and execution capabilities; registration does not imply every combination has been validated.

| Benchmark | Task | Metric | Get started |
| --- | --- | --- | --- |
| **Question answering** | | | |
| [SearchQA](flashrsi/benchmarks/searchqa) | Short-answer QA with search snippets | Answer EM / F1 | [Setup](docs/searchqa-deepseek-reproduction.md) · [Config](examples/searchqa_skillopt.yaml) |
| [HotpotQA](flashrsi/benchmarks/hotpotqa) | Multi-hop Wikipedia QA | Answer EM / F1; joint F1 in fullwiki mode | [Setup](docs/hotpot-independent-evolution.md) · [Config](examples/hotpotqa_opro.yaml) |
| [MuSiQue](flashrsi/benchmarks/musique) | Compositional multi-hop QA | Answer EM / F1; optional support F1 | [Setup](docs/musique-independent-evolution.md) · [Config](examples/modular_rsi_musique.yaml) |
| [TriviaQA](flashrsi/benchmarks/triviaqa) | Trivia QA with Wikipedia context | Alias-aware EM / F1 | [Setup](docs/triviaqa-independent-evolution.md) · [Config](examples/modular_rsi_triviaqa.yaml) |
| [Natural Questions](flashrsi/benchmarks/nq) | Wikipedia QA, short-answer and yes/no subset | Local text EM / F1 | [Setup](docs/benchmark-quickstart.md) · [Config](examples/nq_opro.yaml) |
| [2WikiMultiHopQA](flashrsi/benchmarks/twowiki_multihopqa) | Multi-hop QA with supplied context | Answer EM / F1 | [Setup](docs/twowiki-independent-evolution.md) · [Config](examples/twowiki_multihopqa_opro.yaml) |
| **Reasoning and mathematics** | | | |
| [BBEH](flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard reasoning | Official per-answer accuracy | [Setup](docs/lightweight-benchmarks.md) · [Config](examples/bbeh_opro.yaml) |
| [SuperGPQA](flashrsi/benchmarks/supergpqa) | Graduate-level multiple-choice questions | Answer-letter accuracy | [Setup](docs/lightweight-benchmarks.md) · [Config](examples/supergpqa_opro.yaml) |
| [HLE](flashrsi/benchmarks/hle) | Humanity's Last Exam, text-only subset | Official judge accuracy | [Setup](docs/benchmark-quickstart.md) · [Config](examples/hle_opro.yaml) |
| [MATH](flashrsi/benchmarks/math) | Competition mathematics | Math-Verify equivalence accuracy | [Setup](docs/math-independent-evolution.md) · [Config](examples/modular_rsi_math500.yaml) |
| [AIME](flashrsi/benchmarks/aime) | AIME 2025 / 2026 mathematics | Exact integer accuracy | [Setup](docs/coding-math-benchmarks.md) · [Config](examples/aime_opro.yaml) |
| [LiveMathBench](flashrsi/benchmarks/livemathbench) | Mathematics with repeated sampling | G-Pass@k / mG-Pass@k | [Setup](docs/benchmark-quickstart.md) · [Config](examples/livemathbench_opro.yaml) |
| **Coding** | | | |
| [SWE-bench Verified](flashrsi/benchmarks/swe_bench) | Repository issue repair | Official verifier resolved rate | [Setup](docs/swe-independent-evolution.md) · [Config](examples/swe_bench_verified_opro.yaml) |
| [SWE-bench Pro V2](flashrsi/benchmarks/swe_bench_pro) | Repository repair, all / hard sets | Official container regrade resolved rate | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/swe_bench_pro_opro.yaml) |
| [DeepSWE](flashrsi/benchmarks/deepswe) | Repository repair via native Harbor v1.3 tasks | Independent container verifier reward | [Setup](docs/deepswe.md) · [Config](examples/deepswe_opro.yaml) |
| **Web research** | | | |
| [BrowseComp](flashrsi/benchmarks/browsecomp) | Web research | Official answer judge accuracy | [Setup](docs/web-research-services.md) · [Config](examples/browsecomp_serper_jina.yaml) |
| [DeepSearchQA](flashrsi/benchmarks/deepsearchqa) | Web research with single or set answers | Official autorater F1 | [Setup](docs/web-research-services.md) · [Config](examples/deepsearchqa_serper_jina.yaml) |
| [WideSearch](flashrsi/benchmarks/widesearch) | Broad web research with tabular answers | Official table score | [Setup](docs/web-research-services.md) · [Config](examples/widesearch_opro.yaml) |
| **Documents and tool use** | | | |
| [OfficeQA-Pro](flashrsi/benchmarks/officeqa_pro) | Document research | Numeric / text answer accuracy | [Setup](docs/web-research-services.md) · [Config](examples/officeqa_pro_opro.yaml) |
| [Harvey LAB](flashrsi/benchmarks/harvey_lab) | Legal document work | Dual-judge rubric, all-criteria pass rate | [Setup](docs/benchmark-quickstart.md) · [Config](examples/harvey_lab_opro.yaml) |
| [JobBench](flashrsi/benchmarks/jobbench) | Professional file deliverables | Official weighted rubric reward | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/jobbench_opro.yaml) |
| [SpreadsheetBench 2](flashrsi/benchmarks/spreadsheetbench2) | Debugging / Financial_Model / Template | Native LibreOffice verifier; Visualization excluded | [Setup](docs/coding-working-benchmarks.md) · [Config](examples/spreadsheetbench2_opro.yaml) |
| [AppWorld](flashrsi/benchmarks/appworld) | Application and API automation | Official task-completion reward | [Setup](docs/appworld-independent-evolution.md) · [Config](examples/modular_rsi_appworld.yaml) |
| [BFCL V4](flashrsi/benchmarks/bfcl) | Multi-turn function calling, Base track | Official conversation success | [Setup](docs/benchmark-quickstart.md) · [Config](examples/bfcl_opro.yaml) |
| [WorkBench](flashrsi/benchmarks/workbench) | Workplace tool use | Native database outcome correctness | [Setup](docs/workbench.md) · [Config](examples/workbench_opro.yaml) |
| [TravelPlanner](flashrsi/benchmarks/travelplanner) | Travel itineraries, sole-planning track | Final constraint pass rate | [Setup](docs/benchmark-quickstart.md) · [Config](examples/travelplanner_opro.yaml) |
| **Interactive environments** | | | |
| [τ²-bench](flashrsi/benchmarks/tau2) | Airline, retail, and telecom dialogue, text mode | Mean native reward | [Setup](docs/tau2-bench.md) · [Config](examples/tau2_opro.yaml) |
| [τ³ Banking](flashrsi/benchmarks/tau3_banking) | Multi-turn banking support | Native tau2 reward | [Setup](docs/benchmark-quickstart.md) · [Config](examples/tau3_banking_opro.yaml) |
| [Terminal-Bench 2.0 / 2.1](flashrsi/benchmarks/terminal_bench) | Linux terminal tasks through Harbor | Native verifier reward | [Setup](docs/terminal-bench.md) · [Config](examples/terminal_bench21_opro.yaml) |
| [ALFWorld](flashrsi/benchmarks/alfworld) | Text-only interactive environment | Native TextWorld won / success | [Setup](docs/alfworld.md) · [Config](examples/alfworld_opro.yaml) |

Examples use different algorithms. Methods such as ModularRSI also need matching module and data settings; see the [run guide](docs/running-experiments.md).

<details id="citation">
<summary>Citation</summary>

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
