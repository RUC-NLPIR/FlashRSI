---
name: appworld-file-system-access
description: Use for AppWorld tasks that reference files or directories (e.g. "~/bills/") whose data lives inside the simulated file_system app; skip host-shell filesystem probing and read via the file_system app API after fetching credentials.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [76f2c72_2]
---
When an AppWorld task references a file or directory path (e.g. "~/bills/"):

1. Recognize that the data lives in the simulated `file_system` app, not the host shell. Host `ls`/`find` on such paths returns "No such file or directory"; do not burn turns probing `/`, `/home`, `whoami`, or `echo $HOME`.
2. Retrieve credentials first from the supervisor: call `show_account_passwords` via the appworld client.
3. Read the relevant app docs up front: `docs file_system` (plus `docs supervisor`) and `metadata` to learn the exact call names.
4. Read the file/directory through the file_system API (e.g. `show_directory`/`show_file`) using the retrieved credentials.
5. Only then act on the returned contents as the task requests.

Trigger check: if the session exposes AppWorld tools (appworld_client `metadata`/`docs`/`execute`) and a mentioned path is absent from the host filesystem, go straight to the app API instead of probing the shell.
