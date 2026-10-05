# GEPA + MiniAgent + SearchQA

Completed on rsi002 using the official DeepSeek API. One epoch; frozen train/dev/test 400/200/1400; seed 42. Target Flash concurrency 8; Worker Pro with serial calls. Dev-only selection; sealed test; no previous run cache reused.

Test hard / exact match: 77.50% -> 84.642857% (+7.142857 percentage points). F1: 87.025802% -> 91.303061%. All 1400 tasks scored; initial 1399 finished, final 1400 finished. Paired bootstrap 95% interval: [5.428571, 8.928571] percentage points.

logs.tar.gz contains the complete run and isolated runtime source, with credentials redacted. verification.json records per-file hashes and independently recomputed test metrics; initial/final task order matches. Completed at 2026-10-03 19:24:51 China time.
