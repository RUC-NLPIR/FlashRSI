# FlashRSI Evolved Harnesses

English | [简体中文](README.zh-CN.md)

This directory contains **96 final harness artifacts from historical experiments**: 12 algorithms, two harness types (MiniAgent and Claude Code), and four benchmarks (SearchQA, HotpotQA, TerminalBench, and AppWorld).

## Directory structure

```text
exports/
├── README.md
├── README.zh-CN.md
└── harnesses/
    └── <algorithm>-<agent>-<benchmark>/
```

Each group is an expanded directory that can be inspected and modified directly. MiniAgent directories include runtime source and resources. Claude Code directories contain extensions loaded by its native engine, such as prompts, skills, hooks, and MCP tools; they do not include the engine itself.

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

## Using an artifact

Install FlashRSI following the [project README](../README.md). In your experiment configuration, set `agent.name` to the corresponding harness type and `agent.source_dir` to the artifact directory. Paths in the YAML configuration are resolved relative to that configuration file.

For a configuration file saved in `exports/`, for example:

```yaml
agent:
  name: miniagent
  source_dir: ./harnesses/rrsi-miniagent-hotpotqa
```

Provide the model connection, algorithm settings, and benchmark configuration as usual. Benchmark data, Docker images, model credentials, and original experiment logs are not included. Keep runtime outputs outside the artifact directories.

## AppWorld compatibility and transfer across benchmarks

Some AppWorld artifacts use AppWorld's public task APIs directly in prompts, skills, Python tools, or MCP scripts, so they depend on the corresponding task environment.

Twenty groups of historical tools use `appworld-connection.json` and a Unix socket. The AppWorld adapter provides a compatibility bridge that forwards calls to the HTTP world for the same task, without rewriting the historical tools. Use a FlashRSI version that includes this bridge. See the [AppWorld guide](../docs/appworld-independent-evolution.md) for details.

Transferring these artifacts to another benchmark still requires adapting environment APIs, tool bindings, and related strategies. We plan to provide that adaptation later; direct transfer across benchmarks is not currently guaranteed.
