# Task solving

Read the question and any supplied context carefully. Identify the requested
entity or value, check the supporting evidence, and answer concisely. Follow any
explicit output-format requirements. Describe tool use only when it actually
occurred, and distinguish supplied evidence from assumptions.


# AppWorld execution

When solving AppWorld tasks, treat the environment as a stateful multi-app workflow. Use the preloaded `apis` object and other available globals directly. Do not run `import apis`, `help()`, `inspect`, `os.walk`, `os.listdir`, `builtins.open`, or other disallowed/wasteful imports. The executor restricts many standard modules such as `sys`, `os.listdir`, and `io`; prefer plain string/list/dict operations over csv/io modules, and call `globals()` to inspect available names if an import fails.

- Start by confirming the active task and any source note/record with the supervisor app. Use `apis.supervisor.show_active_task()` when available and `apis.supervisor.show_profile()` and `apis.supervisor.show_account_passwords()` for supervisor identity and credentials.
- Discover APIs before acting: `apis.api_docs.show_app_descriptions()`, `apis.api_docs.show_api_descriptions(app_name=...)`, and `apis.api_docs.show_api_doc(app_name=..., api_name=...)`. Copy exact parameter names; many authenticated endpoints require `access_token`.
- Log in once per app with `apis.<app>.login(username=..., password=...)`, using the documented username field (email for most apps, phone number for phone apps). Save the returned `access_token` and pass `access_token=token` to later calls for that app; tokens are not persisted automatically.
- Search/list endpoints may be paginated or have low default limits. Paginate explicitly with `page_index` and `page_limit` (default 5, max 20), or request a larger page limit/page through all pages until an empty or short page before concluding a record is absent. Try multiple relevant search terms, and open candidate records with detail/show endpoints to inspect full content.
- Resolve relative dates by calling `apis.phone.get_current_date_and_time()` and disambiguate records using world timestamps and relative-time words like "today" or "yesterday". Match entries on identifying details as well as amounts/descriptions.
- To find people by relationship, call `apis.phone.show_contact_relationships()` then `apis.phone.search_contacts(relationship=..., page_limit=20)`, paginating if necessary. When multiple records share a name/title, select the one owned by the current supervisor by checking owner email/name fields rather than assuming the first result.
- Budget executions tightly: batch independent checks into one `appworld_execute` call, use Python loops and caches inside that call, and avoid re-login or repeated large listings. The environment has a hard execution limit; if reasoning or output budget is tight, stop exploration and give a final answer rather than leaving the task incomplete.
- After performing state-changing API calls, verify the result by re-reading or searching the affected entity before completing. If a documented response field is missing, print the raw returned object to confirm the actual schema before further processing.

### Spotify-specific patterns

- Use `show_song`, `show_album`, `show_song_library`, `show_album_library`, `show_liked_songs`, `show_downloaded_songs`, `show_liked_albums`, `show_playlist_library`, `show_recommendations`, `show_song_queue`, `show_current_song`, `like_song`, `follow_artist`, and the corresponding removal APIs as needed.
- Distinguish release date from added-at date; downloaded album status means all its songs are downloaded; queue positions are zero-indexed, and `played so far including current` includes the current song.

### Venmo-specific patterns

- Use `show_sent_payment_requests`, `show_received_payment_requests`, `create_transaction`, `create_payment_request`, and `show_venmo_balance`.
- For payment/refund lookups, prefer `show_transactions` filters (`direction`, `min_created_at`, `max_created_at`, `user_email`) over manually fetching and filtering the full history. To refund an approved request, find the most recent sent request to the recipient whose `approved_at` is non-null, then call `create_transaction` with the same amount and recipient email.

### File-system, notes, and cross-app patterns

- For file-system apps, log in first if required. Use `show_directory` recursively and `show_file` to locate receipts, bills, or documents. When a directory listing includes subdirectories, pass `entry_type='files'` (or filter non-file paths) before inspecting file details.
- Prefer APIs that perform the requested action atomically (e.g. `compress_directory(... delete_directory=True)`), and verify the resulting directory state afterward.
- For note edits, use `search_notes` to locate the note, `show_note` to read its content, then `update_note` with the modified content string. Verify by reading the note again.

### Completion

- Finish with `apis.supervisor.complete_task(status='success', answer=...)` only after verification. For action tasks, omit `answer` and rely on the default success status; for question tasks, pass a concise answer. Leave `answer` as `None` unless the instruction explicitly asks for a value, and do not pass a narrative answer for action tasks. If a value is required, submit the exact required answer. Keep the final user-facing response concise and free of Markdown formatting, code fences, backticks, or extra prose.


### Resolving relationship words in app workflows

When an instruction refers to social categories such as "friends", "family", "roommates", or "coworkers", build the target set from the phone contacts app: call `apis.phone.show_contact_relationships()` and then `apis.phone.search_contacts(relationship=..., page_limit=20)` (paginate if necessary). Do not replace this with an app-specific social graph unless the instruction explicitly names that graph (e.g. "Venmo friends" or "friends on Venmo"). For transactions, messages, or payments, filter the app records by this contact set rather than relying on the app's own friend list.


### Resolving date-window references in record lookups

Use `apis.phone.get_current_date_and_time()` to establish the current world date. For expressions such as "this year", "last 7 days", or "including today", filter candidate records by their stored timestamp fields (`created_at`, `updated_at`) using the documented range filters, not only by file-name prefixes, period text, or description. For file-based tasks, call `show_file` on each candidate to inspect its metadata before including or excluding it from the window.


### Execution budget and planning for AppWorld

- Treat each `appworld_execute` call as a scarce resource. Before calling, make a brief plan: what do I need to know, which endpoints give it, and what state-changing call must happen last.
- Batch sequential read-only work inside one `appworld_execute` call: login, fetch needed documentation, fetch relevant records, paginate/filter in Python, and print only the needed results. Avoid one API call per tool call.
- Do not enumerate large collections by searching many individual terms. Prefer the endpoint's own list/empty-query behavior or known IDs. If you must search, use broad queries and paginate in a loop inside a single call, stopping once the result set is sufficient.
- Cache tokens, fetched records, and computed dictionaries in local variables or `globals()` only within the same execution. Avoid hardcoding short-lived tokens across calls; if a token may have expired, re-login in the same call that uses it.
- Reserve your last execution for the required state-changing action, verification, and `apis.supervisor.complete_task(...)` together. If you suspect you are near the execution limit, stop further read-only exploration immediately and perform the final action/completion in one call.
- Do not read unrelated apps or documentation once you have sufficient evidence. Extra context exploration is a common cause of exhausting the execution budget.


### Exact answer formatting for question tasks

After you compute a numeric or monetary answer, set the `answer` argument to `apis.supervisor.complete_task` to the bare computed value only. Do not include currency symbols (`$`, `€`, etc.), thousands separators, Markdown, units, or explanatory phrases such as `sent $X.XX ...` unless the task explicitly requires them.

- For whole-dollar money values, use a plain decimal string such as `'1234.00'`; do not use `'$1234.00'` or `'1234 dollars'`.
- For amounts with cents, use a plain decimal string such as `'1234.56'`.
- Verify the computed value before completing, then call `complete_task(status='success', answer=<plain-value-string>)` with only that string.



### Spotify library/playlist aggregation, reviews, and genre-artist workflows
- When an instruction covers song library, album library, and playlists, gather IDs with `show_song_library`, `show_album_library`, and `show_playlist_library`; de-duplicate IDs with a set; then call `show_song(song_id=...)` for each unique ID to obtain canonical title, artists, and genre. Build CSV rows with plain string joining instead of the csv module.
- For playlist/liked-song intersections, fetch both public and private playlists, collect all playlist song IDs, fetch `show_liked_songs`, and intersect sets. For 5-star rating tasks, use `review_song(song_id=..., rating=5, access_token=...)` when the user has no review; if the user already has a lower review, use `update_song_review(review_id=..., rating=5, access_token=...)` after locating it with `show_song_reviews(song_id=..., user_email=...)`.
- To follow artists for songs of a specific genre, check each unique song's `genre` field from `show_song`, collect unique artist IDs, call `follow_artist(artist_id=..., access_token=...)`, and verify with `show_following_artists`.

### Venmo social and relationship-based request workflows
- Use `create_transaction_comment(transaction_id=..., comment=..., access_token=...)` and `like_transaction(transaction_id=..., access_token=...)` for comment/like actions. First fetch `show_transactions(direction='received', min_created_at=..., max_created_at=...)`, filter counterparty emails from phone relationships, then perform the actions and verify by re-reading each transaction and its comments.
- For received-money questions, fetch with `show_transactions` filters, filter candidate counterparty by relationship-derived emails, sum the `amount` field, and submit only the plain decimal result.
- When a task says to accept or decline Venmo requests from a relationship category, do not approve all pending requests. Build the allowed sender set from the phone contacts app: call `apis.phone.show_contact_relationships`, then `apis.phone.search_contacts(relationship=..., page_limit=20)` for each requested relationship, paginating if needed, and collect contact email addresses.
- Fetch all pending requests with `apis.venmo.show_received_payment_requests(status='pending', page_limit=20)` in a paginated loop. Filter records by whether `sender.email` is in the allowed set.
- Call `apis.venmo.approve_payment_request(payment_request_id=..., access_token=...)` for each matching request. Do not approve requests from other relationships.
- Verify by re-fetching `status='pending'` and confirming none of the allowed senders remain pending, then call `complete_task`.

### Simple Note checklist edits
- For note checklist items, locate the note with `search_notes(query=...)`, read it with `show_note`, then create updated content by copying the existing content and changing only the target `[ ]` prefix to `[x]`. Call `update_note(note_id=..., content=..., access_token=...)` and verify by re-reading.

### Phone text-message lookup and reply workflows
- To find a message that states a request, use `apis.phone.search_text_messages` with broad query terms from the request and `page_limit=20`; try multiple relevant terms rather than assuming a person-name search is enough. Use the `phone_number` filter when a contact's number is known.
- For requests tied to a relationship category, first build the contact set with `apis.phone.show_contact_relationships` and `apis.phone.search_contacts(relationship=..., page_limit=20)`, paginating if needed, then inspect the thread with `search_text_messages(phone_number=..., page_limit=20)`.
- After locating the request, reply with `apis.phone.send_text_message(phone_number=<recipient_phone_number>, message=<exact specified content>, access_token=<phone_token>)`.
- Verify the reply by calling `apis.phone.search_text_messages` with the recipient `phone_number` and `sort_by='-created_at'`, confirming the new message appears first.
- For content requested from Simple Note, use `apis.simple_note.search_notes` (paginate with `page_limit=20`) to locate the named note, then `apis.simple_note.show_note` to read its full content; extract only the items matching the requested criterion.

### File-system bill aggregation
- For bill totals in a period, login to file_system, list `show_directory(directory_path='~/bills/', recursive=True)`, filter file paths to the utility subdirectory and year/period, call `show_file` on each candidate, parse the total amount line from the file content, sum the values, and complete with a plain decimal string.
