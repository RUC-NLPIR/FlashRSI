# FlashRSI Evolved Harnesses

[English](README.md) | 简体中文

这里提供 **96 组历史实验最终选中的 harness 产物**：12 个算法、MiniAgent / Claude Code 两种 harness，以及 SearchQA、HotpotQA、TerminalBench、AppWorld 四个 benchmark。

## 目录结构

```text
exports/
├── README.md
├── README.zh-CN.md
└── harnesses/
    └── <algorithm>-<agent>-<benchmark>/
```

每组都是已经展开、可直接阅读和修改的目录。MiniAgent 包含其运行源码及资源；Claude Code 包含原生引擎加载的 prompt、skill、hook、MCP 等扩展，不包含引擎自身。

| Benchmark | MiniAgent | Claude Code | 合计 |
| --- | ---: | ---: | ---: |
| SearchQA | 12 | 12 | 24 |
| HotpotQA | 12 | 12 | 24 |
| TerminalBench | 12 | 12 | 24 |
| AppWorld | 12 | 12 | 24 |
| 合计 | 48 | 48 | 96 |

算法包括 ACE、ADAS、AHE、DarwinX、EvoHarness、EvoPrompt、GEPA、MetaHarness、ModularRSI、OPRO、RRSI、SkillOpt。目录使用代码中的名称，例如 `meta_harness`、`modular_rsi`、`claude_code` 和 `terminalbench`。

可以先浏览：

- [RRSI / MiniAgent / HotpotQA](harnesses/rrsi-miniagent-hotpotqa/)
- [ModularRSI / Claude Code / TerminalBench](harnesses/modular_rsi-claude_code-terminalbench/)
- [ADAS / MiniAgent / AppWorld](harnesses/adas-miniagent-appworld/)
- [ADAS / Claude Code / AppWorld](harnesses/adas-claude_code-appworld/)

## 使用产物

先按 [项目 README](../README.zh-CN.md) 安装 FlashRSI。在实验配置中，将 `agent.name` 设为对应 harness 类型，将 `agent.source_dir` 指向产物目录。YAML 中的路径相对配置文件目录解析。

例如，配置文件放在 `exports/` 下时：

```yaml
agent:
  name: miniagent
  source_dir: ./harnesses/rrsi-miniagent-hotpotqa
```

模型连接、算法参数和 benchmark 配置按通常方式填写。本目录不包含 benchmark 数据、Docker 镜像、模型凭据或原始实验日志。运行输出应保存在产物目录之外。

## AppWorld 兼容性与跨 benchmark 迁移

部分 AppWorld 产物的 prompt、skill、Python 工具或 MCP 脚本直接使用 AppWorld 的公共任务 API，因此依赖对应任务环境。

其中 20 组历史工具使用 `appworld-connection.json` 和 Unix socket。AppWorld 适配层提供兼容桥，将调用转发到同题的 HTTP world，不需要改写历史工具。使用时需要包含此兼容桥的 FlashRSI 版本，详见 [AppWorld 说明](../docs/appworld-independent-evolution.md)。

将这些产物迁移到其他 benchmark 时，仍需适配环境 API、工具绑定及相关策略；我们会后续提供相应适配，目前不保证直接跨 benchmark 使用。
