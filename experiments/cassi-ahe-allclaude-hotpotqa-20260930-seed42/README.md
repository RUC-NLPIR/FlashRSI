# AHE + Claude Code + HotpotQA — seed42

Completed on rsidind. Both Target and Worker use Claude Code. Frozen train/dev/test: 150/300/300; five AHE steps; dev selects the final version, test is not used for selection.

| Metric | Initial | Final |
| --- | ---: | ---: |
| Answer EM | 50.00% | 51.00% |
| Answer F1 | 67.5090% | 66.5198% |
| Finished test executions | 300/300 | 300/300 |

Paired EM change: +1 percentage point; 19 improved, 16 regressed. Paired bootstrap 95% interval: [-3,+5] percentage points. This single-seed result does not establish a reliable improvement; F1 decreased.

Target: 32768 tokens, 600 seconds, 10 turns. Worker: 65536 tokens; diagnosis 10 turns/900 seconds, editing 100 turns/1200 seconds. Execution failures are not scored zero.

The complete server run is retained in logs.tar.gz and extracted under full/. All 3421 file hashes and the archive SHA256 were verified locally. See manifest.json and files.sha256.json. Original configuration, snapshots, working files, caches, trajectories, frozen data and logs are preserved. No models were called during archival and nothing was pushed to GitHub.

Archive SHA256: b6700cbb5f1a6ef6745a41f184be3b43982fe6641c0a9a21f2095a2bbf03f63d


## GitHub package

The full persisted run is stored in `logs.tar.gz` with Git LFS. The extracted `full/` and `source/` directories remain in the local archive and are not duplicated in Git. `result.json`, `selection.json`, `plan.json`, and `data-manifest.json` are included here for direct review. The manifest and `files.sha256.json` record archive and extracted-file checksums.
