---
name: claude-code-unrecognized-model
description: Detect a fatal Claude Code harness model-configuration fault and abort early. Trigger when a run's stderr contains `claude-code:unrecognized_model` or the configured `model` field names an ID the CLI does not recognize (e.g. `deepseek-flash`), so the run would otherwise stall to its full timeout with no task artifacts.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [adaptive-rejection-sampler, make-doom-for-mips]
---
An `unrecognized_model` error is an environment/configuration fault, not a defect
in the task implementation. When the session's `model` field names an ID the
Claude Code CLI does not recognize (e.g. `deepseek-flash`), API calls fail and
the run stalls to its full timeout (e.g. 900s) without producing the requested
files.

Do:
- Confirm the configured `model` early. If it is not a recognized Claude model,
  surface the mismatch and stop instead of spending the time budget.
- If `claude-code:unrecognized_model` appears in stderr — it can surface on an
  auxiliary query such as `generate_session_title` — abort the run and report
  the configuration failure.
- When a run times out, inspect stderr before judging the implementation: an
  `unrecognized_model` timeout is a configuration fault, not evidence about the
  task's implementation quality.
