# AppWorld Agent Operating Guide

## Core Rules
- Treat the AppWorld environment as the only source of truth. Do not rely on remembered app data, IDs, field names, or examples from other tasks.
- Print every API result or error in full. If output is truncated, do not proceed as if you saw all records.
- Never report an action as successful unless the actual tool output explicitly shows success.
- Do not name or rely on training examples in your reasoning; solve the current task only.
- Do not access grading, ground-truth solutions, or benchmark files.
- Do not instantiate, reinitialize, reset, load another task into, or close AppWorld. Use only the supplied current world.

## Input Format
- The task is provided as JSON with fields such as `task_id`, `instruction`, `supervisor`, and `apps`.
- The `instruction` is the only objective to complete.
- Supervisor details may be needed to look up credentials or identity, but they are not app data and should not be treated as hardcoded facts.

## Authentication and Credentials
- Many private or state-changing operations require the relevant app account to be logged in.
- Before mutating state in an app, check the app's API docs for `login`, `logout`, `show_account`, or similar account APIs.
- Use the supervisor app to find credential APIs or account information when credentials are needed.
- Retrieve credentials with documented supervisor APIs rather than hardcoding them from the task prompt.
- If you call `login`, verify it succeeded with a read-only account or profile API before making changes.

## API Discovery and Calling
- Use `apis.api_docs.show_app_descriptions()` to see available apps.
- Use `apis.api_docs.show_api_descriptions(app_name=...)` to list an app's APIs.
- For any API you plan to call, inspect its full doc with `apis.api_docs.show_api_doc(app_name=..., api_name=...)` when the description is ambiguous or when arguments are unclear.
- Call documented APIs through `apis.<app_name>.<api_name>(...)`.
- Pass arguments exactly as documented. Do not guess parameter names or types.
- If `task_completed` is `false`, the code failed or the task is not complete. Read the output and retry.

## Common Error Recovery
- If execution fails with `"Usage of the following module is not allowed: apis."`, retry without importing `apis`. It is already available as a preloaded object.
- If a doc result is truncated or unclear, query the specific app or API doc for more detail.
- If an API call fails with invalid arguments, recheck the API doc and use the exact parameter names and types shown there.
- If a data result is truncated or possibly incomplete, narrow the search, use pagination if available, or fetch records individually by ID. Do not mutate based on partial data.

## General Task Strategy
- Break the task into small, verifiable steps.
- Explore relevant app APIs before making changes.
- Use identifiers from search results such as IDs, phone numbers, email addresses, or names. Do not hardcode IDs.
- When a task mentions multiple record types, handle all affected types. For example, phone message deletion may require searching and deleting both text messages and voice messages separately.
- A display name is not a unique identifier. Many apps can have duplicate names for people, albums, artists, songs, playlists, or files.

### Named-Entity Lookup and Disambiguation
- Treat a name in the instruction as a search key, not as proof of a unique record.
- Use the broadest relevant search or list API for that entity type.
- Retrieve and inspect all search results that could match. Do not select the first result merely because its name looks similar.
- Fetch full details for each candidate using the appropriate `show_*` or detail API before deciding.
- Compare all available metadata such as title, artist, year, type, or other unique fields to disambiguate.
- If search results are truncated or paginated, fetch the next page or narrow the search with additional terms; never act on a partial candidate set.

### Superlatives and Metric Selection
- When the task asks for a superlative such as "most listened to", "least", "latest", or "top", identify the documented numeric or date field that expresses that criterion.
- Do not assume a field name or reuse one from another app.
- Fetch full details for every candidate in the relevant set.
- Print an explicit sorted list of candidate IDs and their metric values before selecting.
- Select the matching item by its unique ID after comparing the full candidate set, not by display order or a presumed top result.
- If multiple records tie for the same value, handle the tie according to the task wording. If no tie-breaker is given, inspect metadata or documented ordering before choosing.

## Building a Complete Candidate Set
For tasks that require "all X that satisfy condition C":
1. Identify the global namespace of X using the broadest available search/list API.
2. If the condition involves a category or type, retrieve the exact category values from the relevant category/list API, such as `show_genres` in Spotify.
3. Do not restrict the candidate set to records already associated with the current account unless the task explicitly asks for that.
4. Fetch full details for every candidate before deciding whether it matches.
5. Apply the condition carefully. Pay attention to inclusive thresholds: "at least 21" includes 21.
6. Build an explicit set of matching identifiers and print it before mutating.
7. Do not stop after finding the first match if the task says "all".

Even when the task asks for only one final item, such as the "most" or "latest" item, the same principle applies: identify all possible candidates, inspect their full details, compute the requested metric over the complete set, and then choose.

## Mutations and Verification
- Apply mutations to every identifier in the expected set.
- After mutation, verify with a read-only API that lists the whole final collection or relationship.
- Compare IDs or unique identifiers, not display names, because names may not be unique.
- Do not rely on a mutation call's success message or on checking only one record.
- For follow/like/join tasks, use the corresponding read API that lists all current relationships, such as `show_following_artists` in Spotify, and verify every expected ID is present.
- For state changes such as playing a song, verify with the relevant current-state API and confirm the unique ID or state matches the intended target.

## Verification Against Completion Text
- A supervisor completion message such as "Marked the active task complete" only means the completion API was called.
- It is not proof that the requested application state was changed correctly.
- Before calling the completion API, verify the actual final application state with read-only calls.
- Do not infer task success from a completion message alone.

## App-Specific Notes
- **Spotify**: `show_genres` lists exact genre names. `search_artists` can enumerate artists; inspect `show_artist` for public artist details such as genre and follower counts. `show_artist_following` tells whether the current user follows an artist; it is not the artist's follower count. Use `follow_artist` to change follow state and `show_following_artists` to verify the full set of followed artists.
- **Spotify albums and songs**: For an album or song lookup, use search/list APIs to find candidates, then use detail APIs such as `show_album` or `show_song` to get full metadata. Album and song titles may be duplicated, so compare album IDs, song IDs, artists, and other metadata. When a task refers to "most listened", "most played", or similar phrasing, use the documented listen/play metric on the full song records, compute the maximum over the complete set of songs in the selected album or playlist, and only then play the selected song ID. Verify with `show_current_song` that the current song ID and title match the chosen song.
- **Phone**: Deletion tasks may require handling text messages and voice messages separately. Search by the given phone number or contact identifier across all relevant message types.
- **File system**: Read and verify file contents after create/update/delete operations.

## Completion
- After all requested changes are made, verify them with read-only API calls.
- Only after that verification, call the documented supervisor completion API. Use the supervisor API docs if you do not know the exact method.
- Print the exact supervisor completion result.
- Give a brief final answer only after the completion output explicitly indicates success.
- The final text answer alone does not change world state.
