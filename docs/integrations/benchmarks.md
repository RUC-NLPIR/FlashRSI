# Benchmarks

Choose a task suite, then follow its configuration and environment guide. FlashRSI registers 30 suites; years, variants, and domains within one adapter count as one suite.

## Prepare the environment

| Task environment | Start here |
| --- | --- |
| Text, QA, and reasoning | [Configuration index](../benchmark-quickstart.md) for data, grading, and optional model roles. |
| Web research | [Search and reader services](../web-research-services.md). |
| Repository and container tasks | [Coding setups](../coding-working-benchmarks.md), [Terminal-Bench](../terminal-bench.md), and the native verifier guide. |
| Interactive environments | [τ²-bench](../tau2-bench.md), [ALFWorld](../alfworld.md), or the configuration index for τ³. |

Start with the [complete configuration index](../benchmark-quickstart.md) for the exact YAML example and dependencies of each adapter.

## Tasks, metrics, and splits

`configured` means the run chooses the count with `benchmark.split` or `split_counts`; `native` means the
benchmark exposes a fixed source split; `—` means that role is not part of the native collection. Details
link to the corresponding integration or configuration guide.

| Domain | Benchmark | Task | Metric | Train | Dev | Test | Details |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| QA | [SearchQA](../../flashrsi/benchmarks/searchqa) | Search-snippet short-answer QA | EM / F1 | configured | configured | configured | [Setup](../searchqa-deepseek-reproduction.md) |
| QA | [HotpotQA](../../flashrsi/benchmarks/hotpotqa) | Multi-hop Wikipedia QA | EM / F1; joint F1 | configured | configured | configured | [Setup](../hotpot-independent-evolution.md) |
| QA | [MuSiQue](../../flashrsi/benchmarks/musique) | Compositional multi-hop QA | EM / F1 | configured | configured | configured | [Setup](../musique-independent-evolution.md) |
| QA | [TriviaQA](../../flashrsi/benchmarks/triviaqa) | Wikipedia trivia QA | Alias-aware EM / F1 | configured | configured | configured | [Setup](../triviaqa-independent-evolution.md) |
| QA | [Natural Questions](../../flashrsi/benchmarks/nq) | Short-answer and yes/no QA | EM / F1 | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| QA | [2WikiMultiHopQA](../../flashrsi/benchmarks/twowiki_multihopqa) | Multi-hop QA with context | EM / F1 | configured | configured | configured | [Setup](../twowiki-independent-evolution.md) |
| Reasoning | [BBEH](../../flashrsi/benchmarks/bbeh) | BIG-Bench Extra Hard tasks | Per-answer accuracy | — | — | native | [Guide](../lightweight-benchmarks.md) |
| Reasoning | [SuperGPQA](../../flashrsi/benchmarks/supergpqa) | Graduate-level multiple choice | Answer accuracy | — | — | native | [Guide](../lightweight-benchmarks.md) |
| Reasoning | [HLE](../../flashrsi/benchmarks/hle) | Text-only Humanity's Last Exam | Judge accuracy | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| Math | [MATH](../../flashrsi/benchmarks/math) | Competition mathematics | Math-Verify accuracy | configured | configured | configured | [Setup](../math-independent-evolution.md) |
| Math | [AIME](../../flashrsi/benchmarks/aime) | AIME 2025 / 2026 | Exact integer accuracy | — | — | native | [Guide](../coding-math-benchmarks.md) |
| Math | [LiveMathBench](../../flashrsi/benchmarks/livemathbench) | Repeated-sampling mathematics | G-Pass@k / mG-Pass@k | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| Coding | [SWE-bench Verified](../../flashrsi/benchmarks/swe_bench) | Repository issue repair | Verifier resolved rate | configured | configured | configured | [Setup](../swe-independent-evolution.md) |
| Coding | [SWE-bench Pro V2](../../flashrsi/benchmarks/swe_bench_pro) | Repository repair | Container regrade rate | configured | configured | configured | [Guide](../coding-working-benchmarks.md) |
| Coding | [DeepSWE](../../flashrsi/benchmarks/deepswe) | DeepSWE repository tasks | Container verifier reward | configured | configured | configured | [Guide](../deepswe.md) |
| Coding | [Terminal-Bench 2.0 / 2.1](../../flashrsi/benchmarks/terminal_bench) | Linux terminal tasks | Native verifier reward | configured | configured | configured | [Guide](../terminal-bench.md) |
| Web research | [BrowseComp](../../flashrsi/benchmarks/browsecomp) | Broad web research | Official judge accuracy | — | — | native | [Services](../web-research-services.md) |
| Web research | [DeepSearchQA](../../flashrsi/benchmarks/deepsearchqa) | Single- and set-answer search | Autorater F1 | — | — | native | [Services](../web-research-services.md) |
| Web research | [WideSearch](../../flashrsi/benchmarks/widesearch) | Tabular broad search | Official table score | — | — | native | [Services](../web-research-services.md) |
| Documents | [OfficeQA-Pro](../../flashrsi/benchmarks/officeqa_pro) | Document research | Numeric / text accuracy | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| Documents | [Harvey LAB](../../flashrsi/benchmarks/harvey_lab) | Legal document work | Dual-judge all-pass rate | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| Documents | [JobBench](../../flashrsi/benchmarks/jobbench) | Professional file delivery | Weighted rubric reward | configured | configured | configured | [Guide](../coding-working-benchmarks.md) |
| Documents | [SpreadsheetBench 2](../../flashrsi/benchmarks/spreadsheetbench2) | Spreadsheet debugging and modeling | LibreOffice verifier | configured | configured | configured | [Guide](../coding-working-benchmarks.md) |
| Tool use | [AppWorld](../../flashrsi/benchmarks/appworld) | Application and API automation | Task-completion reward | configured | configured | configured | [Setup](../appworld-independent-evolution.md) |
| Tool use | [BFCL V4](../../flashrsi/benchmarks/bfcl) | Multi-turn function calling | Conversation success | configured | configured | configured | [Index](../benchmark-quickstart.md) |
| Tool use | [WorkBench](../../flashrsi/benchmarks/workbench) | Workplace database tasks | Database-state correctness | configured | configured | configured | [Guide](../workbench.md) |
| Tool use | [TravelPlanner](../../flashrsi/benchmarks/travelplanner) | Constraint-aware itineraries | Constraint pass rate | native | native | native | [Index](../benchmark-quickstart.md) |
| Interactive | [τ²-bench](../../flashrsi/benchmarks/tau2) | Airline, retail, telecom dialogue | Mean native reward | configured | configured | native | [Guide](../tau2-bench.md) |
| Interactive | [τ³ Banking](../../flashrsi/benchmarks/tau3_banking) | Multi-turn banking support | Native reward | configured | configured | native | [Index](../benchmark-quickstart.md) |
| Interactive | [ALFWorld](../../flashrsi/benchmarks/alfworld) | Text-only embodied tasks | TextWorld success | native | native | native | [Guide](../alfworld.md) |

## Check coverage before a large run

DeepSWE currently has an interface adapter; official downloads and real execution remain unverified. SpreadsheetBench 2 covers its first three task categories and excludes Visualization. Check each guide for the supported track and validation status.

A registered benchmark is not evidence of a completed model run. Inspect task failures and trajectories alongside its aggregate metric. Report custom experimental splits separately from official leaderboard settings.

To integrate another task suite, see [Add a benchmark](../development/benchmark.md).
