---
name: verify-embedded-version-after-fetching-source
description: Use when building a version-pinned compiler or tool from a Git tag or source archive, and the verifier or user may check the version the built tool reports.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [compile-compcert]
---
# Verify embedded version metadata after fetching a source tag

A Git tag or release name may not match the version string the built tool reports. After fetching version-pinned source, inspect the tree's own version metadata and reconcile it with the requested version before building.

Procedure:
1. List available tags and map them to the request:
   ```bash
   git ls-remote --tags <repo-url> | grep -i <requested-version>
   ```
2. After cloning or extracting, read embedded version files:
   ```bash
   cat VERSION
   head -30 Changelog.md
   grep -RIn "version" --include="VERSION" --include="*.md" . | head
   ```
3. Compare the embedded string with the requested version. A tag `v3.13.1` may identify a tree whose `VERSION` says `version=3.13` and whose Changelog head says `# Release 3.13`; the built tool would then report `3.13`, not `3.13.1`.
4. If they differ, do not assume the tag is sufficient. Confirm what the built tool will actually report, and look for the tag or tarball that embeds the exact requested version before proceeding.

Why: for CompCert 3.13.1, `git ls-remote --tags` showed `v3.13.1`, but the cloned tree had `VERSION` `version=3.13`, `Changelog.md` `# Release 3.13, 2023-07-04`, and the GitHub release name was `CompCert 3.13`.

Supporting evidence: compile-compcert (this batch).
