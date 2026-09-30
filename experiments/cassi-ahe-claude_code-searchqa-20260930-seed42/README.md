# AHE + Claude Code + SearchQA, seed 42

Completed on rsidind. Target Claude Code; AHE diagnosis/editing Worker MiniAgent. Frozen 400/200/1400 split. Five AHE editing steps; dev selects final candidate, test not used for selection.

Initial test hard: 73.9286%; final: 79.3571% (+5.4286 percentage points). Both test evaluations completed all 1400 tasks. Official F1: 84.6962% -> 87.1585%. Paired improved/regressed: 113/37; bootstrap 95% interval [+3.7143,+7.1429] pp. Single seed, not a multi-seed estimate.

Full persisted run under full/, launcher/support scripts under source/. logs.tar.gz contains the sanitized archive; files.sha256.json lists 6559 locally verified file hashes. Archive digest and byte count are in manifest.json. Credentials redacted; transient process.lock excluded. No model calls were made for archival and no GitHub push performed.


## GitHub package

The full persisted run is stored in `logs.tar.gz` with Git LFS. The extracted `full/` and `source/` directories remain in the local archive and are not duplicated in Git. `result.json`, `selection.json`, `plan.json`, and `data-manifest.json` are included here for direct review. The manifest and `files.sha256.json` record archive and extracted-file checksums.
