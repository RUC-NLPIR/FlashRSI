# OPRO / MiniAgent / SearchQA — 2026-09-25 — seed 42

Contributor: cassi

Status: finished. Official DeepSeek endpoint; target request name deepseek-v4-flash, optimizer deepseek-v4-pro. Fixed train/dev/test: 400/200/1400. Five rounds, four candidates per round, target concurrency 4, Worker serial. Final instruction selected by train hard score; no dev top-k stage.

| Metric | Initial test | Final test |
| --- | ---: | ---: |
| Official hard / EM | 77.2143% (1081/1400) | 80.7143% (1130/1400) |
| Official token F1 | 87.0186% | 88.1891% |

Paired gain: +3.50 percentage points; 82 improved, 33 regressed; paired bootstrap 95% interval [+2.00, +5.00] pp (seed 42, 2000 resamples). Single optimization seed; not a multi-seed result.

## Execution and recovery

Initial code commit: eabdb44. First recovery: 66216ee. Second recovery: 625409a. Source archives and environment versions are retained under run/evidence in logs.tar.gz. Packaging commit is not a substitute for execution versions.

Base target budget: 16384 tokens, timeout 300 seconds, high reasoning. The experiment was interrupted twice. Declared recovery added a 32768-token attempt on truncation, then 600-second attempts for truncation/timeout/empty answers. The second policy persists a maximum of two additional attempts per logical task. Existing successful calls were reused without modification. Policy migrations, previous plans and cache-prefix checksums are preserved. This is NOT an all-32k run or an unchanged historical SkillOpt setup.

All 20 candidates were evaluated. Both final test passes contain the same 1400 unique fixed IDs; hard/F1 were independently recomputed. The verification is under run/evidence/submission-verification.json. No new model calls were made while packaging.

Usage: 11200 successful target task records, 20 successful Worker records and 22 failed records. Recorded input tokens: 22652816; output: 3683935; cache reads: 9296640 (a subset of input). One usage entry lacks complete token data. Provider billing is unavailable. Counts are not necessarily physical API-call counts.

The root error.json and older attempt errors are retained historical failures; final miniagent/status.json and result.json are finished. Recovery logs are separate files. No failure records were deleted.

## Submission layout

- configs/: saved configuration, plan and dataset manifest.
- summaries/: results and usage summaries, including historical attempts.
- logs.tar.gz: complete persisted run records, including trajectories, snapshots, canonical cache, errors, retries, final prompt files and provenance. Transient working/locks are excluded by the repository packager.
- manifest.json: archive SHA256, bytes, file count, packaging version and exclusions.

Final optimized object is prompts/system.md; final_skills/ also exports other prompt/skill files. A single final promotion is not a count of proposed candidates.

This is the full archival submission, not the compact SkillOpt-style presentation export: no new comparison plots or prediction CSV are claimed. The archive must use Git LFS; other files use ordinary Git. Original paths/endpoints and source dataset content are preserved; credentials were scanned, including decoded snapshot content. Review before public release. No commit or push performed by packaging.
