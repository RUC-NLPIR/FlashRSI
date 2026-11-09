# AppWorld execution contract

Treat every task as a small, verifiable state transition. Before acting, restate
the required final answer or final state and the exact objects involved. The
session has a hard 30-turn budget.

## 1. Submission is the terminal action of the task loop

- Call `apis.supervisor.complete_task(...)` in the same turn the required answer
  or final state is achieved and verified. Do not defer submission for extra
  exploration, inspection, or "just in case" checks.
- Spend turns only on actions that can change the graded answer or final state.
  If an action cannot affect the graded outcome, skip it.
- If you already have a best-supported answer or state and are still uncertain,
  submit it.
- For any ambiguity, make at most 2 resolution attempts, then submit the
  best-supported result.
- Question tasks: `apis.supervisor.complete_task(answer=<value>)`.
- Non-question tasks: verify the final state, then
  `apis.supervisor.complete_task(status='success')`.

## 2. API discipline

- Before calling an app API, run the metadata command and
  `apis.api_docs.show_app_descriptions()`, then read the docs for the exact app
  methods you will use.
- Use only the supervisor-provided credentials exactly as given. Do not reset,
  change, or "fix" credentials unless the task explicitly requires it.
- Use documented filter, sort, pagination, and parameter semantics. Prefer
  precise filters and sorts over broad queries.
- Paginate until an empty page and handle edge cases such as fewer results than
  the page limit. Re-fetch mutated collections to check completeness.

## 3. Verify against the task's expected state

- A successful-looking self-check is necessary but not sufficient.
- For mutation tasks, before `complete_task`, write a requirement-by-requirement
  comparison of the actual final state against the expected final state:
  - Restate each requirement from the task.
  - Re-fetch the actual state from the app or filesystem for each requirement.
  - For files, check path, headers, separators, row uniqueness, and content.
  - Mark each requirement `match` or `mismatch`; fix any mismatch before completing.
- For question tasks, show the exact query or aggregation and the raw records
  that produced the answer, then submit that value.
- If a requirement cannot be verified after 2 attempts, complete only when the
  best available evidence matches the expected state; otherwise resolve the
  ambiguity with a direct API query.

## 4. Keep data self-describing

- When printing rows or records for selection or aggregation, always print
  labeled dictionaries or JSON objects with keys, for example
  `{"id": 42, "name": "Example Item", "count": 7}`. Never print bare positional
  tuples.
- Sort with an explicit key and select by key name. Before using a numeric value
  as a minimum, maximum, or final answer, re-read the printed key labels and
  confirm which field the value belongs to; never interpret numeric columns by
  position.
