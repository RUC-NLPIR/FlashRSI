# AppWorld harness notes

When using the `mcp__appworld__appworld_execute` tool, the AppWorld API client
`apis` is already available inside the sandbox as a pre-injected global object.
Call it directly rather than importing it:

```python
print(apis.api_docs.show_app_descriptions())
print(apis.api_docs.show_api_descriptions(app_name="phone"))
print(apis.api_docs.show_api_doc(app_name="phone", api_name="show_alarms"))
```

Do NOT use `import apis` or `import apis.api_docs`. Those imports are blocked by
the sandbox and will fail with `Usage of the following module is not allowed: apis.`

If you see that import-rejection error, remove the import and call
`apis.<service>.<api>()` directly instead.

## Completing a task

- AppWorld grades the final world state, not your final text answer. A text answer
  alone does **not** change the world.
- When the required world-state changes are done, call the documented supervisor
  completion API, e.g. `print(apis.supervisor.complete_task(status="success"))`.
  Do not end your turn before that call unless you have a concrete, task-relevant
  reason the task is impossible.
- Before completing, name the observable state changes you made. If you cannot name
  any state change, you are not done yet: query or mutate the world first.
- A Stop guard is active in this harness. If you try to end your turn without a
  `supervisor.complete_task(...)` call in the transcript, the stop is blocked and
  you are prompted to continue. If that prompt appears, do not just repeat a text
  answer: make the missing world-state changes, then call the completion API and
  wait for its result before ending again.
- If a tool result reports `task_completed: false`, the task is not finished yet.
  That is a signal to continue with the next required world-state change, not to
  stop.

## Efficient API discovery

- Prefer targeted `show_api_doc(app_name=..., api_name=...)` calls for the exact
  methods your plan needs over printing every app or API description.
- If a tool result is truncated, ends mid-JSON, reports an error, or is marked
  `"truncated": true`, do not guess the missing content and do not stop. Re-run a
  narrower query, print a smaller slice, or inspect the specific API doc you need.
- Broad discovery calls such as `show_app_descriptions()` are read-only and never
  complete a task. Use them only to find the app name, then switch to targeted
  calls.
- If a call returns an authorization error (401, "not authorized", or a missing /
  invalid / expired access token), do not retry the same call unchanged. Call the
  relevant app's login API with the credentials supplied in the task, then retry
  the failing private API.
- When a task mentions a relative time such as "yesterday" or "last 7 days", obtain
  the simulation's current date/time from the relevant app first (for example
  `print(apis.phone.get_current_date_and_time())` or the equivalent API in the app
  you are working with) instead of assuming a date.
