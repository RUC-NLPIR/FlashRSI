---
name: main
description: General guidance for solving tasks and following requested output formats.
---

# Task solving

Read the question and any supplied context carefully. Identify the requested
entity or value, check the supporting evidence, and answer concisely. Follow any
explicit output-format requirements. Describe tool use only when it actually
occurred, and distinguish supplied evidence from assumptions.


## AppWorld tasks

When executing AppWorld tasks through `mcp__appworld__appworld_execute`, use the preloaded API client and manage the turn budget.

### API client and discovery
- Use the preloaded `apis` global directly; do not `import apis`. If an import error occurs, the client is already available and can be inspected with `print(dir())` or `print(sorted(globals().keys()))`.
- Use preloaded helpers such as `json`, `Counter`, `defaultdict`, `datetime`, and `requester` instead of restricted imports or filesystem/introspection helpers such as `os`, `sys`, `inspect`, or `open`. Avoid blocked or unnecessary imports/introspection; they fail or waste turns.
- Inspect only the needed API docs before acting: `apis.api_docs.show_app_descriptions()`, `apis.api_docs.show_api_descriptions(app_name=...)`, and `apis.api_docs.show_api_doc(app_name=..., api_name=...)`. Print the results and note app names, parameter names, required fields, response shapes, and documented limits.
- In time-sensitive tasks, obtain the simulated current date/time from world APIs or runtime time globals rather than assuming from token expiry, file timestamps, or general knowledge.

### Authentication and data access
- Get supervisor context early: `apis.supervisor.show_active_task()`, `apis.supervisor.show_profile()`, and `apis.supervisor.show_account_passwords()`.
- For authenticated app APIs, inspect the target app's login API doc, log in once with the supervisor-provided app account email/username and password, save the returned `access_token`, and reuse it for all subsequent authenticated calls to that app. Missing tokens commonly produce 401 errors.
- Before creating records, use list/show APIs to check for existing resources and avoid duplicates. For create/update, preflight reads: list/show all relevant records across pages first.
- Use detail/show endpoints when list responses omit fields you need. Inspect raw records before accessing nested, numeric, or optional fields.
- Resolve people/accounts through available search endpoints and identify current records by flags such as `is_current` or position fields; when a task refers to "so far" in an ordered or cyclic structure, operate on the prefix ending at the current item.
- For file/email evidence, list relevant directories/mailboxes and read readable records; ignore unreadable binary duplicates, watch for overlapping file formats, and cross-check current-world dates from messages, app APIs, or task context before applying relative terms.
- For list-returning endpoints, page through all results using the documented pagination parameters (usually `page_index` and `page_limit`). Respect documented caps such as `page_limit <= 20`, and continue until an empty or short page is returned; collect all pages before filtering, sorting, or checking existence. Do not assume page 0 contains all records, that one page is complete, or that results are sorted.

### Execution and completion
- Batch independent actions inside as few `mcp__appworld__appworld_execute` calls as practical: fetch credentials and token once, then loop over records in a single Python block. Use server-side filters where available, but still verify after listing or mutating state.
- Once enough evidence is available, stop exploring and execute the required actions; avoid extra exploratory calls that may exhaust the turn budget. If near the turn limit, submit the best supported answer instead of over-exploring.
- After state changes, verify the final state with read/list APIs.
- Read the supervisor completion API doc and follow its answer contract exactly. For question tasks, pass only the concise requested value as `answer`; avoid adding units, labels, or prose. For action-only tasks, call without an answer or pass `None` and do not summarize actions. Use the documented status value (usually `"success"`) and call `apis.supervisor.complete_task(...)` promptly.
- Use only the supplied AppWorld APIs; do not access grading, ground-truth solutions, or benchmark files.

<!-- SLOW_UPDATE_START -->
---
name: main
description: General guidance for solving tasks and following requested output formats.
---

# Task solving

Read the question and any supplied context carefully. Identify the requested entity or value, check the supporting evidence, and answer concisely. Follow any explicit output-format requirements. Describe tool use only when it actually occurred, and distinguish supplied evidence from assumptions.

## AppWorld tasks

At the start of an AppWorld task, read this skill with the Skill tool before calling `mcp__appworld__appworld_execute`. Use the preloaded API client and manage the turn budget.

### API client and discovery
- Use the preloaded `apis` global directly; do not `import apis`. If an import error occurs, the client is already available and can be inspected with `print(dir())` or `print(sorted(globals().keys()))`.
- Use preloaded helpers such as `json`, `Counter`, `defaultdict`, `datetime`, and `requester` instead of restricted imports or filesystem/introspection helpers such as `os`, `sys`, `inspect`, or `open`. Avoid blocked or unnecessary imports/introspection; they fail or waste turns.
- Inspect only the needed API docs before acting: `apis.api_docs.show_app_descriptions()`, `apis.api_docs.show_api_descriptions(app_name=...)`, and `apis.api_docs.show_api_doc(app_name=..., api_name=...)`. Print the results and note app names, parameter names, required fields, response shapes, and documented limits.
- In time-sensitive tasks, obtain the simulated current date/time from world APIs or runtime time globals rather than assuming from token expiry, file timestamps, or general knowledge.

### Authentication and data access
- Get supervisor context early: `apis.supervisor.show_active_task()`, `apis.supervisor.show_profile()`, and `apis.supervisor.show_account_passwords()`.
- For authenticated app APIs, inspect the target app's login API doc, log in once with the supervisor-provided app account email/username and password, save the returned `access_token`, and reuse it for all subsequent authenticated calls to that app. Missing tokens commonly produce 401 errors.
- Before creating records, use list/show APIs to check for existing resources and avoid duplicates. For create/update, preflight reads: list/show all relevant records across pages first.
- Use detail/show endpoints when list responses omit fields you need. Inspect raw records before accessing nested, numeric, or optional fields.
- Resolve people/accounts through available search endpoints and identify current records by flags such as `is_current` or position fields; when a task refers to "so far" in an ordered or cyclic structure, operate on the prefix ending at the current item.
- For file/email evidence, list relevant directories/mailboxes and read readable records; ignore unreadable binary duplicates. Do not repeatedly attempt to read files returned as `binary:...`; instead use readable text/alternative records or proceed with available evidence.
- For list-returning endpoints, page through all results using the documented pagination parameters (usually `page_index` and `page_limit`). Respect documented caps such as `page_limit <= 20`, and continue until an empty or short page is returned; collect all pages before filtering, sorting, or checking existence. Do not assume page 0 contains all records, that one page is complete, or that results are sorted.

### Execution and completion
- Batch independent actions inside as few `mcp__appworld__appworld_execute` calls as practical: fetch credentials and token once, then loop over records in a single Python block. Use server-side filters where available, but still verify after listing or mutating state.
- Once enough evidence is available, stop exploring and execute the required actions; avoid extra exploratory calls that may exhaust the turn budget. If near the turn limit, submit the best supported answer instead of over-exploring.
- After state changes, verify the final state with read/list APIs.
- Read the supervisor completion API doc and follow its answer contract exactly. For question tasks, pass only the concise requested value as `answer`; avoid adding units, labels, or prose. For action-only tasks, call without an answer or pass `None` and do not summarize actions. Use the documented status value (usually `"success"`) and call `apis.supervisor.complete_task(...)` promptly.
- Use only the supplied AppWorld APIs; do not access grading, ground-truth solutions, or benchmark files.
<!-- SLOW_UPDATE_END -->
