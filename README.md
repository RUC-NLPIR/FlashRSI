<p align="center">
  <img src="assets/readme/cover.gif" alt="FlashRSI: a large white wordmark beside a blue-white ElectricLogo lightning mark on a deep black background." width="100%">
</p>

<h1 align="center">FlashRSI: A Unified Framework for Agent Self-Improvement</h1>

<p align="center">
  FlashRSI brings RSI algorithms, benchmarks, and native agent harnesses into one framework for developing and evaluating agent self-improvement. It supports <b>12 algorithms</b> and <b>3 harnesses</b>—MiniAgent, Claude Code, and Codex—with an expanded collection of <b>28 benchmark adapters</b> on the <a href="https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke"><code>integration/flashrsi-smoke</code></a> branch.
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

- **Combine methods with native harnesses.** Select an algorithm and a compatible harness independently. MiniAgent, Claude Code, and Codex keep their native execution and resource loading.
- **Control what evolves.** Restrict edits to instructions, skills, tools, or harness code. A Snapshot keeps the complete candidate resources so local changes are evaluated in context.
- **Keep each method's search logic.** Algorithms share candidate construction, execution, and feedback while controlling their own populations, search history, and selection rules.
- **Inspect the improvement.** Separate train, dev, and test; retain resource versions, task trajectories, and available usage. Freeze a selected Snapshot for held-out evaluation or transfer experiments.

See the [usage guide](docs/usage.md) for the framework overview, harness resources, Python API, and extension interfaces.

## Quick start

### 1. Install

Use **Python 3.11+** and [uv](https://docs.astral.sh/uv/):

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ignorejjj/FlashRSI.git
cd FlashRSI
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

The **28-adapter collection** below is available on [`integration/flashrsi-smoke`](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks). `main` currently includes SearchQA, HotpotQA, Terminal-Bench 2.0, and τ³ Banking. Each benchmark links to its implementation on that branch.

| Benchmark | Tasks | Scoring |
| --- | --- | --- |
| [SearchQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/searchqa) | Short-answer QA with search snippets | Answer EM / F1 |
| [HotpotQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/hotpotqa) | Multi-hop Wikipedia QA | Answer EM / F1; joint F1 in fullwiki mode |
| [MuSiQue](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/musique) | Compositional multi-hop QA | Answer EM / F1; optional support F1 |
| [TriviaQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/triviaqa) | Trivia QA with Wikipedia context | Alias-aware EM / F1 |
| [Natural Questions](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/nq) | Wikipedia QA, short-answer and yes/no subset | Local text EM / F1 |
| [2WikiMultiHopQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/twowiki_multihopqa) | Multi-hop QA with supplied context | Answer EM / F1 |
| [BBEH](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard reasoning | Official per-answer accuracy |
| [SuperGPQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/supergpqa) | Graduate-level multiple-choice questions | Answer-letter accuracy |
| [HLE](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/hle) | Humanity's Last Exam, text-only subset | Official judge accuracy |
| [MATH](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/math) | Competition mathematics | Math-Verify equivalence accuracy |
| [AIME](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/aime) | AIME 2025 / 2026 mathematics | Exact integer accuracy |
| [LiveMathBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/livemathbench) | Mathematics with repeated sampling | G-Pass@k / mG-Pass@k |
| [CRUXEval-O](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/cruxeval_output) | Python function output prediction | Python literal equality accuracy |
| [SWE-bench Verified](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/swe_bench) | Repository issue repair | Official verifier resolved rate |
| [SWE-bench Pro V2](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/swe_bench_pro) | Repository repair, all / hard sets | Official container regrade resolved rate |
| [BrowseComp](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/browsecomp) | Web research | Official answer judge accuracy |
| [DeepSearchQA](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/deepsearchqa) | Web research with single or set answers | Official autorater F1 |
| [WideSearch](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/widesearch) | Broad web research with tabular answers | Official table score |
| [OfficeQA-Pro](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/officeqa_pro) | Document research | Numeric / text answer accuracy |
| [Harvey LAB](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/harvey_lab) | Legal document work | Dual-judge rubric, all-criteria pass rate |
| [JobBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/jobbench) | Professional file deliverables | Official weighted rubric reward |
| [AppWorld](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/appworld) | Application and API automation | Official task-completion reward |
| [BFCL V4](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/bfcl) | Multi-turn function calling, Base track | Official conversation success |
| [WorkBench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/workbench) | Workplace tool use | Native database outcome correctness |
| [TravelPlanner](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/travelplanner) | Travel itineraries, sole-planning track | Final constraint pass rate |
| [τ²-bench](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/tau2) | Airline, retail, and telecom dialogue, text mode | Mean native reward |
| [τ³ Banking](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/tau3_banking) | Multi-turn banking support | Native tau2 reward |
| [Terminal-Bench 2.0](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke/flashrsi/benchmarks/terminal_bench) | Linux terminal tasks through Harbor | Native verifier reward |

Setup depends on the benchmark: text QA and reasoning adapters use local or pinned Hugging Face data; web research may require search services and separate judge credentials; document tasks need their corpora or file tools; interactive and coding tasks use their native environments, with Docker / Harbor where required. Follow each implementation's setup notes and the branch guides for [math and code](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/coding-math-benchmarks.md), [web research](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/web-research-services.md), [τ²-bench](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/tau2-bench.md), and [Terminal-Bench](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/terminal-bench.md).

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
