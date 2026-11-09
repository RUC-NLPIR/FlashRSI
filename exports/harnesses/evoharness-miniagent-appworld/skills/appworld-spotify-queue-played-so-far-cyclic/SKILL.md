---
name: appworld-spotify-queue-played-so-far-cyclic
description: >-
  AppWorld Spotify music-player queue tasks that ask which songs have been
  "played so far". Use when show_song_queue returns a cyclic queue with the
  current song not at the first or last position, or when a position-based
  subset of the queue is about to be used as the played set.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [ccb4494_3]
---
# AppWorld Spotify: resolve cyclic queue "played so far" semantics

Do not derive the played set from linear queue positions relative to the
current song. `show_song_queue` is documented as cyclic, so entries after the
current song in the returned order may still belong to the played set when
playback has wrapped.

## Procedure
1. Print the full `show_song_queue` response and identify the current-song
   field and each entry's position/id.
2. Treat the queue as circular. Do not auto-exclude positions after the
   current song; a wrap means they can already have been played in an earlier
   cycle.
3. Resolve the exact "played so far" set from queue semantics and endpoint
   docs before mutating. Candidate sets include the whole queue or the
   circular prefix before the current song; do not settle for
   `positions <= current_index` without evidence.
4. Apply the mutation to the resolved set only.

## Verification
Before answering, confirm no queue entry was excluded solely because it
appeared after the current song in the returned list. If any position-based
exclusion was made, re-derive the played set under cyclic semantics and rerun
the mutation.
