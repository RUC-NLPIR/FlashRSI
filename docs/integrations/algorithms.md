# Algorithms

Choose a method by the resource you want to improve. FlashRSI supplies versioned resources, rollout, grading, and records; each method keeps its own proposal, selection, and memory policy.

## Instructions and skills

| Method | What it changes | How it searches | Settings / example |
| --- | --- | --- | --- |
| OPRO | Instructions | Proposes from scored history; returns the best candidate. | [Guide](../opro.md) · [中文](../opro.zh-CN.md) · [YAML](../../examples/quickstarts/opro.yaml) |
| GEPA | Instructions | Reflects on trajectories and screens a candidate pool. | [Guide](../gepa.md) · [中文](../gepa.zh-CN.md) · [YAML](../../examples/quickstarts/gepa.yaml) |
| EvoPrompt | Instructions | Uses GA or DE population search on dev scores. | [Guide](../evoprompt.md) · [中文](../evoprompt.zh-CN.md) · [YAML](../../examples/quickstarts/evoprompt.yaml) |
| ACE | Instructions / playbook | Accumulates feedback and reflections into a playbook. | [Guide](../ace.md) · [中文](../ace.zh-CN.md) · [YAML](../../examples/quickstarts/ace.yaml) |
| SkillOpt | Skills | Uses fast/slow updates and adopts strict dev gains. | [SkillOpt guide](../skillopt.md) · [Quickstart YAML](../../examples/quickstart.yaml) |
| SkillAdam | One Markdown skill | Tracks recurring issues and adapts the edit budget to per-task score changes. | [Settings](#skilladam) |
| Evo-Harness | Skills | Accumulates task-stream skills through native skill discovery. | [Guide](../evo-harness.md) · [中文](../evo-harness.zh-CN.md) · [YAML](../../examples/quickstarts/evo_harness.yaml) |

### SkillAdam

Set `algorithm.name` to `skilladam` and configure the Worker model under `algorithm.worker.llm`. Start from a Markdown file in the Target’s `skill` component. If there are several, set `algorithm.skill_path` to the file the Target loads, such as `skills/main.md` for MiniAgent.

Each round samples training tasks and asks the Worker for edits using the trajectories and its history of issues and attempts. The candidate is scored on the same dev tasks as the incumbent. Only a strict increase in the mean score selects the candidate. Rejected attempts remain in the next round’s issue memory.

`max_iterations` defaults to 4 and `batch_size` to 8. The edit budget starts at `base_budget` (4) and can shrink to `min_budget` (1) as the variance of per-task score changes grows. `beta` (0.9) smooths this variance across rounds and `v_max` (0.25) sets the scale. The Snapshot carries the selected skill. [Upstream implementation](https://github.com/ruc-datalab/SkillAdam/tree/b6c9640f7a9e0d5e3a500c25bc4e6369eeca78f1)

## Harness resources

These methods edit a broader resource scope. Start from their own configurations, including an Agent Worker capable of file edits.

| Method | How it searches | Settings / example |
| --- | --- | --- |
| AHE | Successive edits with diagnosis and edit audits. | [Guide](../ahe.md) · [中文](../ahe.zh-CN.md) · [YAML](../../examples/quickstarts/ahe.yaml) |
| ADAS | A design archive; retains proposals and selects the best. | [Guide](../adas.md) · [中文](../adas.zh-CN.md) · [YAML](../../examples/quickstarts/adas.yaml) |
| DarwinX | Repeated train screening/confirmation; preservation gates and complementary recombination. | [Guide](../darwinx.md) · [中文](../darwinx.zh-CN.md) · [YAML](../../examples/quickstarts/darwinx.yaml) |
| Meta-Harness | File-based history of code, scores, and traces. | [Guide](../meta-harness.md) · [中文](../meta-harness.zh-CN.md) · [YAML](../../examples/quickstarts/meta_harness.yaml) |
| ModularRSI | Independent module branches and integration, admitted by review/execution gates rather than score gains. | [Guide](../modular-rsi.md) · [中文](../modular-rsi.zh-CN.md) · [YAML](../../examples/modular_rsi.yaml) |
| RRSI | History-guided revisions with score/cost admission; returns the last accepted version. | [Guide](../rrsi.md) · [中文](../rrsi.zh-CN.md) · [YAML](../../examples/quickstarts/rrsi.yaml) |
| Arbor | Hypothesis-tree planning; experiments start from the selected trunk and require strict dev gains for adoption. | [Guide](../arbor.md) · [中文](../arbor.zh-CN.md) · [YAML](../../examples/quickstarts/arbor.yaml) |

## Match the Worker to the method

For three directory-editing methods, the current implementations differ as follows:

| Method | Editing base | Search evidence | Adoption and final selection |
| --- | --- | --- | --- |
| AHE | Current retained version | Train traces, optional debugger, previous verdicts | Keep every valid evaluated edit, including ties/regressions; return the last retained version. |
| ADAS | Current best-dev version | Design descriptions and dev scores, bounded in the prompt | Retain all measured designs in the archive; strictly higher dev changes best; promote best at the end. |
| Meta-Harness | Initial seed; Worker may copy any historical version | Historical source and full recorded dev/Worker traces in files | Retain all measured versions; strictly higher dev changes best; promote best at the end. |

These are local implementation rules, not claims of complete upstream reproduction. ADAS still has an unpinned upstream revision; the method pages state other adaptation limits.

- Use `algorithm.worker.type: llm` when the method requests textual proposals.
- For an Agent Worker, set `type: agent` and choose `name: miniagent`, `claude_code`, `codex`, `pi`, `hermes`, `openclaw`, or `opencode`, with independent `llm` settings.
- Evo-Harness needs directory-based native skill discovery. ModularRSI needs explicit module mappings. Follow the linked method guide before switching harnesses.

## Interpret results

The fourteen implementations adapt methods to FlashRSI's resource and evaluation interfaces. Registration is a configuration entry point; consult each guide's migration notes for differences from the original method and supported capabilities.

The [overall results](../../README.md#overall-results) compare methods using DeepSeek-V4.1-Flash as Target and DeepSeek-V4-Pro as Worker. See the [experiment protocol](../experiments/protocol.md) for model aliases, SearchQA output limits and metadata corrections.

To implement your own search policy, see [Add an algorithm](../development/algorithm.md).
