---
name: minimal-answer-verification
description: Calibrate and verify minimal outputs for automatically-graded short answers. Use when the answer span appears verbatim in the supplied context, when a context offers both specific and generic phrasings, or when a yes/no claim shares a salient keyword with evidence but the actual outcome must be matched.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [28ce80cc4e9440b8bae1ec4a2c94c4c4, d98417a0052c446b9cbec27592b0716b, d86f059053b84a90964e806da32c9302]
---
1. Emit the verbatim span immediately. When the answer token appears verbatim (and often repeatedly) in the supplied context, copy that minimal span and output it as the final answer at once. Do not invoke a skill or keep deliberating after it is found — delay or extended internal reasoning can leave the run with no answer output and score 0.

2. Prefer the shortest, most general base noun. When the context offers both a specific phrase and a generic term, answer with the bare noun the question requires and strip descriptive modifiers the question does not itself require (e.g., "balloon", not "hot air balloon").

3. Verify the semantic consequence, not the shared keyword. When a yes/no claim overlaps a passage on a salient phrase, do not let that shared term drive the polarity. Locate the passage stating the actual outcome and match the claim's consequence (dies vs. survives), not merely the triggering event the claim shares with the text.
