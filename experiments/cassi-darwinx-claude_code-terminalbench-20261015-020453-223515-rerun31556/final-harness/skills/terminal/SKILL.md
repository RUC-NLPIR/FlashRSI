---
name: terminal
description: Use for terminal task execution in this experiment. General playbook for filesystem, data, build, database, and simulation tasks.
---

# Terminal Task Skill

This skill contains general, task-agnostic strategies for terminal work. Follow the
sections that apply; skip the rest. Keep changes minimal and reversible, and never
modify verifier/test files or fabricate outputs.

## 0. Orient before acting
- Read the whole prompt and identify: inputs, required outputs, exact output paths
  and formats, and any supplied tests/verifiers.
- Run `ls -la`, `find . -maxdepth 2 -type f | sort`, and `git status --short` when
  a repo is present. Check hidden files and symlinks.
- Do not hard-code task IDs or answers; derive the result from the supplied inputs.

## 1. Prefer small deterministic scripts
- Use Python 3 with the standard library for parsing, counting, date math, and text
  transformations. Write a script file and run it rather than relying on long,
  brittle shell pipelines.
- Use `datetime`/`timedelta` for date ranges; end dates are usually inclusive.
- Write text as UTF-8; use `csv.writer` for CSV; preserve the required header and
  row order exactly.
- Keep scripts in the working directory unless a different location is requested.

## 2. Data conversion and text generation
- Parse input with `encoding="utf-8", errors="replace"`; handle empty input and
  malformed lines without crashing.
- Preserve record order. When converting a structured format (e.g., G-code), keep
  modal state and emit one deterministic output unit per command. For G-code,
  common codes include G0/G1 (rapid/linear move), G2/G3 (arcs), G90/G91
  (absolute/relative), and M-codes; comments commonly use `;` or `(...)`.
- Validate by counting input and output records and checking the output format
  against the specification.

## 3. Build, cross-compilation, and polyglot source
- Inventory toolchains first: `command -v gcc g++ make cmake rustc cargo pkg-config`
  and print versions.
- Cross-compiling: locate an installed toolchain
  (`ls /usr/bin/*-linux-gnu-gcc`, `apt-cache search '^gcc-.*-linux-gnu$'`), set
  `CC`/`CXX`/`AR`/`STRIP` and `--host=...`/`--target=...`; build out-of-tree and
  capture the full build log.
- Install missing packages only when the task requires them and network access is
  permitted; use the smallest package set that satisfies the build.
- Polyglot single-file code: use constructs valid in all target languages (such as
  block comments), isolate language-specific lines so each compiler sees valid
  syntax, and verify by compiling/running with every required toolchain.

## 4. Database and query-rewriting tasks
- Inspect schema first: `sqlite3 <db> ".schema"` or `PRAGMA table_info(<table>)`;
  count rows before changing data.
- Use `EXPLAIN QUERY PLAN` (SQLite) or `EXPLAIN` (other DB) before and after
  rewriting; add only indexes the plan actually uses.
- Rewrites must preserve exact semantics and column/row order; diff old vs new
  results before finishing.

## 5. Simulation or tournament tasks
- Run the simulator/tournament many times and use aggregate metrics, not a single
  lucky run.
- Place generated code/artifacts at the exact requested path and keep a copy of the
  best candidate.

## 6. Verify before finishing
- Run any supplied test command; otherwise write a quick independent check.
- Inspect required outputs (`ls -la`, `head`, `tail`, `wc -l`) and re-run to confirm
  determinism.
- Prefer adding files/scripts over modifying shared configuration.
