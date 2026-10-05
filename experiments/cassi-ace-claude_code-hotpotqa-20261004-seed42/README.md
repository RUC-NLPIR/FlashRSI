# ACE + Claude Code + HotpotQA

Official DeepSeek API. One epoch; seed 42; target concurrency 12; Worker serial. Frozen train/dev/test 150/300/300; dev-only selection and sealed test. Completed 2026-10-04 03:38:26 Beijing.

Test exact match: 49.333333% -> 55.000000% (+5.666667 percentage points). F1: 66.555601% -> 69.374438%. Both evaluations contain 300 normally finished tasks. Paired bootstrap 95% interval: [2.333333, 9.333333] percentage points.

logs.tar.gz contains the complete experiment records, cache, snapshots, trajectories, logs and runtime source. Transient verification-test fixtures are excluded. verification.json records verified file hashes, independently recomputed test metrics and matching paired task order. Credentials are redacted. Previous gateway archive remains separate and unchanged.

The directory date is the Beijing completion date; the original run directory and timestamps are preserved inside the archive.