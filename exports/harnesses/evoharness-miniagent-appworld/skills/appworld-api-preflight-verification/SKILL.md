---
name: appworld-api-preflight-verification
description: AppWorld tasks requiring bulk or mutating API work across records, playlists, notes, or pages. Use when the solver is about to loop over API results; verify the exact task target set, endpoint pagination limits, and actual response schema before bulk operations.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [ce359b5_2, ce359b5_3, b0a8eae_1, b0a8eae_2]
---
# AppWorld API preflight: verify target set, limits, and schema first

Failures across Spotify and simple_note tasks share one pattern: the solver
assumed API behavior or task scope and started bulk work before checking the
actual API/task constraints.

## Preflight checklist
1. Re-read the task and fix the concrete target set before mutating. Defaults
   can be wrong in destructive scopes (e.g., "my song library and playlists"
   requires both `show_playlist_library` and `show_liked_playlists`).
2. Probe one record before looping. Print a sample response and access only
   keys observed or documented there; do not assume fields such as
   `album_title`.
3. Check pagination limits before bulk fetching. Prefer `page_limit=20` with
   `page_index` iteration; an over-large `page_limit` returns HTTP 422.
4. Use focused query parameters for targeted lookup. Empty queries return
   recency/pinned-first pages that can bury the target record.

## During and after
- Stop on the first unexpected error (`KeyError`, 422, 401) and inspect the
  actual response/docs, then rerun with corrected arguments.
- Verify accumulated results cover the full target set before answering or
  marking the task complete.

This is a cross-task planning/verification skill. App-specific procedures stay
in their topic skills; this skill enforces preflight checks before bulk API
work.
