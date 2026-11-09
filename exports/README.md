# FlashRSI Evolved Harnesses

English | [简体中文](README.zh-CN.md)

This directory provides **96 harnesses and Snapshots selected at the end of historical experiments**: 12 algorithms, two harness types (MiniAgent and Claude Code), and four benchmarks (SearchQA, HotpotQA, TerminalBench, and AppWorld).

These are frozen evolution artifacts. Use the source directory and Snapshot from the same group when loading, evaluating, or continuing evolution. Model credentials, benchmark data, Docker images, and original experiment logs are not included.

## Directory structure

```text
exports/
├── README.md
├── README.zh-CN.md
├── MANIFEST.json
├── harnesses/
│   └── <algorithm>-<agent>-<benchmark>/
└── snapshots/
    └── <algorithm>-<agent>-<benchmark>.json
```

`harnesses/` contains 96 expanded directories that can be inspected directly. MiniAgent directories include runtime source and resources. Claude Code directories contain extensions loaded by its native engine, such as prompts, skills, hooks, and MCP tools; they do not include the engine itself.

`snapshots/` contains 96 JSON files paired with the expanded directories. `MANIFEST.json` records groups, historical provenance, Snapshot identities, per-file hashes, and validation status.

| Benchmark | MiniAgent | Claude Code | Total |
| --- | ---: | ---: | ---: |
| SearchQA | 12 | 12 | 24 |
| HotpotQA | 12 | 12 | 24 |
| TerminalBench | 12 | 12 | 24 |
| AppWorld | 12 | 12 | 24 |
| Total | 48 | 48 | 96 |

The algorithms are ACE, ADAS, AHE, DarwinX, EvoHarness, EvoPrompt, GEPA, MetaHarness, ModularRSI, OPRO, RRSI, and SkillOpt. Directory names use their code identifiers, including `meta_harness`, `modular_rsi`, `claude_code`, and `terminalbench`.

Examples to browse:

- [RRSI / MiniAgent / HotpotQA](harnesses/rrsi-miniagent-hotpotqa/)
- [ModularRSI / Claude Code / TerminalBench](harnesses/modular_rsi-claude_code-terminalbench/)
- [ADAS / MiniAgent / AppWorld](harnesses/adas-miniagent-appworld/)
- [ADAS / Claude Code / AppWorld](harnesses/adas-claude_code-appworld/)

## Loading and evaluation

Install FlashRSI following the [project README](../README.md), then prepare the target benchmark's data, dependencies, and runtime environment. The current SearchQA and HotpotQA integrations use Docker. TerminalBench also requires Harbor and its task images. AppWorld requires its native environment and the legacy interface compatibility layer described below.

For example, to evaluate `rrsi-miniagent-hotpotqa`, save the following as `evaluate.local.yaml` in the `exports/` directory and supply your model connection and test data path:

```yaml
run:
  output_dir: ./runs
benchmark:
  name: hotpotqa
  mode: context
  split: auto
  data_path:
    test: /absolute/path/to/hotpotqa-test.jsonl
agent:
  name: miniagent
  source_dir: ./harnesses/rrsi-miniagent-hotpotqa
  max_turns: 20
  timeout: 600
  llm:
    model_name: YOUR_MODEL
    api_key: YOUR_RUNTIME_API_KEY
    base_url: YOUR_PROVIDER_BASE_URL
```

Run these commands from the FlashRSI project root:

```bash
uv run flashrsi evaluate --config exports/evaluate.local.yaml --snapshot exports/snapshots/rrsi-miniagent-hotpotqa.json --check-only
uv run flashrsi evaluate --config exports/evaluate.local.yaml --snapshot exports/snapshots/rrsi-miniagent-hotpotqa.json
```

The YAML `source_dir` is resolved relative to the configuration file. The CLI `--snapshot` path is resolved relative to the working directory. To use another group, update the harness type, source directory, Snapshot, and benchmark configuration together. Claude Code requires a supported model interface and appropriate tool permissions. Evaluation does not require a Worker and does not continue evolution.

`--check-only` checks startup configuration; it does not confirm model authentication, tool execution, or task success. The configuration above is a template: actual evaluation requires valid data and runtime settings. See [Snapshot evaluation](../docs/snapshot-evaluation.md) for more options.

## AppWorld compatibility and transfer across benchmarks

Some AppWorld artifacts use AppWorld's public task APIs directly in prompts, skills, Python tools, or MCP scripts, so they depend on the corresponding task environment.

Twenty groups of historical tools use `appworld-connection.json` and a Unix socket. The current local AppWorld adapter restores this legacy interface and forwards calls to the HTTP world for the same task. Use a FlashRSI version that includes this compatibility implementation. The connection exists only during the task, is not stored in the Snapshot, and does not require rewriting historical tools. See the [AppWorld compatibility bridge](../flashrsi/integrations/_appworld_legacy.py) and [AppWorld guide](../docs/appworld-independent-evolution.md) for its implementation and scope.

This layer restores connectivity within AppWorld. Transferring these artifacts to another benchmark still requires adapting environment APIs, tool bindings, and related strategies. We plan to provide that adaptation later; direct transfer across benchmarks is not currently guaranteed.

## Snapshot identity and file integrity

The JSON files are release versions recaptured from the prepared final harness directories and match their corresponding source directories. Earlier preparation adjusted some MCP and hook deployment commands and generated `components.yaml`; historical Python, prompt, and skill content was preserved. The original final IDs, root IDs, and JSON hashes remain in the manifest as provenance. Release versions have their own IDs and do not claim the original version lineage.

Use the source directory and Snapshot from the same group. Do not pair a separately archived historical JSON with the current default Agent or a release root from this directory.

`.gitattributes` disables Git line-ending conversion for harness files and Snapshots to preserve their exact bytes. Snapshot identity also includes executable flags. When copying between Windows and Linux, restore file modes according to `files[].executable` in `MANIFEST.json` (`0755` for executable files and `0644` for other files), and preserve the original file contents. Keep runtime logs, caches, and task outputs outside these source directories.
