# AHE / MiniAgent / SearchQA — 2026-09-29 — seed 42

Contributor: cassi. Status: finished. Machine: rsidind.

Frozen train/dev/test: 400/200/1400, seed 42. Five editing steps; final version selected on dev, test not used for selection. Target budget: 16384 tokens, 10 turns, 300 seconds, concurrency 4. Diagnosis: 32768 tokens, 10 turns, 600 seconds. Editing: 32768 tokens, 100 turns, 1200 seconds. Evidence limit: 30000 characters.

| Metric | Initial test | Final test |
| --- | ---: | ---: |
| Official hard | 73.50% | 78.5714% |
| Official F1 | 83.3190% | 87.5689% |
| Completed executions | 1343/1400 | 1400/1400 |

Recorded paired gain: +5.0714 percentage points; 152 improved, 81 regressed. Paired bootstrap 95% interval: [+3.0714, +7.1429] pp. This is a single optimization seed.

## Recovery and interpretation

The original baseline is retained, including 57 execution failures under the historical two-failures-score-zero policy. Candidate evaluation was interrupted, invalidated twice, and resumed. Provider configuration changed during the experiment; the final candidate used the official endpoint while the baseline retains earlier gateway records. The process loaded the historical scoring policy before the later source patch; the final 1400 executions all completed, so no final error-zero outcomes were needed. These results are not a clean, unchanged-provider comparison; the observed gain includes the differing execution conditions.

## Local archive

- `logs.tar.gz`: complete sanitized run and execution source, including historical attempts, invalidated evidence, canonical cache, trajectories, snapshots, configuration and logs; process lock excluded.
- `full/`: extracted experiment records.
- `source/`: archived Python source.
- `files.sha256.json`: checksums of 7677 archived run/source files, all verified locally.
- `manifest.json`: archive SHA256, byte count and verification status.
- `archive-notes.json`: provenance and caveats.

Credentials were redacted and scanned. No new model calls, commit or GitHub push were performed during archival.


## GitHub package

The full persisted run is stored in `logs.tar.gz` with Git LFS. The extracted `full/` and `source/` directories remain in the local archive and are not duplicated in Git. `result.json`, `selection.json`, `plan.json`, and `data-manifest.json` are included here for direct review. The manifest and `files.sha256.json` record archive and extracted-file checksums.
