# AppWorld Task Guide

You solve tasks in the AppWorld simulator by running Python through the
`mcp__appworld__appworld_execute` tool. A persistent shell is already prepared
with `apis` pre-imported. Do **not** write `import apis`; just use `apis`
directly. Do not inspect the local filesystem or read benchmark/plugin files;
everything needed is inside AppWorld.

## Budget and style

- You have at most 30 `appworld_execute` calls. Make each call count.
- Batch several independent operations in one call. Prefer one larger Python
  script over many tiny calls.
- Always `print(...)` results; only printed output is returned to you.
- Use `page_limit=20` (the maximum) and paginate with `page_index` until a
  page returns fewer than 20 items. Define a reusable helper:

```python
def fetch_all(fn, **kwargs):
    out, page = [], 0
    while True:
        res = fn(access_token=token, page_index=page, page_limit=20, **kwargs)
        if not res:
            break
        out.extend(res)
        if len(res) < 20:
            break
        page += 1
    return out
```

- Only use `fetch_all` with endpoints that document `page_index` and
  `page_limit`. Endpoints such as `show_song_queue` and `show_current_song`
  are **not** paginated; call them directly. `show_song_queue` returns the
  full queue in one response.
- Verify state changes with a read/query call before completing the task.
- The Python shell is persistent across calls, but access tokens may expire.
  If you get a 401, log in again and continue. Use the exact password strings
  from `show_account_passwords()`.

## Starting a task

In your first call, get the active task, supervisor identity, and app
passwords together:

```python
print(apis.supervisor.show_active_task())
print(apis.supervisor.show_profile())
print(apis.supervisor.show_account_passwords())
```

Then print only the API docs you need, in batched calls:

```python
print(apis.api_docs.show_app_descriptions())
print(apis.api_docs.show_api_descriptions(app_name="phone"))
print(apis.api_docs.show_api_doc(app_name="phone", api_name="login"))
```

Log in to each required app with the credentials from
`show_account_passwords()`. Reuse the returned `access_token` in later calls.

## Completing the task (critical)

`apis.supervisor.complete_task(answer=..., status=...)` marks the active task
complete. Its API docs say:

- Pass `answer` **only if the instruction is an actual question** that asks
  for a value, e.g. "What ...", "How many ...", "How much ...", "How long ...",
  "Name ...", "Which ...". Keep the answer concise: a number, name, title, or
  short list.
- For any **action** instruction (send, reply, delete, move, create, play,
  like, rate, accept, reject, request, follow, unfollow, mark, export,
  compress, organize, cleanup, add, remove, ...), do **not** pass `answer`.
  Call:

```python
print(apis.supervisor.complete_task(status="success"))
```

- Never put a long description of what you did in `answer`. That belongs in
  your final assistant message, not in the API call.

### Answer formatting

For numeric/currency questions, pass a plain number string with no `$`, no
commas, and no extra prose. Examples:

- For a total of $1068, use `answer="1068.0"` or `answer="1068"` (not
  `"$1068"`).
- For a count, use `answer="10"` or `answer=10`.
- For a short text answer, use only the requested value (e.g. a title or
  name), not a sentence.

### Side effects

Make only the state changes the task asks for. Extra side effects can fail
grading. For example, when sending Venmo requests, do **not** add the person
as a friend first; `create_payment_request` works directly with the receiver
email.

## App-specific patterns

### Phone
- `apis.phone.login(username=<supervisor phone number>, password=<phone password>)`
- `apis.phone.get_current_date_and_time()` gives the world's current date/time.
  Call it whenever the instruction uses "today", "yesterday", "this year",
  "last month", etc.
- `search_contacts(access_token=..., relationship="friend|roommate|coworker|sibling|...")`
  retrieves contacts by relationship. Use it for any relationship-based task.
- `search_text_messages` / `search_voice_messages` accept `phone_number` and
  pagination parameters. Delete spam with the matching delete APIs and then
  verify zero remain.

### Venmo
- `apis.venmo.login(username=<supervisor email>, password=<venmo password>)`
- Relationship categories for tasks such as "friends", "roommates", or
  "coworkers" are normally defined in the **phone contact book**, not in
  Venmo's `search_friends`. Prefer
  `apis.phone.search_contacts(relationship=...)` and match by email unless the
  task explicitly says "Venmo friends".
- Pending received requests:
  `apis.venmo.show_received_payment_requests(access_token=..., status="pending", page_limit=20)`
  and paginate through all pages.
- Transactions:
  `apis.venmo.show_transactions(access_token=..., direction="received|sent", query=..., page_limit=20)`.
  Use `min_created_at` and `max_created_at` (in `YYYY-MM-DD` format) to
  restrict by date; do not rely only on the first page.
- Use the documented `create_payment_request`, `deny_payment_request`,
  `approve_payment_request`, or `send_money` APIs. Match people by their email
  address. Send a payment request directly to the recipient's email; do not
  call `add_friend` unless the task explicitly asks you to add friends.

### Spotify
- `apis.spotify.login(username=<supervisor email>, password=<spotify password>)`
- Library/private endpoints include `show_song_library`, `show_album_library`,
  `show_playlist_library`, `show_liked_songs`, `show_downloaded_songs`,
  `show_liked_albums`, `show_following_artists`. Paginate all of them.
- `show_playlist` returns a `songs` key (full song objects);
  `show_playlist_library` and `search_playlists` return a `song_ids` key.
  Check the key that the endpoint actually returns before counting songs.
- An album counts as downloaded only if **every** song id in its `song_ids`
  appears in `show_downloaded_songs`.
- Use `show_song_privates` / `show_album_privates` / `show_playlist_privates`
  for play counts, like counts, and similar private fields.
- `show_song_queue` returns the entire current queue and is not paginated;
  call it directly, then check `len(queue)` and `is_playing`.

#### Spotify cleanup tasks

Read the instruction's conjunction exactly:

- **"liked or downloaded"**: keep a song if it is in `show_liked_songs` OR in
  `show_downloaded_songs`; keep an album if it is in `show_liked_albums` OR all
  of its songs are downloaded.
- **"liked and downloaded"**: keep a song only if it is in **both**
  `show_liked_songs` AND `show_downloaded_songs`. Keep an album only if it is in
  `show_liked_albums` AND every song id in its `song_ids` is in
  `show_downloaded_songs`.

Remove the rest with `remove_song_from_library` / `remove_album_from_library`,
then verify with fresh `show_song_library` / `show_album_library` calls.

### Workout playlist task
When the instruction asks to start a playlist that has "enough songs" for a
workout and the workout plan is in Simple Note:

1. Get the current date, then read the matching day's entry from the workout
   note and record `duration_mins`.
2. Create a **public** playlist with `create_playlist(title="... Workout ...",
   is_public=True, access_token=...)`.
3. Add **`duration_mins` unique songs** (minimum 1). Pull first from
   `show_liked_songs`, `show_downloaded_songs`, and `show_song_library`
   (deduplicate by `song_id`), then fill the remaining slots with
   `search_songs(query="", page_limit=20)` results.
4. Start playback of that playlist. The safest pattern is
   `clear_song_queue`, then `add_to_queue(playlist_id=...)`, then
   `play_music()`; if you use `play_music(playlist_id=...)`, clear the queue
   first so the queue contains exactly the chosen playlist.
5. Verify `show_current_song` has `is_playing: true` and `show_song_queue`
   has at least `duration_mins` songs and, if durations are available, at least
   `duration_mins * 60` total seconds. Then complete with
   `status="success"`.

### File system
- `apis.file_system.login(username=<supervisor email>, password=<file_system password>)`
- `show_directory(directory_path="~/...", recursive=True, access_token=...)`
  lists files; always include the slash after `~` (`"~/bills"`, not `"~"`).
  `show_file` gives `content`, `created_at`, and `updated_at`.
- Use `create_directory`, `move_file`, and `copy_file` with full destination
  paths that preserve the original file name. Prefer `~`-relative paths.
- For bill totals, read the `.txt` files. The `.pdf` files in the same
  directories are often unreadable binary duplicates; do not double-count them
  by also trying to parse the `.pdf`s unless the task explicitly requires it.

#### CSV export tasks

When writing a CSV file with a required header:

- Write the header line exactly as requested, e.g. `Title,Artists`, and only
  quote a field when it contains a comma, double quote, or newline. Do **not**
  quote every field.
- Join multiple artists with `|` inside the single Artists field, e.g.
  `Lucas Grey|Velvet Echo`.
- Verify the written file with `show_file` before calling `delete_account` or
  `complete_task`.

### Simple Note
- `search_notes` returns note metadata (not content); then use
  `show_note(note_id=..., access_token=...)` to read content.
- Use `query`, `tags`, and `page_limit=20`; pinning can reorder results, so
  if you are looking for a specific note, search by query and check all pages.

## Common pitfalls

- Do not pass `answer` to `complete_task` for action tasks.
- Do not include `$`, commas, or prose in numeric answers.
- Do not waste calls inspecting Python internals (`dir(apis...)`, importing
  appworld modules, etc.). Use `apis.api_docs` and the documented app APIs.
- If an endpoint returns fewer than `page_limit` items, you have reached the
  last page.
- Verify your final world state with a read/query call, then complete.
- If `complete_task` returns a task-completed message, you still need to give a
  brief final answer in your assistant response, but do not assume that changes
  the world.
