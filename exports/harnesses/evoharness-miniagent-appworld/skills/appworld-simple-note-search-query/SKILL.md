---
name: appworld-simple-note-search-query
description: >-
  AppWorld simple_note retrieval tasks where a target note must be found among
  many routine or pinned notes. Use when broad search_notes output is dominated
  by unrelated recurring notes.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [b0a8eae_1]
---
# AppWorld simple_note: use a focused search query

When a target note is buried among routine or pinned notes, query for the topic
instead of relying only on broad recency order.

## Rules
- `search_notes(access_token=tok, page_limit=20)` with no query returns notes
  ordered by recency and pinned status; high-volume recurring notes can bury
  the target.
- Build a focused query from the task's topic, e.g.:
```python
results = apis.simple_note.search_notes(
    access_token=tok, query="workout", page_limit=20
)
```
- Use the documented query parameter rather than fetching all notes and
  scanning manually.

## Verification
Before answering, confirm the target note appears in the query results. If the
first broad page omits it, retry with the topic query and verify the target is
present.
