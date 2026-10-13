# ModularRSI + MiniAgent — Terminal-Bench

Completed on 2026-10-13, seed 42. Five-module evolution with Target concurrency 4 and Worker concurrency 1.

| Evaluation | Successes | Score |
| --- | ---: | ---: |
| Initial test | 21 / 30 | 70% |
| Final test | 21 / 30 | 70% |

Initial and selected Snapshot: `6ce261158b58d7e1b8f0f4950571452ce91415ca2efcc7eadca94d5f601c59e9`.

All integration candidates were rejected under the frozen selection protocol. The selected Snapshot equals the initial Snapshot, so final test reuses the complete initial evaluation (`independent_final_test: false`), with no additional test model calls. Test results were not used for selection.

`full-run.tar.gz` contains all 6,054 files from the completed run: per-task scores, trajectories, Worker records, snapshots, native trials, failed attempts, caches, recovery diagnostics, and integrity copies. The archive is stored with Git LFS. Runtime environments and credentials outside the run directory are not included.

The publication copy removes credential-shaped strings from historical records. The original full archive is retained locally; original source hashes and the changed-file list are recorded in `file-manifest-sha256.json`. Snapshot contents and evaluation results are unchanged. `verification.json` records the publication archive SHA256 and verification of every archived file.

This is an archive-only submission; no experiments were restarted and no model calls were made for publication.
