# SkillOpt + Claude Code + Tau3 Banking

Official DeepSeek API; Flash target, Pro Worker. Two epochs; seed 42; target concurrency 10, Worker concurrency 4. Frozen train/dev/test 20/15/30. Candidate selection uses dev only; sealed test was not used for selection. The selected snapshot equals the initial snapshot.

Test reward: initial 7/30 = 23.333333%; final 6/30 = 20%; change -3.333333 percentage points. All 30 tasks scored in each evaluation. Normally finished trajectories: initial 29/30, final 30/30. The initial non-finished trajectory retains its original zero score.

Final task cache was complete when the development container restarted on 2026-10-04 02:52:40 Beijing. The last task log was 02:52:30; the final aggregate had not been written. Offline aggregation was recovered on 2026-10-04 using the original simulator rewards, paired task IDs and checksums, with zero new model or Worker calls. The actual cause of the container restart remains unconfirmed.

logs.tar.gz contains the complete experiment directory, earlier attempts, snapshots, trajectories, canonical caches, usage summary, runtime source and recovery provenance. Credentials are redacted. verification.json records archive and per-file hashes, independently recomputed test metrics and matching initial/final task order.

The directory date is the Beijing aggregation recovery date. Original experiment timestamps remain in the archive. Recovery model/Worker call counts are zero; this does not mean the original training used zero calls. Server records remain preserved.


完整日志分卷存储于 Git LFS；按文件名顺序合并后 SHA256 与 manifest 一致：

```bash
cat logs.tar.gz.part* > logs.tar.gz
```
