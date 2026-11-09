---
name: appworld-supervisor-complete-task
description: AppWorld tasks that require an explicit supervisor.complete_task call after the requested API action has succeeded. Use when the terminal action returned success and a read-back already confirms the target state while a valid access token is still held.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [c901732_1]
---
# AppWorld: complete the task immediately after verified success

A successful AppWorld API action does not finish the task by itself; the run
still requires an explicit supervisor completion call.

## When to apply
- The terminal API action returned success.
- A verification read-back (for example `show_current_song`) already matches
  the task goal.
- The harness still shows the task as incomplete.

## Procedure
1. Keep the verified result value from the read-back in the current execution
   context.
2. Call the supervisor completion endpoint with that verified result, for
   example:
```python
apis.supervisor.complete_task(answer=verified_result)
```
3. Do not re-authenticate or run additional verification calls before
   completing when the target state is already confirmed. Extra calls such as
   `spotify.login` after the successful action can delay or obscure the
   required completion step.
4. If completion fails, re-check the expected answer format and retry once
   with the same verified result.

## Verification
Before ending the episode, confirm `supervisor.complete_task` was actually
called after the last successful action. If only API actions and read-backs
are visible, add the completion call with the confirmed result.
