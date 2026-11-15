---
title: Experiment explorer
description: Browse the recorded edits, development scores, and logs behind historical FlashRSI experiments.
---

# Experiment explorer

Inspect how a method actually searches and selects a version. The archive covers **12 methods × 2 target harnesses on SearchQA, HotpotQA, and Terminal-Bench**. Each method has its own selection view; a single dev curve would hide important differences between these runs.

## Available experiments

| Method | SearchQA | HotpotQA | Selection view |
| --- | --- | --- | --- |
| SkillOpt | [Explore](./skillopt-searchqa.md) | [Explore](./skillopt-hotpotqa.md) | Fast / slow skill updates |
| OPRO | [Explore](./opro-searchqa.md) | [Explore](./opro-hotpotqa.md) | Optimization history |
| EvoPrompt | [Explore](./evoprompt-searchqa.md) | [Explore](./evoprompt-hotpotqa.md) | Population arena |
| GEPA | [Explore](./gepa-searchqa.md) | [Explore](./gepa-hotpotqa.md) | Coverage frontier |
| ACE | [Explore](./ace-searchqa.md) | [Explore](./ace-hotpotqa.md) | Playbook ledger |
| AHE | [Explore](./ahe-searchqa.md) | [Explore](./ahe-hotpotqa.md) | Repair audit |
| ADAS | [Explore](./adas-searchqa.md) | [Explore](./adas-hotpotqa.md) | Design archive |
| Meta-Harness | [Explore](./meta-harness-searchqa.md) | [Explore](./meta-harness-hotpotqa.md) | Experiment notebook |
| DarwinX | [Explore](./darwinx-searchqa.md) | [Explore](./darwinx-hotpotqa.md) | Branch admission |
| ModularRSI | [Explore](./modular-rsi-searchqa.md) | [Explore](./modular-rsi-hotpotqa.md) | Branches and integration |
| RRSI | [Explore](./rrsi-searchqa.md) | [Explore](./rrsi-hotpotqa.md) | Round tournament |
| Evo-Harness | [Explore](./evoharness-searchqa.md) | [Explore](./evoharness-hotpotqa.md) | Skill production |

Every experiment includes MiniAgent and Claude Code. The pages preserve each historical run's recorded policy; they do not substitute the latest algorithm implementation or reselect historical candidates.

Open **View diff** on a candidate, branch, or checkpoint to inspect its file changes without leaving the selection view. The comparison includes added/removed lines, before/after text, and side-by-side views; you can also choose another recorded version as the comparison base.

The explorer does not display test results. Training scores, dev scores, per-task coverage, admission gates, and final selection are labelled separately. Runtime progress logs and algorithm event records are distinct from complete model conversation transcripts.

To add an experiment, see [maintaining the explorer](../development/docs-site.md#experiment-explorer).

## Terminal-Bench

| Experiment | Selection view |
| --- | --- |
| [OPRO × Terminal-Bench](./opro-terminal-bench.md) | Optimization history |
| [EvoPrompt × Terminal-Bench](./evoprompt-terminal-bench.md) | Population arena |
| [GEPA × Terminal-Bench](./gepa-terminal-bench.md) | Coverage frontier |
| [ACE × Terminal-Bench](./ace-terminal-bench.md) | Playbook ledger |
| [AHE × Terminal-Bench](./ahe-terminal-bench.md) | Repair audit |
| [ADAS × Terminal-Bench](./adas-terminal-bench.md) | Design archive |
| [Meta-Harness × Terminal-Bench](./meta-harness-terminal-bench.md) | Experiment notebook |
| [DarwinX × Terminal-Bench](./darwinx-terminal-bench.md) | Branch admission |
| [ModularRSI × Terminal-Bench](./modular-rsi-terminal-bench.md) | Branches and integration |
| [RRSI × Terminal-Bench](./rrsi-terminal-bench.md) | Round tournament |
| [Evo-Harness × Terminal-Bench](./evoharness-terminal-bench.md) | Skill production |
| [SkillOpt × Terminal-Bench](./skillopt-terminal-bench.md) | Fast / slow skill updates |

Open a method to switch between MiniAgent and Claude Code and inspect its recorded decisions, selected artifact, and file changes. Test results are omitted.
