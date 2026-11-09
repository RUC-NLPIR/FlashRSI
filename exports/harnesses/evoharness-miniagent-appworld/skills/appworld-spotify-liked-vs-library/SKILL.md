---
name: appworld-spotify-liked-vs-library
description: >-
  AppWorld Spotify tasks that ask about the album library, liked playlists,
  "my playlists", or "my song library and playlists". Use when wording
  distinguishes album library from liked albums, uses a relative clause such as
  "playlists which I have liked", or when a destructive cleanup scope may
  require liked playlists in addition to owned library playlists.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [ce359b5_2]
---
# AppWorld Spotify: liked vs library vs private flags

Resolve the exact target set before collecting, ranking, rating, or removing
songs.

## Album library vs liked albums
When the task says "my album library":
- `show_liked_albums` is NOT the album library; it returns liked/saved albums.
- Call `show_album_privates` and inspect `in_album_library` for each album.
- Collect songs only from albums where `in_album_library == true`.

## Liked playlists vs liked songs
When the phrase is "songs in my playlists which I have liked":
- The relative clause "which I have liked" attaches to "playlists", not "songs".
- Call `show_liked_playlists` and expand each liked playlist's songs.
- Do NOT intersect `show_liked_songs` with `show_playlist_library`.

## Playlist scope for "my playlists"
- For read-only tasks ("my playlists", "any of my playlists"), default to the
  supervisor's own library playlists from `show_playlist_library`. Do not
  auto-union `show_liked_playlists`; liked playlists may be owned by others.
- For destructive cleanup/removal tasks phrased "my song library and
  playlists", enumerate BOTH `show_playlist_library` and
  `show_liked_playlists`, expand each returned playlist's `song_ids`, and
  operate on the union of those playlist surfaces. Restricting this scope to
  owned library playlists alone misses liked-playlist songs and leaves
  violations.
- Use `show_liked_playlists` whenever the task explicitly asks about liked or
  saved playlists.

## Verification
Before answering, re-read the task and confirm the target set matches the exact
wording: album library vs liked albums; liked playlists vs liked songs; and for
"my playlists", owned-library default for read-only tasks but union of library
and liked playlists for destructive cleanup scopes. If the set came from a
same-sounding API or an automatic union/default, re-derive it.
