---
name: appworld-paginated-api-page-limit
description: >-
  AppWorld paginated list/search endpoints that validate page_limit. Use when a
  bulk fetch plan may set page_limit above the API maximum, or when a call
  returns HTTP 422 about a page_limit constraint.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [b0a8eae_2]
---
# AppWorld paginated endpoints: respect page_limit limits

Do not set `page_limit` above an endpoint's maximum. This avoids HTTP 422
validation errors and silent truncation.

## Rules
- Check docs or prior outputs for the endpoint's `page_limit` maximum before
  bulk fetching.
- For AppWorld paginated list/search endpoints, the maximum may be 20; e.g.
  `spotify.show_playlist_library(access_token=tok, page_limit=50)` returns
  HTTP 422 "ensure this value is less than or equal to 20".
- Use `page_limit=20` and iterate with `page_index` until results are
  exhausted.
- Accumulate results across pages and stop only when fewer than `page_limit`
  items are returned or the total count is reached.

## Verification
Confirm each page call returns 200 (not 422) and that iteration continues
until all items are collected. If a 422 mentions a `page_limit` maximum, lower
the page size and rerun.
