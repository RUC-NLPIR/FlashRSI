<p align="center">
  <img src="assets/readme/cover.svg" alt="FlashRSI: a white wordmark beside three branching paths that converge, on a plain dark background." width="100%">
</p>

<h1 align="center">FlashRSI</h1>
<h3 align="center">Improve the agent you already have.</h3>

<p align="center">
  A unified framework for agent self-improvement.<br>
  Choose a benchmark, an RSI algorithm, and a harness. Run the search. Measure what changed.
</p>

<!-- TODO: add paper, project page, and discussion links; set the license before release. -->
<p align="center">
  <a href=""><img src="https://img.shields.io/badge/Paper-arXiv-B31B1B?style=for-the-badge&amp;logo=arxiv&amp;logoColor=white" alt="Paper — link forthcoming"></a>
  <a href="https://github.com/ignorejjj/FlashRSI-Lite"><img src="https://img.shields.io/badge/Code-GitHub-181717?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Code on GitHub"></a>
  <a href=""><img src="https://img.shields.io/badge/Project_Page-Live-0E9B9B?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Project page — link forthcoming"></a>
  <a href="#demo"><img src="https://img.shields.io/badge/Live_Demo-Watch-FF5C8A?style=for-the-badge&amp;logo=githubpages&amp;logoColor=white" alt="Watch the demo"></a><br>
  <a href="docs/"><img src="https://img.shields.io/badge/Docs-Guide-526CFE?style=for-the-badge&amp;logo=readthedocs&amp;logoColor=white" alt="Documentation"></a>
  <a href=""><img src="https://img.shields.io/badge/Discussions-Join-5865F2?style=for-the-badge&amp;logo=github&amp;logoColor=white" alt="Discussions — link forthcoming"></a>
  <a href=""><img src="https://img.shields.io/badge/License-TBD-D22128?style=for-the-badge&amp;logo=opensourceinitiative&amp;logoColor=white" alt="License — to be specified"></a>
</p>

<p align="center">
  <b>12</b> RSI algorithms &nbsp;·&nbsp; <b>3</b> native harnesses &nbsp;·&nbsp; <b>4</b> benchmark adapters<br>
  <sub>Planned harness adapters: OpenHands · Pi · Hermes</sub>
</p>

<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="#demo">Demo</a> &nbsp;/&nbsp;
  <a href="#quick-start">Quick start</a> &nbsp;/&nbsp;
  <a href="#how-it-works">How it works</a> &nbsp;/&nbsp;
  <a href="#supported-components">Supported components</a> &nbsp;/&nbsp;
  <a href="#extend-flashrsi">Extend</a> &nbsp;/&nbsp;
  <a href="#citation">Citation</a>
</p>

---

FlashRSI brings recursive self-improvement (RSI) methods to existing agents. Use it to compare instruction search, skill learning, and harness evolution on the same target, or reuse a compatible method with another native harness.

Each experiment keeps the agent resources, search decisions, and evaluation evidence together. You can inspect the changes, compare candidates, and freeze a selected version for assessment on new tasks.

## Demo

<p align="center">
  <img src="assets/readme/slot-machine.gif" alt="FlashRSI: benchmark, algorithm, and harness reels advance one step and settle, then illustrative Training, Held-out, Near-domain, and OOD-domain curves appear below." width="100%">
</p>

Training, Held-out, Near-domain, and OOD-domain curves are illustrative.

## Quick start

### 1. Install

From this repository, with **Python 3.11+** and [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra miniagent --extra llm
```

<details>
<summary>Use pip instead</summary>

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[miniagent,llm]'
```

Use `flashrsi` in place of `uv run flashrsi` in the commands below.

</details>

### 2. Prepare an experiment

```bash
uv run flashrsi run --config examples/quickstart.yaml --prepare-only
```

This creates an experiment directory and saves its configuration. It needs no API key and makes no model requests.

The quickstart includes a **12-question local QA example** with separate train, dev, and test splits. It demonstrates the workflow without a dataset download; use the full benchmark datasets for research results.

### 3. Run one improvement step

In [examples/quickstart.yaml](examples/quickstart.yaml), set the model and API key for both roles. Set `base_url` when using a custom endpoint.

| Role | Configuration | Responsibility |
| --- | --- | --- |
| **Target** | `agent.llm` | Solve benchmark tasks with the selected resource version. |
| **Worker** | `algorithm.worker.llm` | Propose improvements, or edit candidate files when using an Agent Worker. |

```bash
uv run flashrsi run --config examples/quickstart.yaml
```

This example runs **SkillOpt × MiniAgent** for one training batch, evaluates the candidate on dev, and tests the selected version. Target and Worker have independent model and connection settings.

<details>
<summary>Pass credentials from your shell</summary>

The configuration loader reads literal YAML values. To use environment variables, expand them in your shell:

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --model "$TARGET_MODEL" \
  --worker-model "$WORKER_MODEL" \
  --agent.llm.api_key "$TARGET_API_KEY" \
  --algorithm.worker.llm.api_key "$WORKER_API_KEY"
```

</details>

### 4. Change the combination

Every configuration field accepts a dotted CLI override. For example, switch the quickstart from skill learning to instruction search:

```bash
uv run flashrsi run --config examples/quickstart.yaml \
  --algorithm opro \
  --algorithm.max_steps 1 \
  --algorithm.num_candidates 2
```

For another harness or task suite, start with a matching configuration:

| Try | Configuration | Extra dependency |
| --- | --- | --- |
| Codex as target and Worker | [examples/codex.yaml](examples/codex.yaml) | `codex` |
| Multi-hop question answering | [examples/hotpotqa.yaml](examples/hotpotqa.yaml) | Target and Worker extras |
| Terminal-Bench 2.0 | [examples/terminal_bench.yaml](examples/terminal_bench.yaml) | `harbor`, Python 3.12+, Docker |
| τ³ Banking | [examples/tau3_banking.yaml](examples/tau3_banking.yaml) | `tau2` and the upstream benchmark |

Install the extras for each selected role. Environment benchmarks have additional setup; follow their integration notes below.

## How it works

<p align="center">
  <img src="assets/readme/framework.svg" alt="An algorithm edits selected Snapshot components. The native harness executes the complete candidate; the benchmark returns search feedback. After search, the selected Snapshot is evaluated on held-out test tasks." width="100%">
</p>

### Scoped edits, complete candidates

A skill's effect depends on the instructions, tools, and execution logic around it. A **Snapshot** records a complete version of the resources declared by the harness. The editing **scope** controls what an algorithm may read and change; execution retains the surrounding resources.

Native harnesses keep their own resource loading and execution rules. An open harness can expose runtime code; a CLI or SDK harness can expose instructions, configuration, and extensions. Credentials, dependencies, task directories, and runtime state stay outside the resource version.

### Shared operations, independent search

OPRO uses a scored history. EvoPrompt maintains a population. SkillOpt combines fast edits with slower guidance updates. They share candidate construction, execution, and scoring facilities, while each algorithm controls its proposal schedule, search memory, and adoption rules.

**Evaluating a candidate and activating it are separate operations.** A candidate's parent records where its resources came from; the algorithm can use evidence from many versions to propose it.

### Feedback during search, assessment after search

Benchmarks supply scores, task outcomes, trajectories, and available usage. Algorithms choose which evidence to use for reflection and selection. The harness determines how an agent runs; the benchmark determines how its work is graded.

When search ends, the runner evaluates the selected Snapshot on the test split. You can also freeze that Snapshot and evaluate it on another benchmark to measure transfer.

## Supported components

The lists below describe the current **FlashRSI-Lite implementation**. Combinations depend on the method's resource requirements and the benchmark's execution environment.

### RSI algorithms

| Method | Search idea | Editable resources |
| --- | --- | --- |
| [OPRO](examples/opro.yaml) | Propose instructions from scored history. | Instructions |
| [GEPA](examples/gepa.yaml) | Use reflection and task-level Pareto selection. | Instructions |
| [EvoPrompt](examples/evoprompt.yaml) | Evolve a population with GA or DE operators. | Instructions |
| [ACE](docs/ace.md) | Accumulate a playbook through reflection and curation. | Instructions / playbook |
| [SkillOpt](flashrsi/algorithms/skillopt/__init__.py) | Combine batch edits with epoch-level guidance. | Skills |
| [Evo-Harness](docs/evo-harness.md) | Compile online experience into reusable skills. | Skills |
| [AHE](docs/ahe.md) | Retain legal edits and revise them using later diagnoses. | Declared harness resources |
| [ADAS](docs/adas.md) | Search an archive of designs with self-reflection. | Declared harness resources |
| [DarwinX](docs/darwinx.md) | Preserve existing capabilities while extending a population. | Declared harness resources |
| [Meta-Harness](docs/meta-harness.md) | Retrieve full search history to diagnose and edit candidates. | Declared harness resources |
| [ModularRSI](docs/modular-rsi.md) | Evolve module branches, then integrate their changes. | Declared harness resources |
| [RRSI](docs/rrsi.md) | Use repeated trials, attribution, and cost-aware selection. | Declared harness resources |

These are adaptations to the framework's resource and evaluation interfaces. Method notes describe implementation choices and validation. Methods that edit directories require an **Agent Worker**; ModularRSI also requires independent evolution tasks.

### Native harnesses

| Harness | Execution | Versioned resources |
| --- | --- | --- |
| [MiniAgent](flashrsi/agents/miniagent) | Native Python agent | Instructions, skills, tools, configuration, and declared runtime code |
| [Claude Code](docs/agent-integration.md) | Official Agent SDK | Instructions, skills, commands, agents, hooks, MCP/LSP registrations, and settings |
| [Codex](docs/codex.md) | Native `codex exec` CLI | Instructions, skills, agents, hooks, MCP servers, plugin bundles, memory resources, rules, and configuration |

**Planned adapters:** OpenHands, Pi, and Hermes, also previewed in the demo.

The same Agent interface supports a target that solves tasks and a Worker that edits files. A plain **LLM Worker** is also available for methods that request text or structured edit proposals.

### Benchmarks

| Benchmark | Tasks | Evaluation |
| --- | --- | --- |
| [SearchQA](flashrsi/benchmarks/searchqa) | Short-answer QA with supplied search context | Answer EM / F1 |
| [HotpotQA](examples/hotpotqa.yaml) | Multi-hop QA with supplied Wikipedia context | Answer EM / F1 |
| [Terminal-Bench 2.0](docs/terminal-bench.md) | Linux terminal tasks through Harbor | Native verifier reward |
| [τ³ Banking](examples/tau3_banking.yaml) | Multi-turn banking tasks | Native tau2 reward |

QA adapters accept local **JSON, JSONL, and Parquet** data. Default benchmark sources use pinned revisions in a private Hugging Face dataset and require access. Keep `split: auto` when using published splits to preserve their held-out partitions.

Terminal-Bench and τ³ have separate environment requirements. Install Harbor and tau2 in separate environments because their upstream dependencies conflict. See the linked configurations and integration notes for current validation coverage.

## Python API

Use the same components directly when building a custom experiment:

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

For lower-level control, `snapshot.check_out()` and `snapshot.commit()` construct a candidate; `target.rollout(tasks, snapshot=candidate)` evaluates it, and `target.update(candidate)` selects it for subsequent runs.

## Experiment records

Each CLI run creates its own directory:

```text
runs/<algorithm>-<agent>-<benchmark>-<timestamp>/
├── config.yaml           # Saved configuration; credentials redacted
├── snapshots/            # Resource versions and their lineage
├── trajectories/         # Target runs, Worker calls, and search decisions
├── result.json           # Selected Snapshot and final test result
├── end-summary.json      # Machine-readable experiment summary
└── end-summary.md        # Human-readable experiment summary
```

Scores and trajectories stay associated with the version that produced them. Target and Worker calls are recorded separately, so you can inspect both task behavior and the work spent improving it. Usage follows the accounting exposed by each native harness.

## Extend FlashRSI

| Add your own… | Implement | Start here |
| --- | --- | --- |
| **Harness** | Declare resource components and implement native execution as `Agent._run`. | [Agent integration guide](docs/agent-integration.md) |
| **RSI method** | Declare editing / observation scopes and organize search in `Algorithm.evolve`. | [Algorithm implementations](flashrsi/algorithms) |
| **Benchmark** | Supply tasks and grading; bind an environment executor where needed. | [Benchmark interface](flashrsi/core/benchmark.py) |

A small offline example demonstrates resource checkout, file editing, candidate evaluation, and activation:

```bash
uv run python examples/agents/native_adapters.py
```

It uses a local subprocess and an explicitly simulated SDK. For detailed earlier implementation records, see the [archived notes](docs/implementation-notes.zh-CN.md).

<details>
<summary>Development checks and image generation</summary>

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The minimal cover is an [editable SVG](assets/readme/cover.svg), generated by [scripts/render_readme_cover.py](scripts/render_readme_cover.py), with a [PNG preview](assets/readme/cover.png) and [design notes](assets/readme/cover-design.md). The demo GIF is generated from [scripts/render_readme_hero.py](scripts/render_readme_hero.py) using Pillow. Its training and evaluation curves are schematic. Images are checked into `assets/readme/`, so viewing the README needs no renderer.

</details>

## Citation

<!-- TODO: add the report URL and publication metadata when available. -->
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
  <b>Gaoling School of Artificial Intelligence · Renmin University of China</b><br>
  Built for studying how agents improve, and when those improvements hold up.
</p>
