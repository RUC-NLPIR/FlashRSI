# Choose and run an experiment

[README](../README.md) · [Configuration and Python API](usage.md)

## Choose a version

| You need | Use | Harnesses |
| --- | --- | --- |
| The quickstart or Codex | `main`: SearchQA, HotpotQA, Terminal-Bench 2.0, τ³ Banking | MiniAgent, Claude Code, Codex |
| The full 28-benchmark collection | [`integration/flashrsi-smoke`](https://github.com/ignorejjj/FlashRSI/tree/integration/flashrsi-smoke) | MiniAgent, Claude Code |

A valid combination needs a harness that exposes the resources the algorithm edits and the tools the task uses.

## Choose an algorithm and harness

Start with a [configuration from the algorithm list](../README.md#supported-algorithms). It includes the method's parameters and Worker type.

| What to improve | Algorithms | Worker |
| --- | --- | --- |
| Instructions | OPRO, GEPA, EvoPrompt, ACE | LLM or Agent |
| Skills | SkillOpt | LLM or Agent |
| Skills discovered by the native harness | Evo-Harness | Agent |
| Declared harness resources | AHE, ADAS, DarwinX, Meta-Harness, ModularRSI, RRSI | Agent |

The Target solves tasks; the Worker proposes changes. They can use different models and harnesses. Configure them independently in `agent` and `algorithm.worker`; see [model and connection settings](usage.md#configure-an-experiment).

The editable scope follows each harness's declared resources; see the [harness list](../README.md#supported-harnesses).

Additional method requirements:

- Evo-Harness needs native directory-based skill discovery and loading. Declaring a `skill` component alone is insufficient; see its [implementation notes](evo-harness.md).
- ModularRSI needs separate evolution data and mappings for five modules. Fill in the paths in its [configuration](../examples/modular_rsi.yaml); see the [data and module requirements](modular-rsi.md).

Other implementation notes: [ACE](ace.md), [AHE](ahe.md), [ADAS](adas.md), [DarwinX](darwinx.md), [Meta-Harness](meta-harness.md), and [RRSI](rrsi.md). These describe adaptations to the original methods.

## Choose a benchmark

The README links each benchmark to its setup and available YAML examples. An entry with only **Setup** has no ready-made benchmark YAML; use its setup instructions to configure the data, grading, and runtime.

### Benchmarks on main

| Benchmark ID | Start here | Preparation |
| --- | --- | --- |
| `searchqa` | [Local quickstart](../examples/quickstart.yaml) | Includes 12 questions to try the workflow. For full data, use the [SearchQA experiment guide](searchqa-deepseek-reproduction.md). |
| `hotpotqa` | [Config](../examples/hotpotqa.yaml) | Loads the benchmark data. Fullwiki mode also needs a retrieval service configured in the YAML. |
| `terminal_bench` | [Config](../examples/terminal_bench.yaml) | [Harbor, Python 3.12+, and Docker](terminal-bench.md). |
| `tau3_banking` | [Config](../examples/tau3_banking.yaml) | Install tau2 and prepare its banking data and user simulator as described in the configuration. |

Harbor and tau2 use separate environments because their dependencies conflict.

### Benchmark collection

Use a separate checkout for the full collection. Python 3.12 or 3.13 covers the version requirements of its supported environments.

```bash
git clone --branch integration/flashrsi-smoke --single-branch https://github.com/ignorejjj/FlashRSI.git FlashRSI-benchmarks
cd FlashRSI-benchmarks
```

Fill in the Target and Worker model settings in the chosen YAML. For example, to run OPRO on BBEH:

```bash
python3 scripts/run_experiment.py --config examples/bbeh_opro.yaml
```

This branch's launcher creates an isolated environment, installs the selected dependencies, and prepares benchmark data. Git and any required Docker daemon must already be available. Add `--plan` to inspect requirements, or `--check-only` to install dependencies and prepare data without model calls. Neither option validates model authentication.

| Task family | Extra preparation | Setup |
| --- | --- | --- |
| QA and reasoning | Data downloads; HotpotQA fullwiki needs retrieval. | [Data and prerequisites](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查), [BBEH / SuperGPQA](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/lightweight-benchmarks.md) |
| Mathematics and code | Math scoring dependencies; SWE tasks need Docker. HLE and LiveMathBench need a Judge. | [Math / CRUXEval](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/coding-math-benchmarks.md), [SWE-bench](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/swe-independent-evolution.md) |
| Web research | Search/web services and an independent Judge. | [Service configuration](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/web-research-services.md) |
| Documents | OfficeQA-Pro needs its corpus; Harvey LAB needs Judge models; JobBench needs Docker and a Judge. | [OfficeQA-Pro](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/web-research-services.md), [Other prerequisites](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| Tools and applications | AppWorld and BFCL need Docker; WorkBench needs Git; TravelPlanner needs a postprocessing model. | [AppWorld](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/appworld-independent-evolution.md), [WorkBench](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/workbench.md), [Other prerequisites](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#准备与检查) |
| Interactive environments | τ²/τ³ need a user simulator; τ² retail also needs a Judge. Terminal-Bench needs Docker and Harbor. | [τ²](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/tau2-bench.md), [Terminal-Bench](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/docs/terminal-bench.md) |

Some linked configurations use ModularRSI and contain paths to experiment-specific data. Prepare the required data and module files before running them.

Keep train, dev, and test separate. When a benchmark only provides an evaluation pool, explicitly define an experimental split. A split made for self-improvement is a custom protocol; its scores are not automatically comparable to the official leaderboard. Follow the benchmark's setup notes for its supported track and metric.

## Read the results

On `main`, each run writes to `runs/<algorithm>-<agent>-<benchmark>-<timestamp>/` by default. The CLI reports the directory. Start with:

| File | What to inspect |
| --- | --- |
| `end-summary.md` | Run status, final test score, and recorded usage. |
| `result.json` | `test_score`, `primary_metric`, `test_tasks`, and the selected `snapshot_id`. |
| `snapshots/` | Saved resource versions. Match the selected ID to its Snapshot. |
| `trajectories/` | Task results, Worker calls, and candidate decisions. |
| `config.yaml` | The saved configuration, with credentials redacted. |

The standard runner evaluates the selected Snapshot on test after search. It does not automatically run the initial Snapshot on test. For an improvement claim, compare both versions on the same held-out tasks and metric, as in the [SearchQA reproduction guide](searchqa-deepseek-reproduction.md).

For the collection branch's output and cache locations, see its [run guide](https://github.com/ignorejjj/FlashRSI/blob/integration/flashrsi-smoke/README.md#模型配置与文件位置).
