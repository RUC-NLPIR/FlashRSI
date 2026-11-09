---
name: appworld
description: Complete tasks in the supplied AppWorld through its documented APIs.
---

Discover the current world API documentation, inspect relevant state, perform the requested actions, and verify results. Use the supplied appworld_execute MCP tool. Read API documentation instead of assuming signatures. Call the documented supervisor completion API when finished. Do not access grading, benchmark solutions, other tasks, or external data; do not rebuild or close the world.

## Solving strategy

### Budget and batching
- Track the remaining `appworld_execute` budget and batch independent operations into as few scripts as possible.
- Combine login, pagination loops, filtering, multiple mutations, and re-fetch verification in one Python script whenever they are independent. Loop over records and pages inside the script instead of making one `appworld_execute` call per record or per page.
- Print progress and stable record identifiers as a script runs so a retry can continue without repeating or corrupting state.

### Pre-mutation allowlist
- Before any create, update, or delete, enumerate every relevant list/search API exhaustively: set `page_limit` to the documented maximum and loop `page_index` (or the documented pagination key) until a page is short or empty.
- Build an explicit allowlist of target records from that enumeration using the task's exact criteria. Include each record's stable ID and the required final attributes: actual sender/receiver, recipient/account, amount and payment direction, date/window, library/playlist membership, genre, director/artist, like/comment/review/follow state, enabled flag, queue position, and every required app.
- Never infer record identity from creation order, list position, or create/update/delete response messages. Map each record to its actual returned fields.
- Do not treat a plausible or self-consistent summary as the allowlist; write down the concrete records and attribute values that must hold when the task is done.

### Payment and transaction direction
- For any payment or transaction task containing `received`, `sent`, `received from`, or `sent to`, first determine the account owner's role and map the instruction to concrete transaction fields:
  - `received`/`from` means the account owner is the recipient/payee.
  - `sent`/`to` means the account owner is the sender/payer.
- Confirm the sender and recipient on the transaction records themselves, and compute totals or selections from those fields rather than from the ambiguous phrase alone.

### Post-mutation verification
- After mutating, independently re-fetch the affected records (do not trust mutation responses) and assert that every actual attribute matches the allowlist, including actual sender/receiver, recipient/account, amount, payment direction, date/window, enabled, playlist privacy and membership, queue position, like/comment/review/follow state, and every required app.
- Only call the supervisor completion API after every allowlisted record passes. A "success" response message is not verification; the re-fetched record state is. Do not treat a self-consistent summary as verification.

### Time and grouping
- For any task containing relative time words (`today`, `yesterday`, `last N days`, `last month`, `this year`, `last year`) or boundary/grouping words (`before`/`after`, `newer`/`older`, `organize by`), first call the world date/time API and write down explicit ISO date bounds.
- Apply the stated comparison literally and consistently to every record. For grouping or organizing tasks, group by the exact attribute named in the instruction (for example creation date), not by inferred labels such as folder names.
