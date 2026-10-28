<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI: blue-white electric arcs trace a lightning logo and the large white wordmark on a deep black background." width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center"><i>One click to reproduce any RSI algorithm with any benchmark and harness.</i></p>

<p align="center">
  FlashRSI brings together <b>12 RSI algorithms</b>, <b>30 benchmarks</b>, and <b>3 harnesses</b>—MiniAgent, Claude Code, and Codex—to reproduce, compare, and develop agent self-improvement methods.
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

## Quick start

### 1. Install

Use Linux / WSL with Python 3.12. These commands check out code and documentation, omitting `experiments/` and LFS downloads.

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --filter=blob:none --sparse https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
git sparse-checkout set flashrsi docs examples scripts tests assets
pip install -e .
```

### 2. Run

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

**YAML**

Set the model, API key and optional endpoint for both `agent.llm` and `algorithm.worker.llm` in [examples/quickstart.yaml](examples/quickstart.yaml), then run:

```bash
flashrsi run --config examples/quickstart.yaml
```

### Automatically prepare selected dependencies

Use Linux / WSL with Python 3.12. Fill both roles in [examples/quickstart_launch.yaml](examples/quickstart_launch.yaml), then run from the repository root:

```bash
python scripts/run_experiment.py --config examples/quickstart_launch.yaml --plan
python scripts/run_experiment.py --config examples/quickstart_launch.yaml --check-only
python scripts/run_experiment.py --config examples/quickstart_launch.yaml
```

The launcher creates a separate Python environment for the selected combination. This example uses the bundled 12 questions; `--check-only` validates initialization without model calls. See the [launcher guide](docs/experiment-launcher.zh-CN.md) for additional services and output records.
Use `quickstart.yaml` with direct `flashrsi run`, and `quickstart_launch.yaml` with the launcher: the two entries resolve data paths differently.

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

This integration registers **30 adapters**. See the [configuration index](docs/benchmark-quickstart.md) for examples and prerequisites, and the [smoke matrix](docs/smoke-matrix.md) for actual run coverage. Registration does not imply every combination has been validated.

| Benchmark | Tasks | Scoring |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | Short-answer QA with search snippets | Answer EM / F1 |
| [HotpotQA](flashrsi/benchmarks/hotpotqa) | Multi-hop Wikipedia QA | Answer EM / F1; joint F1 in fullwiki mode |
| [MuSiQue](flashrsi/benchmarks/musique) | Compositional multi-hop QA | Answer EM / F1; optional support F1 |
| [TriviaQA](flashrsi/benchmarks/triviaqa) | Trivia QA with Wikipedia context | Alias-aware EM / F1 |
| [Natural Questions](flashrsi/benchmarks/nq) | Wikipedia QA, short-answer and yes/no subset | Local text EM / F1 |
| [2WikiMultiHopQA](flashrsi/benchmarks/twowiki_multihopqa) | Multi-hop QA with supplied context | Answer EM / F1 |
| [BBEH](flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard reasoning | Official per-answer accuracy |
| [SuperGPQA](flashrsi/benchmarks/supergpqa) | Graduate-level multiple-choice questions | Answer-letter accuracy |
| [HLE](flashrsi/benchmarks/hle) | Humanity's Last Exam, text-only subset | Official judge accuracy |
| [MATH](flashrsi/benchmarks/math) | Competition mathematics | Math-Verify equivalence accuracy |
| [AIME](flashrsi/benchmarks/aime) | AIME 2025 / 2026 mathematics | Exact integer accuracy |
| [LiveMathBench](flashrsi/benchmarks/livemathbench) | Mathematics with repeated sampling | G-Pass@k / mG-Pass@k |
| [SWE-bench Verified](flashrsi/benchmarks/swe_bench) | Repository issue repair | Official verifier resolved rate |
| [SWE-bench Pro V2](flashrsi/benchmarks/swe_bench_pro) | Repository repair, all / hard sets | Official container regrade resolved rate |
| [BrowseComp](flashrsi/benchmarks/browsecomp) | Web research | Official answer judge accuracy |
| [DeepSearchQA](flashrsi/benchmarks/deepsearchqa) | Web research with single or set answers | Official autorater F1 |
| [WideSearch](flashrsi/benchmarks/widesearch) | Broad web research with tabular answers | Official table score |
| [OfficeQA-Pro](flashrsi/benchmarks/officeqa_pro) | Document research | Numeric / text answer accuracy |
| [Harvey LAB](flashrsi/benchmarks/harvey_lab) | Legal document work | Dual-judge rubric, all-criteria pass rate |
| [JobBench](flashrsi/benchmarks/jobbench) | Professional file deliverables | Official weighted rubric reward |
| [AppWorld](flashrsi/benchmarks/appworld) | Application and API automation | Official task-completion reward |
| [BFCL V4](flashrsi/benchmarks/bfcl) | Multi-turn function calling, Base track | Official conversation success |
| [WorkBench](flashrsi/benchmarks/workbench) | Workplace tool use | Native database outcome correctness |
| [TravelPlanner](flashrsi/benchmarks/travelplanner) | Travel itineraries, sole-planning track | Final constraint pass rate |
| [τ²-bench](flashrsi/benchmarks/tau2) | Airline, retail, and telecom dialogue, text mode | Mean native reward |
| [τ³ Banking](flashrsi/benchmarks/tau3_banking) | Multi-turn banking support | Native tau2 reward |
| [Terminal-Bench 2.0 / 2.1](flashrsi/benchmarks/terminal_bench) | Linux terminal tasks through Harbor | Native verifier reward |
| [DeepSWE](flashrsi/benchmarks/deepswe) | Repository repair via native Harbor v1.3 tasks | Independent container verifier reward |
| [SpreadsheetBench 2](flashrsi/benchmarks/spreadsheetbench2) | Debugging / Financial_Model / Template | Native LibreOffice verifier; Visualization excluded |
| [ALFWorld](flashrsi/benchmarks/alfworld) | Text-only interactive environment | Native TextWorld won / success |

Setup depends on the benchmark: text QA and reasoning adapters use local or pinned Hugging Face data; web research may require search services and separate judge credentials; document tasks need their corpora or file tools; interactive and coding tasks use their native environments, with Docker / Harbor where required. Follow each implementation's setup notes and the branch guides for [math and code](docs/coding-math-benchmarks.md), [web research](docs/web-research-services.md), [τ²-bench](docs/tau2-bench.md), and [Terminal-Bench](docs/terminal-bench.md).

## Experimental Results

These are historical results reported by upstream main. This sync neither downloads nor merges `experiments/`, and does not rerun those experiments.

**SkillOpt on SearchQA, across two native harnesses.** The target uses `deepseek-v4-flash` and the optimizer uses `deepseek-v4-pro`. Both runs use the same 400 / 200 / 1,400 train / dev / test split, seed 42, and a budget of 4 epochs / 40 fast steps. Candidates are selected on dev; the selected Snapshot is frozen before test evaluation.

| Harness | Initial test EM | Final test EM | Gain |
| --- | ---: | ---: | ---: |
| MiniAgent | 76.43% | **82.93%** | **+6.50 pp** |
| Claude Code | 74.71% | **83.14%** | **+8.43 pp** |

These results cover a single DeepSeek transfer setting. The [experiment report](https://github.com/ignorejjj/FlashRSI/blob/f66a875925bf14f05b013f33a82e59e686a9f787/experiments/skillopt-searchqa-deepseek-20260920-seed42/report.md), [independent verification](https://github.com/ignorejjj/FlashRSI/blob/f66a875925bf14f05b013f33a82e59e686a9f787/experiments/skillopt-searchqa-deepseek-20260920-seed42/evidence/full-verification.json), and [reproduction guide](docs/searchqa-deepseek-reproduction.md) provide scores, usage, and differences from the upstream protocol.

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
