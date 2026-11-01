# Algorithms

Choose a method by the resource you want to improve. FlashRSI supplies versioned resources, rollout, grading, and records; each method keeps its own proposal, selection, and memory policy.

## Instructions and skills

| Method | What it changes | How it searches | Settings / example |
| --- | --- | --- | --- |
| OPRO | Instructions | Proposes from scored history; returns the best candidate. | [OPRO YAML](../../examples/opro.yaml) |
| GEPA | Instructions | Reflects on trajectories and screens a candidate pool. | [GEPA YAML](../../examples/gepa.yaml) |
| EvoPrompt | Instructions | Uses GA or DE population search on dev scores. | [EvoPrompt YAML](../../examples/evoprompt.yaml) |
| ACE | Instructions / playbook | Accumulates feedback and reflections into a playbook. | [ACE guide](../ace.md) · [YAML](../../examples/ace.yaml) |
| SkillOpt | Skills | Uses fast/slow updates and adopts strict dev gains. | [Quickstart YAML](../../examples/quickstart.yaml) |
| Evo-Harness | Skills | Accumulates task-stream skills through native skill discovery. | [Evo-Harness guide](../evo-harness.md) · [YAML](../../examples/evo_harness.yaml) |

## Harness resources

These methods edit a broader resource scope. Start from their own configurations, including an Agent Worker capable of file edits.

| Method | How it searches | Settings / example |
| --- | --- | --- |
| AHE | Successive edits with diagnosis and edit audits. | [AHE guide](../ahe.md) · [YAML](../../examples/ahe.yaml) |
| ADAS | A design archive; retains proposals and selects the best. | [ADAS guide](../adas.md) · [YAML](../../examples/adas.yaml) |
| DarwinX | Branches and recombination with repeated outcome checks. | [DarwinX guide](../darwinx.md) · [YAML](../../examples/darwinx.yaml) |
| Meta-Harness | File-based history of code, scores, and traces. | [Meta-Harness guide](../meta-harness.md) · [YAML](../../examples/meta_harness.yaml) |
| ModularRSI | Independent module branches followed by integration. | [ModularRSI guide](../modular-rsi.md) · [YAML](../../examples/modular_rsi.yaml) |
| RRSI | History-guided revisions with score/cost admission. | [RRSI guide](../rrsi.md) · [YAML](../../examples/rrsi.yaml) |
| Arbor | Hypothesis-tree expansion, experiment selection, and upward insight synthesis. | [Arbor guide](../arbor.md) · [YAML](../../examples/arbor.yaml) |

## Match the Worker to the method

- Use `algorithm.worker.type: llm` when the method requests textual proposals.
- For an Agent Worker, set `type: agent` and choose `name: miniagent`, `claude_code`, `codex`, `pi`, or `hermes`, with independent `llm` settings.
- Evo-Harness needs directory-based native skill discovery. ModularRSI needs explicit module mappings. Follow the linked method guide before switching harnesses.

## Interpret results

The thirteen implementations adapt methods to FlashRSI's resource and evaluation interfaces. Registration is a configuration entry point; consult each guide's validation and migration notes for differences from the original method and tested paths. Arbor is newly integrated and has no real-model experiment results yet.

The paper's overall experiment table will be added when its final matrix is available. No aggregate result is claimed here.

To implement your own search policy, see [Add an algorithm](../development/algorithm.md).
