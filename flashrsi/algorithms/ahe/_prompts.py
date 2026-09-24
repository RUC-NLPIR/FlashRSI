"""AHE's three role prompts: two debugger passes and the Evolve Agent.

The Evolve Agent template carries two things upstream's does not need. Lite
classifies every file by the target's own component rules, so a new path that
matches no rule is refused outright -- the rules therefore go into the prompt.
And the manifest comes back in the reply rather than as a file in the checkout,
because a checkout holds only files the target can classify.

Upstream: https://github.com/china-qijizhifeng/agentic-harness-engineering
Commit: 8b2a55d97590363fe50c3cc6b5e833b020a4bb4c
"""

from __future__ import annotations

DEBUGGER_TASK = """[AHE: debug]
You are the Agent Debugger in Agentic Harness Engineering. Analyze one
agent rollout. Ground every claim in the supplied trace. Distinguish harness defects from
task difficulty and infrastructure failures. Return a concise report with these headings:
ROOT CAUSE, CRITICAL TRACE EVIDENCE, PASS/FAIL MECHANISM, GENERAL HARNESS FIX, RISKS.
Do not propose task-specific hard-coded answers.

TASK ID: {task_id}
EVIDENCE:
{evidence}
"""


DEBUGGER_OVERVIEW = """[AHE: overview]
You are the lead Agent Debugger in Agentic Harness Engineering. Synthesize
the per-task reports below into a layered cross-task diagnosis. Cluster common failure
mechanisms, separate infrastructure noise, identify successful patterns worth preserving,
and rank general harness interventions. Every conclusion must cite task IDs. Do not edit
the harness and do not invent evidence.

PER-TASK REPORTS:
{reports}
"""


EVOLVE = """[AHE: evolve]
You are the Evolve Agent in Agentic Harness Engineering. The harness is checked
out in your working directory. Inspect it, then edit it so the failures below stop
happening. Every change must be evidence-backed and falsifiable, and must generalize
beyond the specific tasks: do not hard-code answers.

Each file you add or edit must match exactly one of these component rules, or the whole
edit is refused:
{rules}

If the previous change evaluation marks a change INEFFECTIVE, MIXED, or HARMFUL, decide
whether to KEEP, IMPROVE, or ROLLBACK it. ROLLBACK_SOURCES holds the exact prior content
of those files; do not roll back blindly.

When you are done editing, reply with a manifest bracketed exactly like this, and nothing
after it:
<MANIFEST>
{{
  "failure_evidence": ["task and trace evidence"],
  "root_cause": "why the harness failed",
  "targeted_fix": "what you changed",
  "changes": [
    {{"path": "relative/file", "fix_tasks": ["task-id"], "risk_tasks": ["task-id"]}}
  ]
}}
</MANIFEST>
List every file you added, edited or deleted, and nothing you did not touch. fix_tasks are
the task IDs this file will flip to passing; risk_tasks are the passing tasks it may break.
Both are checked against the next rollout, so a change that names no fix_tasks cannot be
shown to have worked.

LAYERED EVIDENCE:
{evidence}
"""


__all__ = ["DEBUGGER_OVERVIEW", "DEBUGGER_TASK", "EVOLVE"]
