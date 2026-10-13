---
name: terminal
description: Use for terminal task execution in this experiment.
---

# Terminal Task Skill

Follow these best practices for every terminal task. They are general guidance,
not task-specific answers: always solve the task independently.

## 1. Orient first
- Read the whole prompt once and list the concrete deliverables: input paths,
  output paths, required formats, and any fixed facts (reference dates, ports,
  filenames, counts).
- Quickly inspect the environment before acting: list the relevant directories
  and check required tools (`python3 --version`, `gcc --version`, `make --version`,
  or `which <tool>`).

## 2. Prefer a small script
- For anything beyond a one-off command, write a short Python 3 or shell script
  and run it. Scripts are easier to verify, repeat, and correct than long shell
  pipelines.
- Prefer the Python standard library (`csv`, `json`, `re`, `sqlite3`, `pathlib`,
  `argparse`). Install third-party packages only when the task needs them.
- Stream large inputs instead of loading everything into memory.

## 3. Match the required output exactly
- Write outputs to the exact path with the exact filename requested.
- Preserve required headers, separators, ordering, and number formatting. For
  CSV, use `csv.writer` or `csv.DictWriter` rather than hand-building rows.
- Use any reference date or fixed fact exactly as supplied in the prompt.

## 4. Build and dependency tasks
- Use the project's own build system first; read README/INSTALL/build docs when
  present.
- Check the available toolchain before building. For cross builds, set standard
  variables such as `CC`, `CXX`, or `CROSS_COMPILE` to the available toolchain.
- For Python extension builds, prefer `python -m pip install -e .` or
  `python setup.py build_ext --inplace`; install missing build prerequisites
  (for example `cython`) when the task requires them and the environment permits.
- Read the first compiler/runtime error carefully and fix the root cause.

## 5. Algorithm and parsing tasks
- Implement directly from the task specification and named algorithm. Use
  numerical guards where appropriate: small epsilon, log-space arithmetic, or
  exact integer arithmetic.
- Parse structured text with an appropriate standard parser, handle blank
  lines/comments/unicode, and validate on a small example before the full input.

## 6. Bulk edits
- Use `sed -i`, `perl -pi -e`, or a Python script for repetitive or large-file
  edits instead of many individual edit calls.
- For destructive in-place edits, keep a backup or test on a copy first.

## 7. Verify before finishing
- Re-read the prompt and confirm every deliverable exists at the required path
  with the required format.
- Run a quick self-check when possible: parse the output, count records, execute
  a small test, or run the task's own test command if one is named.
- If one approach fails, simplify and retry rather than stopping early.
