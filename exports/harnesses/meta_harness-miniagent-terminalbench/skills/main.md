# Terminal Task Skill

Use the shell tool as your hands in a real Linux-like environment. This skill contains reusable patterns that prevent common failures.

## Shell tool contract
- Input: `command`, optional `cwd`, optional `timeout`.
- Output is a JSON object: `exit_code`, `output` (stdout and stderr combined), `timed_out`, `truncated`.
- Output is capped at 32 KiB. `truncated: true` means you are missing text; rerun with `head`, `tail`, `grep`, or `sed` to narrow the result.
- Each call starts a fresh shell: no persisted working directory or environment.

## Reconnaissance patterns
- `pwd && ls -la`
- `find . -maxdepth 3 -type f | sort | head -100`
- `find . -maxdepth 3 -type d | sort | head -50`
- `grep -Rni "pattern" . --include="*" 2>/dev/null | head -50`
- `file path` or `wc -l path`

## Reading files
- `sed -n '1,120p' path` — first 120 lines
- `tail -n 80 path` — last 80 lines
- `grep -n "term" path` — matching lines with line numbers
- `cat path` only when the file is small or you need the whole content.

## Making changes
Only modify the environment when the task explicitly asks for a change. Prefer the supplied file-editing tools when they are available. From the shell, use a quoted heredoc and then verify:

```sh
cat > path/to/file <<'EOF'
...
EOF
grep -n "expected" path/to/file
```

## Web research
- Use `web_search` only when the local environment cannot answer the question. Start with one specific query rather than several broad ones.
- Use `read_url` only for promising results, and always pass a narrow `focus`.
- If web tools are unavailable or fail, do not loop on them; fall back to local evidence and note the limitation.

## Pitfalls to avoid
- Do not run interactive commands: `vim`, `nano`, `less`, `more`, `top`, `htop`, `watch`, `ssh`, `su`, bare `bash`/`python`/`python3`.
- Do not run a command that waits for input. Use non-interactive flags (`apt-get install -y`, `git commit -m "msg"`).
- Quote patterns and heredoc markers to avoid shell expansion.
- Do not rely on `cd` persisting. Use `cwd` or `cd X && ...`.
- If a command times out, simplify it or increase `timeout`; do not blindly repeat the same timed-out command.

## Verification
- After any change, verify with a read-only command.
- For Python syntax: `python3 -m py_compile path`.
- For shell scripts: `sh -n path`.
- For JSON: `python3 -m json.tool path`.

## Answering
- Answer the original question, not a description of your process.
- If the task asks for a file edit, verify the edit and then summarize the change.
- If asked to retrieve a value, return just that value when the task specifies an output format.
