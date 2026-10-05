# SkillOpt + MiniAgent + Tau3 Banking

Second completed Tau3 experiment on rsi003. Official DeepSeek API; frozen train/dev/test 20/15/30, seed 42. Two epochs, target concurrency 6, task hard timeout 1200 seconds. Dev-only selection; test not used for selection.

Test reward: 10.00% -> 36.666667% (3/30 -> 11/30). All 30 tasks scored for each version. Initial 27 finished with 3 token-budget zero tasks; final 28 finished with 2 token-budget zero tasks. Completed at 2026-10-03 13:11:11 China time. Resumed execution started at 2026-10-02 22:04:55, elapsed approximately 15 hours 6 minutes.

logs.tar.gz contains the complete run, attempts, snapshots, trajectories, cache, logs, captured source, split manifest and data verification. Credentials are redacted. verification.json records archive/per-file hashes and independently recomputed test scores and task ordering.

The source is captured at download time. The run plan does not include a per-file source hash map; this archive does not prove historical source equality. The server records are unchanged.
