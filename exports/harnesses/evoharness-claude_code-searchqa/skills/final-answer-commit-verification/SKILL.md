---
name: final-answer-commit-verification
description: Verify representation, evidence, and referent before committing a graded answer. Use when a task is graded by exact string match and a semantically correct answer still fails because its form is over-elaborated, its verbatim evidence was ignored, or it names the wrong referent among shared candidates.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [b55578edb7ba4b5ba9ed09dc7333795b, 88d06cbae9ef4d5f827ed4d8ed7e2ee7, 4c64770f574c499392b07f182a75c72c]
---
Run three independent checks before committing a graded answer; an answer that is semantically right but over-elaborated, paraphrased, or mis-selected scores 0.

1. Match the expected representation. When the target is a single named entity, emit its minimal canonical form — the symbol, code, or abbreviation ("C"), not the expanded name ("Vitamin C") — because exact-string grading rejects the longer form.

2. Prefer verbatim evidence over paraphrase. If the target already appears verbatim in the supplied context (glossary, title, definition line), copy that exact span and stop; do not expand, paraphrase, or search beyond the provided documents.

3. Let explicit qualifiers select the referent. Parse temporal/status qualifiers ("current", "former", "last") before extracting. When a role or title is shared across multiple entities, the qualifier — not context frequency or salience — picks the correct one; find the passage tying that specific entity to the requested attribute.

Commit only after all three checks pass; do not let a salient keyword or the most frequent context token override the expected form or the selected referent.
