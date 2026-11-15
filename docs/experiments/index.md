---
title: Experiment explorer
description: Browse recorded evolution decisions, selection evidence, file changes, and logs behind historical FlashRSI experiments.
---

# Experiment explorer

Inspect how a method searches and selects a version. The archive covers **12 methods × 2 target harnesses on SearchQA and Terminal-Bench**. Each method has its own selection view and file comparisons.

## SearchQA {#available-experiments}

| Experiment | Selection view | What the archive distinguishes |
| --- | --- | --- |
| [SkillOpt × SearchQA](./skillopt-searchqa.md) | Fast / slow skill updates | Candidate decisions, skill diffs, and runtime progress logs |
| [OPRO × SearchQA](./opro-searchqa.md) | Optimization history | Fixed seed, scored prompt history on train, and final prompt selection |
| [EvoPrompt × SearchQA](./evoprompt-searchqa.md) | Population arena | DE target/trial competition at each slot, ties, and final population promotion |
| [GEPA × SearchQA](./gepa-searchqa.md) | Coverage frontier | Per-task co-best coverage, ancestry, recorded parent choices, and final mean-score selection |
| [ACE × SearchQA](./ace-searchqa.md) | Playbook ledger | Curator advances versus periodic validation and checkpoint promotion |
| [AHE × SearchQA](./ahe-searchqa.md) | Repair audit | Predicted fixes/risks, realized file-level effects, retention, and separate final dev selection |
| [ADAS × SearchQA](./adas-searchqa.md) | Design archive | Design revisions and archive admission versus final selection |
| [Meta-Harness × SearchQA](./meta-harness-searchqa.md) | Experiment notebook | Training experiments and earlier history versus the later dev selection |
| [DarwinX × SearchQA](./darwinx-searchqa.md) | Branch admission | Original screening/confirmation versus fixed-archive dev-gate reselection |
| [ModularRSI × SearchQA](./modular-rsi-searchqa.md) | Branches and integration | Native module mappings, review/execution gates, integration, and final selection |
| [RRSI × SearchQA](./rrsi-searchqa.md) | Round tournament | Calibrated uncertainty, gain/cost budgets, admissible/losing/rejected variants, and native incumbent selection |
| [Evo-Harness × SearchQA](./evoharness-searchqa.md) | Skill production | Training-stream compilation, topic/general skills, no-op/declined updates, and the terminal library |

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
