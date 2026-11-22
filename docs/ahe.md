# AHE

**English** · [简体中文](./ahe.zh-CN.md)

[All algorithms](./integrations/algorithms.md) · [Example configuration](../examples/quickstarts/ahe.yaml)

AHE edits the current harness, declares which task outcomes each change should affect, and checks those predictions against the next train evaluation. Every protocol-valid, evaluated edit is kept, including regressions. The next Worker uses the verdicts to decide what to keep, improve, or undo. After evolution, the initial Snapshot and every retained version are evaluated on dev. The highest-scoring version is returned; ties keep the earliest version.

## Requirements

Train must be non-empty with unique task IDs, and dev must be non-empty for final selection. The Worker must be a file-editing Agent (`algorithm.worker.type: agent`); a text LLM Worker is rejected at startup. Target and Worker have independent model and connection settings.

`evolve_scope = {"*"}` covers all components the Target declares, not arbitrary host files or the internals of every harness. MiniAgent can expose runtime code; Claude Code exposes supported instructions, extensions, and settings. New files must satisfy the Target's component rules. See [harness integrations](./integrations/harnesses.md).

AHE uses train for diagnosis and per-edit prediction checks. Once editing stops, dev selects the final Snapshot from the complete retained history, including the seed. Dev evidence is not supplied to the debugger or editing prompt. The runner evaluates only the selected Snapshot on test; test never participates in selection.

## Run a small example

Follow [Installation](./guide/installation.md), then configure both roles' models and credentials in [examples/quickstart.yaml](../examples/quickstart.yaml). From the repository root:

```bash
flashrsi run --config examples/quickstart.yaml \
  --algorithm ahe \
  --algorithm.worker.type agent \
  --algorithm.worker.name miniagent \
  --algorithm.worker.max_turns 30 \
  --algorithm.max_steps 1 \
  --algorithm.use_debugger false
```

This uses bundled local QA data and omits the optional debugger calls. It still evaluates the complete train split. If the initial train score already meets `target_score`, it stops without editing. Append `--check-only` for initialization without model calls or authentication validation. The dedicated [AHE example](../examples/quickstarts/ahe.yaml) enables the debugger by default.

## Search and selection

1. Evaluate the initial Snapshot on all train tasks.
2. Before each attempt, stop if the current mean score reaches `target_score`.
3. Build evidence from current training trajectories, the previous change verdicts, bounded rollback source text, and the last four declined edits. With `use_debugger`, request per-task diagnoses, failures first, then one cross-task overview.
4. Check out current and let the Worker edit its files. Remove known runtime artifacts, commit within component rules, and compare actual changed paths with the returned manifest. Invalid or empty edits consume an attempt but receive no candidate evaluation.
5. Evaluate a valid candidate on the same full train split. Record each task's before/after score, delta, and pass/fail flip; judge the manifest's predictions.
6. Activate the candidate even if it ties, regresses, or receives an ineffective/harmful verdict. It becomes the next editing base.
7. When attempts end or the train score target is reached, evaluate the seed and every retained candidate once on the full dev split. Select the highest dev score, keeping the earliest Snapshot on ties. Restore that Snapshot for final test evaluation. Invalid or empty edits are excluded from this pool.

During exploration, an automatic rollback or non-regression gate is not implemented. Rollback is a possible *later Worker edit*, informed by the preceding verdict and source text. Rollback text is bounded; binary content is not rendered as text. Worker/debugger execution failures propagate rather than becoming ordinary declined edits.

## Manifest and verdicts

The editing reply requests a JSON object inside `<MANIFEST>...</MANIFEST>`:

```json
{
  "failure_evidence": ["task and trace evidence"],
  "root_cause": "why the harness failed",
  "targeted_fix": "what changed",
  "changes": [
    {"path": "relative/file", "fix_tasks": ["task-id"], "risk_tasks": []}
  ]
}
```

Declared paths must exactly match the real diff. When `changes` is absent or empty, the parser expands top-level `predicted_impact` across changed files. Per-file omitted fix/risk lists inherit that prediction; explicit empty lists remain empty. Missing required fields, invalid JSON, and mismatched paths are declined. The tag parser also accepts an untagged JSON reply.

Pass/fail attribution uses zero as the boundary: `before <= 0 < after` is `fail_to_pass`; `before > 0 >= after` is `pass_to_fail`. Other movements are `unchanged` for this categorical verdict, even though their numeric delta is recorded. A score change from 0.3 to 0.8 therefore does not count as a predicted fix.

| Verdict | Meaning for a declared file change |
| --- | --- |
| `EFFECTIVE` | A non-empty set of predicted fixes all flipped, with no declared risk realized. |
| `PARTIALLY_EFFECTIVE` | Some predicted fixes flipped, with no declared risk realized. |
| `MIXED` | At least one predicted fix and one declared risk materialized. |
| `HARMFUL` | A declared risk materialized without a predicted fix. |
| `INEFFECTIVE` | No predicted fix or declared risk materialized. |

Regressions named in no change's fix or risk lists appear as `unattributed_regressions`. These are prediction checks against joint outcomes, not controlled causal attribution proving which file caused a change.

## Parameters and cost

Defaults below belong under `algorithm`.

| Field | Default | Meaning |
| --- | --- | --- |
| `max_steps` | `10` | Edit-attempt limit; integer, at least 1. Invalid attempts also count. |
| `target_score` | `1.0` | Stop when the current train mean reaches this value. |
| `use_debugger` | `true` | Add per-task diagnoses and a cross-task overview. |
| `debugger_max_tasks` | `90` | Maximum trajectories diagnosed per attempt, failures first; at least 1. |
| `max_evidence_chars` | `30000` | Character limit for serialized evidence blocks; at least 1. |

For N train tasks, D dev tasks and S attempts, Target search and selection cost at most `(1 + S) * (N + D)` task executions: one train evaluation per seed/valid candidate, followed by one dev evaluation per retained version including the seed. The current score is reused, not re-evaluated as a fresh baseline each step. Each attempt makes one editing call; an enabled debugger adds up to `min(N, debugger_max_tasks)` task calls plus one overview. Native model/tool turns and final test are additional.

## Inspect an experiment

`decision.kind: decline` records an invalid attempt and its reason. `kind: keep` records the parent/candidate scores, manifest, per-task attribution, verdicts, rollback sources, and `accepted: true`. That acceptance means retained resources, not improved performance. Final `selection-dev` records score every eligible Snapshot. A concluding `promote` decision records `selection_split: dev`, `selection_policy: best_dev`, the full `dev_scores` list, and the selected Snapshot. Its parent is the last exploration version; its candidate is the version returned for testing.

## Source and adaptation

The [implementation](../flashrsi/algorithms/ahe/__init__.py), [manifest protocol](../flashrsi/algorithms/ahe/_manifest.py), and [prompts](../flashrsi/algorithms/ahe/_prompts.py) record `china-qijizhifeng/agentic-harness-engineering` commit `8b2a55d97590363fe50c3cc6b5e833b020a4bb4c`, via FlashRSI port reference `5efe9b438483710060183c6c3ecbc5062b410a58`. For selection, the upstream [`update_best_ever`](https://github.com/china-qijizhifeng/agentic-harness-engineering/blob/8b2a55d97590363fe50c3cc6b5e833b020a4bb4c/evolve.py#L2361) replaces the recorded best only on strict score improvement; [Algorithm 1 of the paper](https://arxiv.org/html/2604.25850v1#alg1) returns the best harness. The upstream script records last and best scores separately. FlashRSI explicitly restores the selected version for its runner. Using a separate dev split for this final ranking is the FlashRSI experiment protocol, not an upstream split requirement.

Local choices include reply-based manifests rather than a manifest file in the checkout, actual Snapshot diff validation, bounded evidence, and continuing after invalid edits. The conservative rollback/non-regression variants and cross-process search resume are not implemented. Extra configuration keys do not create these capabilities.
