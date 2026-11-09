# FlashRSI Evolved Harnesses

[English](README.md) | 简体中文

这里提供 **96 组历史实验最终选中的 harness 与 Snapshot**：12 个算法、MiniAgent / Claude Code 两种 harness，以及 SearchQA、HotpotQA、TerminalBench、AppWorld 四个 benchmark。

这些是冻结的演化产物。加载、评估或继续演化时，请使用同一组的源码目录与 Snapshot。模型凭据、benchmark 数据、Docker 镜像和原始实验日志不包含在本目录中。

## 目录结构

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

`harnesses/` 下是已经展开、可直接阅读的 96 个完整目录：MiniAgent 包含其运行源码及资源；Claude Code 包含原生引擎加载的 prompt、skill、hook、MCP 等扩展，不包含引擎自身。

`snapshots/` 下的 96 份 JSON 与展开目录配套。`MANIFEST.json` 记录分组、历史来源、Snapshot 身份、逐文件哈希及验证状态。

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

## 加载与评估

先按 [项目 README](../README.zh-CN.md) 安装 FlashRSI，并准备目标 benchmark 的数据、依赖和运行环境。当前 SearchQA / HotpotQA 集成使用 Docker；TerminalBench 还需要 Harbor 和对应任务镜像；AppWorld 需要原生 AppWorld 环境及下文的历史接口兼容层。

以下以 `rrsi-miniagent-hotpotqa` 为例。将 `evaluate.local.yaml` 放在 `exports/` 根目录，填写实际的模型连接及测试数据路径：

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

在 FlashRSI 项目根目录执行：

```bash
uv run flashrsi evaluate --config exports/evaluate.local.yaml --snapshot exports/snapshots/rrsi-miniagent-hotpotqa.json --check-only
uv run flashrsi evaluate --config exports/evaluate.local.yaml --snapshot exports/snapshots/rrsi-miniagent-hotpotqa.json
```

YAML 中的 `source_dir` 相对 YAML 文件目录解析；`--snapshot` 相对执行命令时的工作目录解析。更换组合时，同时更换 harness 类型、源码目录、Snapshot 和 benchmark 配置。Claude Code 需要其支持的模型接口和工具权限。评估不需要 Worker，也不会继续演化。

`--check-only` 是启动检查，不代表模型认证、工具调用或真实任务已通过。上述内容是配置模板，实际评估还需要有效数据与运行参数。更多选项见 [Snapshot 评估说明](../docs/snapshot-evaluation.md)。

## AppWorld 兼容性与跨 benchmark 迁移

部分 AppWorld 产物的 prompt、skill、Python 工具或 MCP 脚本直接使用 AppWorld 的公共任务 API，因此依赖对应任务环境。

其中 20 组历史工具使用 `appworld-connection.json` 和 Unix socket。当前本地实现已在 AppWorld 运行适配层补回旧接口，并转发到同题的 HTTP world；使用时需要包含此兼容实现的 FlashRSI 版本。兼容连接只在任务期间存在，不进入 Snapshot，也不要求改写历史工具。实现见 [AppWorld 兼容桥](../flashrsi/integrations/_appworld_legacy.py)，使用范围见 [AppWorld 说明](../docs/appworld-independent-evolution.md)。

这一层恢复的是原 AppWorld 的连接能力。将这些产物迁移到其他 benchmark 时，仍需适配环境 API、工具绑定及相关策略；我们会后续提供相应适配，目前不保证直接跨 benchmark 使用。

## Snapshot 身份与文件完整性

这里的 JSON 是从整理后的最终 harness 重新捕获的发布版本，与同名源码目录相匹配。此前整理调整过部分 MCP / hook 的部署启动命令，并生成 `components.yaml`；历史 Python、prompt 和 skill 保留原文。原实验的最终 ID、root ID 和原 JSON 哈希仍作为来源信息保存在清单中，发布版使用自己的 ID，不冒充原历史版本关系。

请成对使用本目录中的源码与 Snapshot。不要将另存的历史 JSON 直接配给当前默认 Agent 或本目录的发布版 root。

`.gitattributes` 为 harness 与 Snapshot 禁用 Git 换行转换，以保留校验字节。Snapshot 身份还包含可执行标志；跨 Windows / Linux 复制时，请按 `MANIFEST.json` 中 `files[].executable` 恢复文件模式（可执行文件 `0755`，其他文件 `0644`），并保留原始文件内容。运行日志、缓存和任务产物应保存在这些源码目录之外。
