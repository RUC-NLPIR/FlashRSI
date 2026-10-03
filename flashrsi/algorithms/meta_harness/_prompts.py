"""Filesystem navigation and the edit boundary for Meta-Harness proposals."""

PROPOSE = """[Meta-Harness: propose]
Search iteration: {step}

Improve the target harness in the current working directory. Its initial files
are the seed, not a required parent: inspect any prior version and freely reuse,
combine, or rewrite its mechanisms to construct one new candidate.

SEARCH HISTORY (relative to the current working directory):
- `{history}/index.json` maps native Snapshot IDs to historical source directories.
  Source paths in this index are relative to `{history}`.
- `{history}/trajectories/` contains full prior evaluations and proposer traces.
  Evaluation records link task inputs, outputs, messages, metrics and errors to
  Snapshot IDs. Score/decision records report aggregate scores and attempted edits.

Use your file and terminal tools to selectively inspect the history. Read actual
source and successful/failed trajectories as needed, including low-scoring and
rejected attempts. Diagnose causes of failure before editing; decide which past
ideas to retain, revise, or abandon. The outer loop will evaluate your candidate.

TARGET COMPONENT RULES:
{rules}

Edit only the target files outside `{history}/`. Treat history as read-only
reference material; it will be removed before committing your candidate. Preserve
the declared component layout and the target's execution interface. Keep the underlying model
and runtime credentials fixed. Make reusable harness improvements rather than
hard-coding answers or task IDs. Do not access held-out tests or benchmark graders.

Return a brief explanation of your design. The edited files are the proposal;
there is no patch-response format to fill in.
"""
