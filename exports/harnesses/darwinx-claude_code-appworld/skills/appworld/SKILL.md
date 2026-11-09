---
name: appworld
description: Use when solving AppWorld tasks with the appworld_execute MCP tool. Covers safe API discovery, action execution, and supervisor completion.
---

# AppWorld task procedure

## API access
- `apis` is already injected into the persistent AppWorld shell. Do **not** write `import apis` or `from apis import ...`; the shell rejects those imports.
- Call APIs directly with `apis.<app_name>.<api_name>(...)`.
- Always wrap calls in `print(...)` so the returned value is visible in tool output.

## Discovery
1. Start with `print(apis.api_docs.show_app_descriptions())` to see the available apps.
2. For the relevant app, run `print(apis.api_docs.show_api_descriptions(app_name='<app>'))`.
3. For each API you plan to use, run `print(apis.api_docs.show_api_doc(app_name='<app>', api_name='<api>'))` and follow the documented parameter names and required arguments exactly.

## Execution
- Prefer keyword arguments exactly as shown in the API docs.
- Verify each action by reading back the affected objects/collections before moving on.
- If a call raises an error, re-read the API doc rather than guessing argument names or shapes.

## Completion
- When the requested information has been obtained or the requested world changes are done, call the documented supervisor completion API and print its result.
- Do not read grading, ground-truth, or benchmark files.
