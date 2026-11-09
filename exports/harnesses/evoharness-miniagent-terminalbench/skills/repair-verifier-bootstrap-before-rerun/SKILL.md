---
name: repair-verifier-bootstrap-before-rerun
description: Use when a task solution produces the expected output files and local checks pass, but the verifier still reports zero reward and the captured test output shows the test harness failing before task-specific assertions.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [multi-source-data-merger]
---
# Repair verifier bootstrap failures before trusting rerun results

A zero reward is not always an output failure. If the test runner exits because a command or binary path is missing, task-specific checks never executed. Inspect the verifier output first, then repair the test harness dependency and rerun.

Procedure:
1. Separate bootstrap errors from assertion failures. Look for:
   - `command not found` or `No such file or directory`
   - a fixed binary path that does not exist (for example `/root/.local/bin/env`)
   - transport failures such as `curl: (35) TLS connect error` before setup commands run
2. Identify the missing dependency used by the test script. Common cases:
   - `uvx` or `uv` missing: install it, e.g.
     ```bash
     pip install uv
     ```
     or
     ```bash
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```
   - a toolchain command invoked through a fixed path: create the expected path or symlink after installing the real binary.
3. Make the repair visible to the test runner. Ensure the installed binary is on `PATH` for the shell that executes the tests, including `/root/.local/bin` when the harness expects tools there.
4. Confirm the task's output artifacts still exist after installing dependencies, then rerun the verifier.

Why: in one run the solver's `/app/merged_users.parquet` and `/app/conflicts.json` were correct, but the verifier exited at `uvx: command not found` and `/root/.local/bin/env: No such file or directory`, so the reward was `0.0` before any task logic was evaluated.

Supporting evidence: multi-source-data-merger (this batch).
