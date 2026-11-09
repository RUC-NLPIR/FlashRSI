---
name: appworld-spotify-set-based-aggregate-verification
description: >-
  AppWorld Spotify cleanup or bulk tasks where an aggregate state such as "an
  album is downloaded iff every song in it is downloaded" determines keep or
  remove decisions. Use when printed ID lists could be misread and per-item
  downloaded counts must be exact.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [229360a_1]
---
# AppWorld Spotify: verify aggregate ID membership with sets

When keep/remove decisions depend on every member of a collection having a
property, do not eyeball a printed ID list.

## Rules
- Build the downloaded/property ID set once from the returned list.
- Check each album or playlist against that set programmatically:
```python
downloaded = set(downloaded_song_ids)
for album_id, song_ids in albums.items():
    all_downloaded = set(song_ids).issubset(downloaded)
    downloaded_count = len(set(song_ids) & downloaded)
```
- Use set intersection/subset for membership checks. A printed list such as
  `[4, 8, 19, 21, 23, ...]` is easy to misread; do not classify by eye.
- Recompute any per-item downloaded counts from the sets, not from memory or
  earlier written reasoning.

## Verification
Before answering, rerun the set logic and confirm each all-downloaded vs
partial classification matches `issubset`, and that reported counts equal the
computed intersection sizes.
