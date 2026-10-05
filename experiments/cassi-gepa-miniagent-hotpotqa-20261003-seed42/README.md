# GEPA + MiniAgent + HotpotQA — 2026-10-03 — seed 42

Status: finished. Official DeepSeek API, target deepseek-flash, worker deepseek-v4-pro; 1 epoch. Train/dev/test: 150/300/300. Target concurrency 4; Worker serial. Reflection includes answer, trajectory and evaluation feedback without supporting-fact annotations. Test was sealed until dev selection was saved.

| Metric | Initial test | Final test |
| --- | ---: | ---: |
| Exact match | 55.0000% | 52.0000% |
| F1 | 71.5732% | 67.6344% |
| Finished trajectories | 300/300 | 296/300 |

All 300 tasks are scored in both passes; final non-finished trajectories remain zero-score outcomes and are listed in verification.json. Paired change: -3 percentage points; 20 improved, 29 regressed; bootstrap 95% interval [-7.6667, 1.6667] pp. Single optimization seed.

Started: 2026-10-03 11:02:06 Beijing. Finished: 2026-10-03 13:30:33 Beijing. Optimization metric calls: 5016 (not provider API-call count).

Archive format matches recent runs:

- `logs.tar.gz`: full persisted run, configs, snapshots, trajectories, canonical cache, errors, logs, seed and isolated source available at download.
- `result.json`: original final results.
- `file-manifest.json`: file sizes, hashes and credential-redaction markers.
- `verification.json`: archive and file verification, independently recomputed test scores, identical unique task order.

Verified 5963 files; archive SHA256 `9808efdd8362a8e5c1fdc3f1b5d905f735812408bdbfdbc75742f7bdb7ab6800`. Credentials redacted. Remote original records were not modified. Source was collected at download; the original plan does not supply a complete per-source hash map.

Remote root: `/root/blockdata/gepa-miniagent-hotpotqa-20261003-110108-361079`, rsi002. This archive is the completed official-API run on October 3, not the earlier gateway experiments.

Budget/infra policy: time, token and turn limits score zero; infrastructure errors retry until a terminal outcome. Test never used for selection.
