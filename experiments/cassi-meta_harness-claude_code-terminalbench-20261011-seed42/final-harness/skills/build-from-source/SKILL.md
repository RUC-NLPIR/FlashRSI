---
name: build-from-source
description: Use for tasks that require compiling, building, cross-compiling, porting, or repairing an existing codebase — "build X from source", "fix the build", "port to Y", "get the tests green". A failure-first protocol that avoids thrashing on long builds.
---

# Build / port / repair protocol

Long builds fail when the agent thrashes — retrying the same command or guessing
at an error. Follow this order.

1. **Read the build docs first.** Find `HACKING.*`, `README*`, `INSTALL*`,
   `Makefile` targets, and CI config. Identify the exact configure / build /
   test commands and required toolchain versions.

2. **Install dependencies once, non-interactively.**
   `DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y <pkgs>`.
   Confirm tools are on PATH before building.

3. **Configure → build → test, one stage at a time, capturing the FIRST error.**
   Use `make -j$(nproc)`. Tee the log: `<cmd> 2>&1 | tee /tmp/build.log`. The
   first error is the real one; later lines are fallout.

4. **Watch memory on parallel builds.** `-j$(nproc)` can exhaust RAM and get the
   build `Killed` with no compiler error (common with Coq/OCaml/LLVM builds). If
   the build dies without an error message, re-run at `-j4` and monitor
   `free -h`. A slower build that finishes beats a fast build that OOMs.

5. **Cross-compiling to another target/architecture:** install the matching
   toolchain (e.g. `apt-get install -y gcc-mips-linux-gnu`) and make the build
   use it — set `CC`/`CXX`/`LD`, or the project's `--host`/`--target`/
   `CROSS_COMPILE` variables — instead of silently producing a host binary.
   Verify the output with `file` (it must report the target architecture, e.g.
   `ELF 32-bit … MIPS`).

6. **Reproduce the stated failure with the exact command before changing
   anything**, so you have a baseline to compare against.

7. **Change one thing at a time**, rebuild, check. If a fix does not change the
   error, revert it — do not stack guesses.

8. **Verify with the task's stated acceptance command** (the specific test
   target or binary invocation), not a proxy.

9. **Checkpoint long builds** — write a small script so a re-run resumes from
   the last successful stage instead of restarting from zero.
