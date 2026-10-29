# Codex 核心版本与 Python 迁移

当前执行核心是 `flashrsi/agents/codex/python_core/`，由 Python 实现，作为 Codex
Snapshot 的可演化代码和资源运行。固定基线是 OpenAI Codex：

- 版本：`0.147.0`
- tag：`rust-v0.147.0`
- commit：`be6e8eac029b183056b7e4402879f15d2c85f61b`

这是一份按固定版本源码完成的 Python 语义移植。上游执行逻辑使用 Rust，不能通过
删除 CLI、app 和前端代码直接得到 Python 实现；当前实现对已支持任务路径做了行为
移植，但不宣称覆盖原生 Codex 的全部分支。

## 执行边界

框架把选中的 Snapshot materialize 到独立目录，再从其中加载 Python 核心、配置、
指令、skills、hooks、plugins 和 MCP 配置。执行不编译 Rust，也不启动 Codex CLI；
适配器只负责配置、目录、进程和 Trajectory 映射，会话循环、Responses 请求、历史、
工具执行、上下文压缩、子代理和 memory 都在选中的 Python 核心中。

Code Mode 的工具程序仍由隔离的 Node V8 worker 求值，工具委派和会话生命周期由
Python 管理。这个 Node worker 是模型代码的执行环境，不是 Codex harness 的 native
runtime。

核心组件按 Snapshot 分类如下：

| 组件 | 主要路径 | 职责 |
| --- | --- | --- |
| `code` | `loop.py`、`context.py`、`history.py`、`compact.py`、`client.py`、`models.py` | 会话、请求、历史、上下文和模型配置 |
| `tool` | `tools.py`、`shell.py`、`apply_patch.py`、`code_mode.py`、`mcp.py` | 工具协议、shell、补丁、Code Mode 和 MCP |
| `agent` | `subagents.py`、`subagents_v2.py` | v1/v2 子代理、mailbox、fork 和生命周期 |
| `memory` | `memory.py`、`memory_assets/` | summary、读写搜索和显式笔记 |
| `hook` | `hooks.py`、`resource_assets/hook_schemas/` | command hooks 和生命周期事件 |
| `plugin` | `plugins.py`、`resource_assets/plugins_prompt.txt` | 本地插件资源 |
| `prompt`/`skill`/`config` | `assets/`、`resource_assets/`、外部 Snapshot 目录 | 提示词、技能和版本配置 |

版本信息以本文档和 [Codex 说明](codex.md) 为准。核心目录不再携带
`UPSTREAM.json`、`PROVENANCE.json` 或其他来源清单；这些文件不参与运行时逻辑，
也不属于 Snapshot 的必要输入。

## 验证

使用本地回放 Responses 服务和真实本地工具运行 Codex 专项测试：

```bash
uv run --no-sync pytest -q tests/test_codex*.py
uv run --no-sync ruff check flashrsi/agents/codex tests/test_codex*.py
uv build --wheel --out-dir /tmp/flashrsi-codex-wheel
```

测试验证 Python 核心的请求协议、工具调度、shell/PTY、上下文、子代理、memory、
Snapshot 演化和安装产物。测试通过只说明这些覆盖路径可用，不代表所有未迁移的原生
账号登录、受限 sandbox、远程 MCP 或 app-server 持久管线已经等价。
