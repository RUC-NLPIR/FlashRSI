---
name: appworld-spotify-show-song-fields
description: >-
  AppWorld Spotify tasks that filter library or playlist songs by release date.
  Use when show_song_library or show_playlist_library returns song IDs without
  release dates and the plan is to call show_song per song.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [ce359b5_3]
---
# AppWorld Spotify: inspect show_song before per-song date filtering

When filtering library/playlist songs by release year, do not guess
`show_song` response fields.

## Rules
- `show_song_library` and `show_playlist_library` return song IDs without the
  per-song release date; call `show_song` for each song.
- Inspect one sample `show_song` response before writing the loop:
```python
print(apis.spotify.show_song(song_id=<sample_id>))
```
- Do not assume fields such as `album_title`. A sample may contain `album_id`
  but no `album_title`.
- Access only keys observed in the sample and documented keys such as
  `album_id` and `release_date`.
- If a loop raises `KeyError` for a guessed key, re-inspect the sample and
  switch to the actual keys before rerunning the full loop.

## Verification
Before answering, confirm the per-song loop used keys that are present in a
printed sample response. If any `KeyError` occurred, verify the replacement
keys appear in the sample.
