---
name: appworld-spotify-playlist-duration-not-count
description: >-
  AppWorld Spotify tasks that select or start a playlist whose total duration
  must cover a fixed activity length. Use when playlist search or library
  endpoints return song_ids without durations and the plan might treat
  len(song_ids) as a proxy for total time.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [b0a8eae_3]
---
# AppWorld Spotify: sum song durations, not song counts

When a playlist must cover a time-based duration requirement, do not use the
number of `song_ids` as a proxy for total time.

## Rules
- Playlist search/library endpoints expose `song_ids` but not per-song
  durations. For each candidate playlist, call `show_song` for each `song_id`
  and sum the durations.
- Print one sample `show_song` response first and use only the duration field
  actually returned/documented there; do not assume its name.
```python
total = sum(
    apis.spotify.show_song(song_id=sid)["<duration_field>"]
    for sid in candidate["song_ids"]
)
```
- Only select or start a playlist whose summed duration meets or exceeds the
  required duration.

## Verification
Before answering, confirm every candidate was compared by summed `show_song`
durations, not by `len(song_ids)`. If any candidate was compared by count,
recompute its total duration from actual song durations and re-check the
requirement.
