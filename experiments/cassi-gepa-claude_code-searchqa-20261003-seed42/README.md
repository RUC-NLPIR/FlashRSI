# GEPA + Claude Code + SearchQA

Completed on rsi002 using the official DeepSeek API. One epoch; frozen train/dev/test 400/200/1400; seed 42. Target Flash concurrency 8; Worker Pro with serial calls. Dev-only selection; sealed test; no previous run cache reused.

Test hard / exact match: 75.142857% -> 82.428571% (+7.285714 percentage points). F1: 85.568416% -> 89.414116%. All 1400 tasks scored; initial 1400 finished, final 1399 finished. Paired bootstrap 95% interval: [5.642857, 8.928571] percentage points. Improved tasks: 124; regressed tasks: 22.

Started at 2026-10-03 19:35:01; completed at 2026-10-03 22:51:10 China time. Duration approximately 3 hours 16 minutes 10 seconds.

logs.tar.gz contains the complete experiment run and isolated runtime source, with credentials redacted. Transient verification-tests fixtures are excluded; verification-tests.log is retained. verification.json records per-file hashes and independently recomputed test metrics; initial/final task order is checked. runtime-source-manifest.json records the runtime source hashes before launch.
