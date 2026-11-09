---
name: venmo-relationship-target-derivation
description: Use for AppWorld/Venmo tasks that mutate records qualified by a social relationship plus a time window (e.g. "payments I received from my friends"), where the target set must be derived by cross-referencing endpoints before bulk comment/like mutations.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [afc0fce_2]
---
When a Venmo task requires acting on records qualified by a relationship (e.g. "payments I received from my friends"):

1. Do not assume the transactions endpoint exposes a friendship filter. `show_transactions` accepts only `user_email`, `direction`, and date/amount filters; there is no "friends" filter.
2. Enumerate the relationship set first with `search_friends`, which returns the friend emails.
3. Fetch candidate records with the appropriate filters: `show_transactions(direction='received', min_created_at=<simulated date - window>)`. Compute the date filter from the simulated datetime, inclusive of today.
4. Intersect the two result sets on the counterparty field (`sender.email`) to obtain the true target set.
5. Only after deriving the target set, apply the requested bulk mutation (e.g. comment/like) to those records.

Before mutating, verify the window boundary (inclusive of today) and confirm which counterparty field the intersection uses.
