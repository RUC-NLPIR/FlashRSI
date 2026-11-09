---
name: sql-correlated-subquery-rewrite
description: Optimize a SQL query over a large unindexed table by collapsing repeated correlated subqueries or per-group "top-N" lookups into a single computation, then verify output equivalence. Trigger when the task needs one rewritten SQL deliverable and schema inspection shows no indexes.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [query-optimize]
---
Inspect once, then write. Do a single quick pass over schema/index/count facts
(e.g. `CREATE TABLE`, indexes, row counts), then stop deliberating and write a
first candidate rewrite to the target file immediately. Do not loop in hidden
thinking between inspection and emitting the solution.

Collapse repeated per-group subqueries. When the input query re-derives the same
top-N-per-group value more than once through identical
`GROUP BY ... ORDER BY ... LIMIT 1` logic, compute it once per group using a CTE
or window function (e.g. `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`),
and reference that single result everywhere it is used.

Validate equivalence. After writing, run the rewrite and diff its output against
the original query's output; correct any discrepancy before finishing.
