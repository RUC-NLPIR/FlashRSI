---
name: appworld-execute-recovery-and-verification
description: AppWorld tasks when an execute block fails partway or mutates API state. Use when retrying a failed script, following/liking records, persisting tokens, or logging into phone/venmo; preserve original task filters, re-fetch mutated values before answering, avoid disallowed built-ins, and verify app-specific login identifiers.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [07b42fd_2, 07b42fd_3, 3c13f5a_1, 3c13f5a_2]
---
# AppWorld execute recovery and verification

Failures across Spotify and phone/venmo tasks share recovery and tool-use
patterns distinct from preflight planning.

## Retry after partial execute failure
- When a script dies after side effects but before the planned filtered call,
  rerun the exact intended call with all original task filters.
- Do not drop filters such as `min_follower_count`; broader retrieval changes
  the target set and under-covers bulk mutations.
- Fix only the aborting error (e.g. failed import); keep the original query.

## Re-fetch after mutation
- A mutating call such as `follow_artist` can change the metric used in the
  task condition or final answer.
- Keep the pre-mutation snapshot for eligibility, but re-fetch the record
  after mutation and report the post-action value.
- Do not present a stale pre-action count as current without labeling it.

## Execute sandbox constraints
- Do not use `open()` or other disallowed built-ins in an AppWorld execute
  block to persist tokens/state; the whole block aborts and prior output is
  lost.
- Keep tokens in variables in the same block, or re-fetch them later.

## App-specific login identifiers
- Do not assume the supervisor email works for every app.
- Check each app's login identifier; phone may expect a phone number, venmo
  with an email can return 422 account-not-found.
- On 422 account not found or 401 invalid credentials, stop cycling variants
  and consult app docs/provisioning.

## Verification
Before answering, confirm: retries kept all original filters, mutated fields
were re-read after action, no disallowed built-in was used, and each app used
its documented login identifier.

This complements `appworld-api-preflight-verification` (pre-bulk checks); this
skill covers post-execution recovery and verification.
