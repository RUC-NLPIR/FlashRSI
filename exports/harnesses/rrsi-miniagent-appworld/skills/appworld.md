# AppWorld task solving

If the user's question says AppWorld tools are available through the shell
tool, apply the rules below.

## Orientation and credentials
- Start by listing apps (`appworld_client.py metadata`) and reading the docs
  for any app and API you are about to use, including
  `supervisor.complete_task`.
- Get app credentials from the supervisor password store and reuse the
  returned access token in the same execution block.

## Working with app data
- Resolve target sets from authoritative contact/relationship data (for
  example phone contacts or Venmo friend/roommate data), not from messages or
  notes alone.
- Paginate exhaustively: when a list API returns exactly `page_limit` rows,
  request the next `page_index` until a page returns fewer than `page_limit`.
- Prefer server-side sorting and filtering parameters to find min/max/target
  items instead of scanning locally.
- Treat ordered/ranked feeds as positional ranks, not frequency counts. When
  a task asks for the "most recommended" or "least recommended"
  artist/song/item from an endpoint like Spotify `show_recommendations`, the
  returned list is ordered: the first item is the top/most recommendation and
  the last item is the bottom/least recommendation. Answer from that position.
  Do not count how many times an artist or song appears across the feed.

## Before completing
- Re-read the final state of every object the task changes and check each
  task-specified postcondition explicitly (playlist visibility, exact target
  set, final library contents, sent messages, likes/comments).
- If an instruction is ambiguous, verify the intended reading by querying
  alternative authoritative views before committing to it.
- For question tasks, cross-check the concise answer against the authoritative
  ordered view (for example the first/last row of a recommendation feed)
  before calling `complete_task`.

## Completing
- Complete only through `apis.supervisor.complete_task` executed in the
  AppWorld session.
- For action tasks, call `complete_task()` and leave `answer` at its default
  `None`; never submit a descriptive summary as `answer`.
- For question tasks, call `complete_task(answer='<concise canonical answer>')`.
- Then return a one-sentence final message. Never leave an unexecuted shell or
  DSML command as the final message.
