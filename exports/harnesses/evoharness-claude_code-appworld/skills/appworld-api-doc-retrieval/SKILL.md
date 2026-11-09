---
name: appworld-api-doc-retrieval
description: Use for AppWorld/FlashRSI tasks where the session already lists flashrsi:* helper skills or where you need one or a few API signatures from an app with a large API surface (e.g. Spotify, Venmo); use a listed helper skill and request docs for the specific API name instead of dumping the whole app.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [6ea6792_2]
---
When an AppWorld task lists flashrsi:* helper skills, or spans an app exposing many endpoints (e.g. Spotify, Venmo) while you only need a few signatures:

1. Check the available skills/slash_commands first. If a flashrsi:* helper already covers the app or task, use it instead of re-discovering the API by hand. Manual re-discovery — `metadata`, then whole-app `docs venmo` (46KB, persisted to file), then filtering and re-reading specific entries — burned the full 30-turn budget before any task action (login, list pending requests, deny each) occurred.
2. When you do need a signature, query the docs tool with a specific API name: `docs <app_name> <api_name>`. Whole-app `docs <app_name>` returns the entire API surface; for large apps this exceeds the output limit (observed 78KB and 91KB) and is persisted to a file with only a ~2KB preview shown, hiding the endpoint signature.
3. Do not dump full docs for several apps in a single Bash call. Query one app at a time; when surveying many endpoints, pipe docs through a compact filter that prints only api_name/method/path/short-description before reading full parameter details for the calls you actually need.

Trigger: when the session lists flashrsi:* helper skills for the app/task, or `docs <app_name>` returns an "Output too large" / persisted-output result — use the helper skill / ask for the specific endpoint instead of dumping the whole app.
