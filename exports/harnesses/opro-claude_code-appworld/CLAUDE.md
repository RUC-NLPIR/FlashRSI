# CLAUDE.md

## Pre-flight
- Convert the request into a measurable contract: target app/account/data source, candidate entities, all filters, allowed actions, exact values/content/recipients/channels, and success criteria.
- Resolve every missing or ambiguous detail from current app/system state. Never assume.
- Capture stable IDs and exact attributes: names, emails, usernames, phone numbers, paths, dates, amounts, categories, memberships, balances, content. Use system date/time for relative dates.
- Enumerate exhaustively: paginate, expand, and deduplicate until every relevant record is seen. For all/every/only/not/except/missing and set relations, compute full set operations by stable ID and verify counts.

## Execution
- Plan tool calls within the execution budget: batch independent reads/actions, avoid redundant checks, reserve capacity for final verification and supervisor completion.
- Act only on the exact computed target set. Use exact identifiers and exact values/content/recipients/channels. Do not skip matches, add unrequested objects, substitute actions, or modify out-of-scope state.
- If the target set is empty, verify that explicitly; do not force an action.

## Post-action
- Read back affected records/state after every action or batch. Compare exact expected outcomes: counts, IDs, names, dates, amounts, memberships, folder/file contents, messages, status, balances.
- On any mismatch, correct only the mismatch and re-verify before continuing.

## Completion
- Independently re-check every acceptance criterion against current state.
- If a supervisor completion API exists, call it only after all checks pass and confirm the call succeeds.
- Report concise exact evidence with identifiers/counts and explicit confirmation of each requirement.
- Never claim completion from partial, stale, sampled, unverified, or empty results.

## Hard Rules
- When uncertain, inspect again; never guess.
- App/system data and stable identifiers are the final arbiter.
