# AHE + MiniAgent + Tau3 Banking

Official DeepSeek API; Flash target/user simulator/native NL judge, Pro Worker. Two outer iterations, target concurrency 10, diagnostic concurrency 6. Frozen train/dev/test 20/15/30, seed 42. Dev-only selection chose the unchanged initial harness.

Completed evaluations: initial train 7/20 (35%); initial dev 3/15 (20%); initial sealed test 5/30 (16.666667%), including two token-limit zero scores. The selected version has the same snapshot, so its test score reuses the completed initial evaluation. Combined 65-task score is 15/65 (23.076923%). Candidate dev scores were 0/15 and 1/15; candidate training scores were 2/20 each.

The user stopped duplicate final testing on 2026-10-04 17:43 Beijing. Status remains stopped; the independent final test is incomplete and must not be described as completed. All partial final-test evidence is retained without contributing to the reported 30-task score.

logs.tar.gz preserves the full run directory, snapshots, candidate code, trajectories, caches, retry/error records, earlier status files, recovery audits, source code and split manifest. Verification checks every archive file hash, recomputes completed train/dev/test rewards, validates 65 distinct disjoint task IDs and records the dev-only selection. Credentials are redacted; private credential files are excluded. The archive excludes installed dependencies and the source dataset package, consistent with earlier archives.

Known limitations: the first evolved candidate introduced missing reasoning_content request failures, scored zero as candidate execution errors. Training task 102 initially encountered missing native judge credentials; that host configuration was corrected and the affected current cache retired with provenance preserved. Actual benchmark invocation of the replacement judge was not demonstrated on the retry because the task timed out first; a separate synthetic live check passed. Historical evaluations and failures are retained. No extra model or Worker calls were made for archival, and server records remain unchanged.
