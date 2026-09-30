# AHE + MiniAgent + HotpotQA — seed 42

Completed on rsidind. Frozen train/dev/test 150/300/300; five AHE edits; dev selection with earlier tie-breaking; test not used for selection.

| Metric | Initial | Final |
| --- | ---: | ---: |
| Answer EM | 53.6667% | 51.6667% |
| Answer F1 | 69.3601% | 66.9108% |
| Finished test executions | 300/300 | 300/300 |

Paired EM change -2.00 percentage points, 21 improved and 27 regressed; paired bootstrap 95% interval [-6.6667,+2.6667] pp. Single seed. The selected candidate underperformed the initial version on test; results are preserved without reselection or rerun.

Target: deepseek-flash, 32768 tokens, 10 turns, 600s, concurrency4. MiniAgent Worker: deepseek-v4-pro, 65536 tokens, diagnosis10 turns/900s, editing100 turns/1200s. High reasoning; evidence cap30000 chars. Execution failures stop after two attempts, not scored zero.

Full run in full/, Python source in source/, complete sanitized archive logs.tar.gz. Archive SHA256 and all 3536 file hashes verified locally; manifest.json and files.sha256.json retain evidence. No model calls during archival; no GitHub push.


## GitHub package

The full persisted run is stored in `logs.tar.gz` with Git LFS. The extracted `full/` and `source/` directories remain in the local archive and are not duplicated in Git. `result.json`, `selection.json`, `plan.json`, and `data-manifest.json` are included here for direct review. The manifest and `files.sha256.json` record archive and extracted-file checksums.
