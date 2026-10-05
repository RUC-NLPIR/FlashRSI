# GEPA + Claude Code + HotpotQA — 2026-10-03 — seed 42

Status: finished. Official DeepSeek API, target deepseek-flash, worker deepseek-v4-pro; 1 epoch. Train/dev/test: 150/300/300. Target concurrency 4; Worker serial. Test was sealed until dev selection was saved.

| Metric | Initial test | Final test |
| --- | ---: | ---: |
| Exact match | 49.3333% | 53.3333% |
| F1 | 65.3135% | 68.3203% |

Both test passes contain 300 finished tasks. Paired change: +4 percentage points; 27 improved, 15 regressed; bootstrap 95% interval [0, 8.3333] pp. Single optimization seed.

Started: 2026-10-03 13:47:41 Beijing. Finished: 2026-10-03 15:39:18 Beijing. Optimization metric calls: 4707 (not provider API-call count).

Archive format matches recent runs:

- `logs.tar.gz`: full persisted run, configs, snapshots, trajectories, canonical cache, errors, logs, seed and isolated source available at download.
- `result.json`: original final results.
- `file-manifest.json`: file sizes, hashes and credential-redaction markers.
- `verification.json`: archive and file verification, independently recomputed test scores, identical unique task order.

Verified 5617 files; archive SHA256 `38a75b6ce94a04682b1ddaaa3b1ffffc65281eb346ec953b4f56bda05a135a5e`. Credentials redacted. Remote original records were not modified. Source was collected at download; the original plan does not supply a complete per-source hash map.

Remote root: `/root/blockdata/gepa-claude_code-hotpotqa-20261003-134710-686480`, rsi002.

Budget/infra policy: time, token and turn limits score zero; infrastructure errors retry until a terminal outcome. Test never used for selection.
