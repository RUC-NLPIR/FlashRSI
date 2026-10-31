---
title: Quickstart
description: Run a small, reproducible agent self-improvement experiment with FlashRSI.
prev: false
next:
  text: Installation
  link: /guide/installation
---

<!-- Direction A approved by the user. This is a task guide, with real local
     sample data and independent Target/Worker credentials, not a benchmark result. -->
<div class="quickstart-intro">
  <p class="intro-context">Guide / Quickstart</p>
  <h1>Run a first self-improvement experiment</h1>
  <p class="intro-lead">Give an RSI method a defined editing scope. Run each candidate through a native harness and keep the evidence behind the score.</p>
  <div class="intro-actions">
    <a href="#run-the-experiment">Run the quickstart</a>
    <a class="secondary" href="./development/framework.html">Understand the design</a>
  </div>
</div>

This example runs **SkillOpt with MiniAgent** on 12 bundled SearchQA questions. It uses six questions for train, three for dev, and three for test. You need Python and two model configurations. Docker is not required.

## Install FlashRSI

From a terminal:

```bash
git clone https://github.com/RUC-NLPIR/FlashRSI.git
cd FlashRSI
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[all]"
```

Python 3.11+ is supported. Python 3.12 covers the widest set of benchmark integrations. See [Installation](./guide/installation.md) for Harbor, τ², Windows activation, and Docker.

## Run the experiment

The **Target** answers benchmark questions. The **Worker** proposes changes to its skills. Set their credentials separately before running from the repository root:

```bash
export TARGET_API_KEY="your-target-key"
export WORKER_API_KEY="your-worker-key"

flashrsi run \
  --config examples/quickstart.yaml \
  --algorithm skillopt \
  --benchmark searchqa \
  --agent-harness miniagent \
  --model gpt-5-mini \
  --worker-model gpt-5-mini \
  --set agent.llm.api_key="$TARGET_API_KEY" \
  --set algorithm.worker.llm.api_key="$WORKER_API_KEY"
```

Use model names supported by your provider. For a custom endpoint, set `agent.llm.base_url` and `algorithm.worker.llm.base_url`. See [Configuration](./guide/configuration.md).

::: tip Check setup first
Run `flashrsi run --config examples/quickstart.yaml --check-only` to check startup without model calls. This may prepare data and dependencies; it does not test remote model authentication.
:::

## Inspect the output

The command prints the experiment directory. The sample configuration writes it under `../runs/`, relative to the repository root.

| File | What to look for |
| --- | --- |
| `end-summary.md` | Completion status, final test score, and recorded usage. |
| `result.json` | The selected `snapshot_id`, `test_score`, and `test_tasks`. |
| `snapshots/` | Initial and candidate resource versions. |
| `trajectories/` | Task answers, Worker calls, and selection decisions. |
| `config.yaml` | The resolved configuration with credentials redacted. |

Check that the tasks ran, then inspect failed trajectories. This small sample checks the setup; its score is not a research result. To measure an improvement, evaluate the initial and selected Snapshots on the same held-out tasks.

## Evaluate a saved Snapshot

Use any saved compatible candidate, including an intermediate Snapshot:

```bash
flashrsi evaluate \
  --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run/snapshots/SELECTED_ID.json \
  --model gpt-5-mini \
  --set agent.llm.api_key="$TARGET_API_KEY"
```

This evaluates the destination benchmark's test split without starting a Worker or continuing the search. Read [Snapshot evaluation](./guide/evaluation.md) before transferring resources between experiments.

## Choose your next experiment

A run combines four pieces. Change one while keeping the others explicit.

<div class="resource-map">
  <div><strong>Algorithm</strong><p>The search policy. It decides what to edit, how to use feedback, and which candidate to keep.</p></div>
  <div><strong>Harness</strong><p>The Target's native execution path and its declared prompts, skills, tools, and runtime resources.</p></div>
  <div><strong>Worker</strong><p>An LLM that proposes text edits or an agent that edits candidate files.</p></div>
  <div><strong>Benchmark</strong><p>The tasks, environments, grading rules, and train/dev/test split.</p></div>
</div>

- [Choose and run an experiment](./running-experiments.md) for practical setup and output details.
- [Algorithms](./integrations/algorithms.md), [benchmarks](./integrations/benchmarks.md), and [harnesses](./integrations/harnesses.md) for supported combinations and limits.
- [Framework & Snapshot](./development/framework.md) for the resource boundary.
