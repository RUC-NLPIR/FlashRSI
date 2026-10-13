---
name: sql-optimization
description: Use when the task is to make a SQL query faster while producing identical output — "optimize this query", "make it efficient", "same output produced". Covers schema inspection, rewrite patterns, and byte-identical verification for SQLite and other SQL dialects.
---

# SQL query optimization

Goal: rewrite a slow query so it produces byte-identical output, faster, in the
target dialect, with the exact required formatting (usually: no comments, a
single statement, terminated with `;`).

1. **Understand the original.** Read the query file, then run it under `time`
   against the database to get a baseline (`sqlite3 db < query.sql > out.txt`).
   Identify the cost source: correlated subqueries in the SELECT list, missing
   indexes, repeated full scans, or a window function over a large table.
   Capture the reference output from the ORIGINAL query run to completion on the
   real database — never reconstruct it by hand; if it is slow, run it once in
   the background with a generous timeout and diff against that saved output.

2. **Inspect the schema.** `sqlite3 db ".schema"`; list indexes with
   `SELECT name, tbl_name FROM sqlite_master WHERE type='index';`; confirm
   uniqueness assumptions via `COUNT(*)` vs `COUNT(DISTINCT …)`.

3. **Rewrite with fast primitives.**
   - Hoist correlated subqueries out of the SELECT list into `WITH` CTEs that
     are computed once.
   - Compute per-group maxima/minima with plain aggregation (`MAX(c)`,
     `MIN(x)`) plus a join on that value, NOT `ROW_NUMBER() OVER (…)` — window
     functions are far slower in SQLite.
   - Preserve the exact ORDER BY / LIMIT / tie-break semantics of the original,
     so ties resolve to the same rows.

4. **The deliverable is the query alone** — no indexes or schema changes survive
   grading. Verify the final query runs standalone on the clean database and is
   byte-identical, not merely close.

5. **Verify byte-identical output.** Run both the original and the rewrite and
   `diff` their outputs — they must be identical. Then time the rewrite and
   confirm it finishes well inside the budget (a grader may run it under a
   strict time limit).

6. **Write the final file exactly as specified** — single statement, no
   comments, dialect-correct, semicolon-terminated — then re-read it and run it
   once to confirm it executes cleanly.
