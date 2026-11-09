---
name: verify-build-prerequisites-before-compiling
description: Use when a task asks for a non-native compiled artifact, such as a cross-compiled MIPS ELF, in a minimal or unfamiliar container that already contains a source tree and Makefile.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [make-doom-for-mips]
---
# Verify build prerequisites before relying on an existing Makefile

For custom-runtime build targets, do not assume the checked-in Makefile is sufficient. Check the actual prerequisites before compiling.

Procedure:
1. Verify the required toolchain is actually present:
   ```bash
   which mips-linux-gnu-gcc mipsel-linux-gnu-gcc clang gcc node
   ```
   If the cross compiler is missing, install it first, e.g.:
   ```bash
   apt-get update && apt-get install -y gcc-mips-linux-gnu
   ```
2. Verify task-provided custom headers exist:
   ```bash
   find / -name 'my_stdlib.h' 2>/dev/null
   ```
   A source file that includes a missing header cannot build until that header is provided.
3. Check what the existing Makefile actually produces and link against:
   ```bash
   grep -nE '^(TARGET|OUTPUT|.*-o )|(-lX11|doomgeneric)' Makefile
   ```
   Compare that with the runtime's expected artifact name and architecture. For example, a host Makefile producing `doomgeneric` with `-lX11` will not satisfy a VM that calls `runElf("doomgeneric_mips")`.
4. Build explicitly for the requested target and output filename, or patch the Makefile so the target, compiler, and artifact name all match the runtime expectation.

Why: in this run none of the normal build assumptions held; using the repository's host Makefile would not have produced the requested artifact.

Supporting evidence: make-doom-for-mips (this batch).
