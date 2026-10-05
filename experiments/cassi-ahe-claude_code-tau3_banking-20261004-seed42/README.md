# AHE + Claude Code + Tau3 Banking

Official DeepSeek API: Flash target, user simulator and native NL judge; Pro worker. Target and worker both Claude Code. Two outer iterations, target concurrency 10, diagnostic concurrency 6; overview and editing serial. Frozen train/dev/test 20/15/30, seed 42. Dev-only selection chose the second evolved candidate; test was not used for selection.

Initial train 7/20 (35%), dev 3/15 (20%), test 7/30 (23.333333%). Selected train 7/20 (35%), dev 4/15 (26.666667%), test 6/30 (20%). Test delta -3.333333 percentage points. Initial and final tests were independently evaluated, with 30 scored tasks each. Final test includes seven token-limit zero outcomes; 23 tasks completed normally, which is not the scoring denominator.

Started 2026-10-04 18:03:11 Beijing; finished 23:08:10, about 5h05m. The process exited and status/result both report finished.

logs.tar.gz preserves the complete run records, all snapshots and evolved harness resources, trajectories, per-task records, cache, retries, budget failures, configuration and selection/preflight provenance, plus source code and frozen split/data verification metadata. Credentials are redacted. Installed environments and the external dataset package are not bundled. Server records are unchanged; archival makes no model calls.

verification.json records archive SHA256, per-file checks and independently recomputed initial/final test rewards, task counts and matching task order. file-manifest.json is the detailed file hash inventory; result.json is the readable aggregate result.
