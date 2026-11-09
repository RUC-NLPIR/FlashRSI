# CLAUDE.md

## General
- Invoke any skill the task requires at the start. If the skill returns no rules or content, continue solving normally.
- Solve independently from source inputs; do not search for or use hidden reference/verifier data.
- Inspect supplied inputs and expected outputs before making changes.
- Prototype on a small sample, then run the full required command.
- Verify by actually running commands and checking exit statuses, not by visual inspection.

## Vim / command-line scripting tasks
- Respect exact allowed-command restrictions: no extra lines, comments, shell escapes, or prohibited functions.
- For headless Vim, use the required invocation exactly, typically `vim -Nu NONE -n -Es ... -S ...`, and inspect the exit code.
- When storing macros with `setreg()`:
  - Double-quoted Vimscript strings interpret `\n`, `\r`, `\t`, `\b`, `\e`, `\v`, `\\`, `\"`, and `\<key>`.
  - Backslashes before non-special characters such as `\s`, `\S`, `\1`, or `\2` are not preserved as regex escapes in double-quoted strings. Double them: `\\s`, `\\S`, `\\1`, `\\2`.
  - Prefer single-quoted strings for regex literals and concatenate special keys, for example:
        call setreg('r', ':.s/\v^\s*(\S+)/\1/' . "\<CR>")
  - If the required template uses double quotes, use double backslashes for regex pieces:
        call setreg('r', ":.s/\\v^\\s*(\\S+)/\\1/\<CR>")
- If a macro replayed with `:%normal!` contains an Ex substitution, use an explicit line range such as `:.s` rather than bare `:s`; otherwise the outer `%` range can leak into the substitution.
- Count keystroke budgets from the macro register contents, not from the surrounding `setreg` wrapper. Fewer and cheaper passes over large inputs reduce runtime.

## Verification and reporting
- `grep` exit code 1 means "no matches"; if no match is the expected result, that is not a failure.
- Use `cmp` or `diff` for exact file comparison and check the command exit code.
- Re-run verification from a clean copy before reporting success.
- Report concrete evidence only: exit codes, file comparison results, and timing. Do not claim a check passed unless it was actually run.
