---
name: install-required-runtime-and-artifact
description: Use when a terminal coding task explicitly names a required language/runtime and a required implementation or output file path, and the verifier tests assert that file exists.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [gcode-to-text]
---
# Install required runtime and create/verify the required file first

When a task requires a runtime and a fixed file path (an implementation file like `/app/ars.R` or a generated answer file like `/app/out.txt`), satisfy those requirements before doing unrelated setup or running verifier tests.

Procedure:
1. Check for the required runtime and install it if missing:
   ```bash
   command -v Rscript || { apt-get update && apt-get install -y r-base-core; }
   ```
   Adapt the package/install command to the named runtime (python, node, R, etc.).
2. For a required implementation file, create it immediately and write the implementation into that exact path:
   ```bash
   mkdir -p /app
   touch /app/ars.R
   ```
3. For a required generated output file, produce it from the implementation and verify it exists before spending remaining time on optional dependencies or verifier runs:
   ```bash
   mkdir -p /app
   # run the solution, then:
   test -s /app/out.txt && wc -l /app/out.txt
   ```
4. Only after the required runtime and file exist should you perform optional setup such as installing curl, openssl, or uv, or run the verifier.

Why: verifier failures are often simply `No ars.R file found`, `FileNotFoundError: Rscript`, or `/app/out.txt` missing. In gcode-to-text the verifier failed both tests with reward 0.0 because `/app/out.txt` was never produced while time was spent installing packages and running pytest. Create required implementation files and verify generated output files before running the verifier.

Supporting evidence: gcode-to-text (this batch).
