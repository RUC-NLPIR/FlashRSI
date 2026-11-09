---
name: terminal
description: Use for terminal task execution in this experiment.
---

# Terminal Task Skill

## Terminal task execution rules

### Investigate before writing the deliverable
- List and read all input files, inspect formats/schemas/dtypes, and check tool versions before coding.
- The shell working directory may reset between Bash calls; use `cd <dir> && ...` or absolute paths in each command.
- Create small experiments under `/tmp` before modifying required or existing output paths.

### Verify compiler/tool behavior empirically
- When syntax, lexer/translation-phase behavior, or tool flags are uncertain, write minimal reproduction files and compile/run them with the exact required tool and flags.
- Use the exact required invocation, including working directory and output paths, not just a similar command.
- Prefer solutions that build cleanly with zero warnings/errors, and test edge cases beyond the example input.

### Data-processing tasks
- Inspect actual source rows, column names, and dtypes before defining field mappings.
- Define explicit per-source field mappings and source priority; normalize dates to `YYYY-MM-DD` and IDs to integer types where required.
- Write a standalone reproducible script, write outputs to the required paths, then read back and verify schemas, dtypes, row counts, and sample values.
- Flag ambiguous mappings and document the chosen interpretation instead of silently adding extra fields.

### Final verification
- Re-run the exact required entry point or commands at the end.
- Programmatically inspect output files to confirm schemas, dtypes, and values match the requirements.
- Clean up intermediate build artifacts unless they are required deliverables.

## Reusable service/inference task workflow

### 1. Environment and dependency recon
- Check runtime versions and installed packages before coding: `python3 --version`, `pip3 list`, and verify relevant imports with `python3 -c '...'`.
- Prefer already installed packages; install missing pieces system-wide only when the task permits.

### 2. Download artifacts to the exact required directory
- Create parent directories first with `mkdir -p`.
- For Hugging Face models, use `snapshot_download(repo_id=..., local_dir=<required target>)` and then `ls -la` the result to confirm required files are present.
- Verify the artifact loads and performs a minimal inference/default operation before building the surrounding service.

### 3. Robust service implementation
- Load the model or heavy resource once at module startup, not once per request.
- Guard inference calls with a lock (e.g. `threading.Lock`) when the backing model may not be thread-safe under a threaded server.
- Validate JSON request bodies explicitly: get JSON silently, require an object, check required fields exist and have the correct type, and reject empty or whitespace-only strings with a 400 JSON error.
- To obtain all class probabilities from a pipeline, use `top_k=None`, normalize labels, and choose the highest score if the task needs a single result.

### 4. Run in the background
- Use `nohup python3 <script>.py > <logfile> 2>&1 & echo $!` to start the service and capture the PID.
- Sleep briefly and read the log to confirm it is serving on the requested host and port.

### 5. Verify externally
- Exercise required success cases and representative error cases with `curl -s -w ' [HTTP %{http_code}]'`.
- Confirm binding to all interfaces with `/proc/net/tcp` or `ss -ltnp`/`netstat -ltnp`. In `/proc/net/tcp`, hex local address `00000000` and state `0A` mean LISTEN on `0.0.0.0`.
- If `ps` is unavailable, identify the service process via `/proc/[0-9]*/cmdline`.

### 6. Network/proxy pitfalls
- An HTTP proxy can intercept curl requests to the container's own non-loopback IP. For direct local-service checks, bypass it with `--noproxy '*'` or use loopback when that is sufficient.

## Binary and structured-file recovery

- Inspect target artifacts before changing anything: `ls -la`, `stat -c%s`, and use available dump tools. If `file` or `xxd` are missing, fall back to `od -A d -t x1z` or Python `open(path,'rb').read()`.
- Locate nonzero byte ranges first; this shows where salvageable data actually lives and prevents misinterpreting zero padding as content.
- Use Python stdlib (`struct`, `int.from_bytes`, custom varint readers) to parse binary headers, offsets, pointers, and typed records when native tools cannot open the corrupted file.
- Treat manually parsed records as hypotheses. Reconstruct a minimal valid container under `/tmp`, graft recovered bytes into it, and verify using the native tool's integrity check before writing final output.
- Preserve original scalar types when regenerating JSON output: keep integers as integers and floating-point values as floats.
- Write final artifacts only to the required absolute path after validation, then re-read the file to confirm it parses and contains the expected data.

## Environment fallbacks

- If a diagnostic command is unavailable, prefer stdlib/coreutil fallbacks (e.g. Python one-liners) over installing extra packages.


## Performance-optimization and verifier-aware timing

- Locate and read grading test files (e.g. `/tests`, `test_*.py`) before finalizing a performance task. They often define exact thresholds against a hidden golden/reference implementation, not just correctness.
- For runtime comparisons, follow the grader's methodology: warm the implementations, alternate trials, and compare median/min wall-clock times. Do not rely on a single cold run.
- When a prompt asks for an implementation to be 'as efficient as possible', do not stop after the first large speedup. Produce several equivalent rewrites, time them under the same conditions, and submit the fastest verified-correct one.
- For SQL query optimization, pre-aggregate large tables once, filter early, avoid correlated subqueries that rescan per row, and join small descriptive tables only after row counts are reduced. Avoid materializing unnecessary intermediate rows when the final output is small.
- Time the final artifact on the original unmodified input/database; graders usually do not use your scratch indexed copies.
