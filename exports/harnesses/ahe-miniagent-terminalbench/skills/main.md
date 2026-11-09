# Terminal Task Skill

## Tool-use rules
- To locate content inside the working directory, prefer `shell` with
  `grep -RIn -- "<pattern>" .` (or a scoped `find ... -type f` command). Do not
  rely on recursive `list_files` alone when the repository is large: `list_files`
  returns only paths and is capped, so it can flood context without showing file
  contents.
- File-tool paths (`read_file`, `write_file`, `delete_file`) are relative to the
  task working directory, not to the most recent shell `cd`. After a shell `cd`,
  prefer absolute in-workspace paths or paths relative to the task working
  directory, and use `pwd` when unsure.
- When shell output is truncated, rerun a narrower command (`grep`, `find`,
  `head`, `tail`, or a more specific path) instead of repeating the same broad
  command.
