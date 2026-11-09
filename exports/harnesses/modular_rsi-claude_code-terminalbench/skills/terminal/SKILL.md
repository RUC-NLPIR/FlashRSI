---
name: terminal
description: Optional general Terminal task workflow instructions.
---

Scope terminal/CLI work to the literal task.

- Interpret "sanitize", "remove", or "replace X" in a repository or files as working-tree edits to the repository's current state. Do not expand the task into rewriting history or touching commits the task never named.
- Treat destructive or hard-to-reverse commands as out of scope unless the task explicitly and unambiguously requires them. This includes, but is not limited to: `git filter-branch` / `git filter-repo`, `git reset --hard`, force-pushing, deleting `refs/original`, `git reflog expire`, `git gc --prune`, and `rm -rf`.
- When such an operation would be needed to fully meet a task, make the minimal in-place change instead, verify it, and report the destructive option to the user rather than performing it. If the task explicitly and unambiguously requires the destructive command, make a recoverable backup of the affected state first, and verify the acceptance criterion against the pristine, unmodified input.

Write answer files as the bare value.

- When a task asks you to write an answer to a file, write exactly the requested value to that file: the bare string, integer, or secret with no prose, no markdown, no "Answer:" header, and no trailing newline unless the task explicitly requires them.
- Keep all reasoning and explanation in the transcript, never inside the artifact file.
- After writing, read the file back and verify its exact contents match the requested value and format before reporting success.
- When the value must be extracted or decoded from a file, confirm the extraction with an independent method and sanity-check it against the expected shape rather than trusting a single fragile (e.g. manual or visual) interpretation.

Verify against the grader's exact conditions, not proxies.

- Before reporting a terminal/CLI solution as correct, run the task's literal command lines verbatim — full absolute paths, exact flags, output names, and the stated tool versions — and observe their exit codes and output. Do not substitute simplified relative-path invocations or a different toolchain version.
- When the requirement is "same output as X", make X actually runnable on the unmodified input by raising the timeout or patience, or by streaming its results; capture its real output, then diff the final artifact's actual output byte-for-byte against it. Do not verify against a modified copy of the input, and do not assert equivalence from reasoning about ordering or uniqueness. Adding indexes is a mutation that can change the query plan and silently reorder rows for any result without a complete deterministic ORDER BY, so use it only as a last resort and, if you do, sort both sides with an explicit total ordering that fully resolves ties before comparing.
