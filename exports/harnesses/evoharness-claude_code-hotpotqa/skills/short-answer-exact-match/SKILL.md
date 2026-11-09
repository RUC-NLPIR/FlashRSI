---
name: short-answer-exact-match
description: Apply when a short-answer or multi-hop QA prompt instructs "return only the short answer" (or similar) and scoring is exact match. Emit the minimal answer label — stripped of parentheticals, leading qualifiers, and trailing category words — but preserve a person's full canonical name as given in the source; when the answer already appears verbatim in the supplied context, resolve from that context without tool searching or over-deliberation, and make sure it appears as visible text.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids:
    - 5a77b9e155429967ab105249
---

## Procedure

For a short-answer or multi-hop QA prompt that asks for "only the short answer" (or similar) and is graded by exact match:

1. If the answer already appears verbatim in the supplied context, resolve the qualifying hops against that context and stop. Do not invoke read-only filesystem tools (they cannot add information) and do not over-deliberate with escalating thinking steps.
2. Identify the answer label that fills the blank — a bare noun or name, not a descriptive phrase. For a person's name, use the full canonical form given in the source's lead sentence (e.g. "Jennifer Jane Saunders", not "Jennifer Saunders"): a middle or full given name is part of the answer, not a qualifier to strip.
3. Strip whatever the question or grader does not ask for:
   - Leading qualifiers attached by the source (e.g. answer "Umpire of the Year", not "ICC Umpire of the Year award").
   - Trailing category words already present in the question (e.g. "what genre of films" -> "horror", not "horror films"; "what award" -> the award name, not "...award").
   - Parenthetical elaboration after a correct core answer (e.g. "Yarmouth, Maine", not "Yarmouth, Maine (at the DeLorme headquarters)").
4. Before finishing, confirm the final assistant message contains the answer as visible text. If reasoning reached the answer, re-emit it as a text block — a turn that ends with only a thinking block delivers no answer to the evaluator.

Emit exactly the short answer and nothing else.
