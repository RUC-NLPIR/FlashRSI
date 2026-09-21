# SkillOpt SearchQA audit (2026-09-19)

## Primary sources

- Official repository: https://github.com/microsoft/SkillOpt
- Inspected immutable HEAD: `79124b37e9a6371e13b753f8bcd7adb1e493ade1` (local clone `/tmp/skillopt-paper-audit/SkillOpt`).
- Paper: https://arxiv.org/abs/2605.23904 ; inspected v1 HTML https://arxiv.org/html/2605.23904v1 . Local `paper.html` and text extraction `paper.txt`.
- Main results Table 1: https://arxiv.org/html/2605.23904v1#S3.T1
- Experiment defaults: https://arxiv.org/html/2605.23904v1#S4.SS0.SSS0.Px2
- Appendix C protocol: https://arxiv.org/html/2605.23904v1#A3
- Official SearchQA config: https://github.com/microsoft/SkillOpt/blob/79124b37e9a6371e13b753f8bcd7adb1e493ade1/configs/searchqa/default.yaml
- Official inherited defaults: https://github.com/microsoft/SkillOpt/blob/79124b37e9a6371e13b753f8bcd7adb1e493ade1/configs/_base_/default.yaml
- Official artifact caveats and reference checkpoint: https://github.com/microsoft/SkillOpt/blob/79124b37e9a6371e13b753f8bcd7adb1e493ade1/ckpt/README.md and `ckpt/searchqa/gpt5.5_skill.md`.

## Dataset verified locally

Official IDs are in `data/searchqa_id_split/{train,val,test}/items.json`, with 400 / 200 / 1400 items. This is a 2,000-task SkillOpt subset of `lucadiliello/searchqa`, not the complete SearchQA release. Lite's `dev` corresponds to official `val`/selection. The official evaluator calls these `valid_seen` (selection) and `valid_unseen` (test).

Lite pins `jinjiajie/flashrsi@97f222eda79b77ac217848a18ed3b415b60d8e89`, prepared from `jinjiajie/EvoOS@2e2d97feb4a3394fd577017024e6d9f3176e9fbc`, sourced from `lucadiliello/searchqa@c1a979068ba118d85467179b704031d113d689cc`, with SkillOpt split source `db46cd9ae7ce12f1dbd73c945185816aa738751d`.

The existing Lite local source JSONLs were checked against current immutable official ID manifests: all three split IDs AND order match exactly. All 2,000 question/context/answer payloads were also checked against the original cached Hugging Face Arrow data at the pinned revision: 0 missing, 0 mismatches. Verification outputs are `split-audit.json` and `payload-audit.json` in this directory.

The official renderer limits context to 6,000 characters at `[DOC]` boundaries. No supplied subset context exceeds 6,000 (maximum 4,820), so that difference has no effect here. `benchmark.split: auto`, with no `limit`, preserves the exact released split. Explicit ratio splitting does not.

## Official SearchQA scores

Table 1 reports held-out test EM percentages. All three values below use GPT-5.5 as the target; default optimizer is GPT-5.5.

| Harness | No skill | SkillOpt | Gain (percentage points) |
| --- | ---: | ---: | ---: |
| Direct chat | 77.7 | 87.3 | +9.6 |
| Codex | 81.8 | 87.3 | +5.5 |
| Claude Code | 81.9 | 85.9 | +4.0 |

There are no DeepSeek-v4-flash/pro or MiniAgent rows in this paper. DeepSeek plus MiniAgent/Claude Code is a method-transfer/reproduction experiment, not a matched reproduction of a published cell. A GPT-5.5 reference arm is the most direct route to compare a paper score. The released `ckpt/searchqa/gpt5.5_skill.md` can be evaluated independently without paying for optimization again, but its transfer to DeepSeek is a separate condition from a newly trained DeepSeek skill.

## Effective configuration and protocol

- Four epochs, 400 training items, batch 40 = 10 updates/epoch, 40 planned fast steps, no artificial max-step truncation.
- Reflection minibatch 8, merge batch 8, analyst concurrency 16 (concurrency can be lowered for runtime capacity).
- Textual edit budget starts at 4 with cosine schedule down to floor 2. The paper also reports a constant-budget ablation and SearchQA 87.3 for constant in Table 2; changing to constant must be recorded rather than called identical default.
- Success and failure evidence analyzed separately. Official implementation separates the full batch into success/failure lists, shuffles each, then chunks each list into groups of 8.
- Hard metric is normalized exact match. Soft metric is token F1. Normalization is lowercase, removal of ASCII `string.punctuation`, regex English article removal, collapse whitespace. Max over references.
- Official answer extraction: use the LAST `<answer>...</answer>` match, case-insensitive and DOTALL; otherwise use the final non-empty response line.
- Strict selection gate: candidate EM must be strictly greater; ties rejected. No test examples used for candidate selection.
- Slow update enabled, 20 train examples with previous/current snapshots from epoch 2 onward, plus optimizer-only meta skill. Paper-associated reference artifacts require `optimizer.slow_update_gate_with_selection: true`.
- Current official main defaults slow gate to `false`; `ckpt/README.md` explicitly says this is post-submission behavior. Do not use unmodified main defaults for paper reproduction.
- Rejected buffer is epoch-local and includes each step's observed failure patterns plus rejected edits and score drop.
- Training seed 42. Official epoch shuffle uses `seed + epoch * 1000`, with epochs numbered from 1; slow sample seed is `seed + epoch * 2000`.
- Teacher and student reasoning effort default medium. SearchQA direct-chat max turns 1, completion budget 16,384, executor timeout 120 seconds, rollout workers 24.
- Initial skill is `# Question Answering Skill\n\n(No learned rules yet. Rules will be added through the reflection process.)`.
- Direct-chat default system: expert QA agent, context-grounded answer, think step by step, final short answer inside `<answer>` tags. Harness mode stages the same skill in native `SKILL.md` and a `task.md`, requests the skill explicitly, and returns `<answer>` output. Codex/Claude execution traces are fed to reflection.

## Current FlashRSI-Lite comparison

1. Dataset membership and payload are aligned, as verified above.
2. `benchmarks/metrics.py` currently applies NFKC/casefold and removes Unicode punctuation too; it does not extract XML answers or final lines. Thus it is not the exact official scorer. The biggest practical difference is final-answer extraction. Use a separately named official protocol/metric rather than silently describing Lite's current generic metric as official.
3. Lite's task wrapper asks for only a short answer; official asks for reasoning plus `<answer>` tags. MiniAgent has its own system prompt, skills protocol and additional extraction stage. Claude Code has its native system prompt and workspace setup. Record these as harness differences.
4. Lite currently uses fixed budget 4, seed+zero-based-epoch shuffle, and chunks the original rollout before splitting successes/failures. It retains only the last five rejected patches across epochs, with no full failure-pattern buffer. Its prompts are adapted to multiple skill files, while official optimizes one skill document.
5. Lite already implements the strict dev gate and gated slow updates, with slow/meta enabled and 20 samples. These are substantially aligned with paper core behavior.
6. Never use the checked-in demo skill `examples/agents/open_harness/skills/main.md` as the baseline: its content at audit time is `Paris`. Use a clean official initial skill and the same target model/harness across all conditions.

## Official paper/code inconsistency

Paper defaults mention up to three teacher refinement rounds. Current official `CHANGELOG.md` lines 89–92 explicitly states `gradient.max_analyst_rounds` was parsed/logged but NEVER reached reflection and is now retired. The actual reflection functions perform one model call per success/failure minibatch (API retries are not refinement). Therefore three reflection rounds should not be implemented merely to copy the prose; record the documented/actual discrepancy.

The paper also contains internal inconsistencies in peripheral ablation prose, e.g. Table 2 train-size split caption states 4:1:5 while Appendix C says 2:1:7. Prefer the explicit released IDs for this task.

## Practical assessment

Use the frozen official split and official scorer, baseline and final held-out evaluation for each fixed harness, and retain raw response/parsed answer/score so extraction effects are inspectable. Do not choose settings using the 1,400 test labels. A result near 86–87% may be a useful reference but cannot be promised for changed model/harness pairs. Report both absolute final EM and paired change from the identical harness/model baseline.

Full optimization is not a tiny smoke test: Table 6 reports 213.8M training tokens for its SearchQA GPT-5.5 example. A normal full run can evaluate roughly 40 * 200 = 8,000 dev trajectories in addition to 1,600 training trajectories, baseline dev, slow comparisons and final test. Early smoke validation should use an explicitly labeled subset/budget; full runs should preserve the 400/200/1400 split.
