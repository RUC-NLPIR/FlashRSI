# Codex 任务机制清单

固定参考：`rust-v0.147.0` / `be6e8eac029b183056b7e4402879f15d2c85f61b`。
这是迁移与验收清单，不是“全 Codex 已等价”的声明。实现范围以实际测试路径为准。
后续顺序见 [演化方案](codex-evolution-plan.md)。

## 当前目标运行条件

目标是 API-key provider 的 HTTP Responses/SSE、一次 headless 任务调用、
`approval_policy=never`，以及任务内的长上下文和 v1/v2 子代理。
普通 custom provider、本地压缩与 OpenAI/Azure 远程压缩分别验收；兼容网关必须提供相应接口。
Code Mode 另需可用的 Node V8。模型、effort、feature、权限和平台均需随结果记录。

评估 `rollout` 从所选 Snapshot 的 memory 初态开始，每题独立；普通 `run` 可显式使用
外部 `memory_dir` 累积笔记。在线积累与固定初态的任务评估应分别报告。
实现验收完成前，不应仅据本表使用尚未完成的能力。

## 任务路径

| 机制 | 当前范围 / 验证入口 | 主要剩余边界 |
| --- | --- | --- |
| 模型与主循环 | `loop.py`、`models.py`、`client.py`；protocol/loop/task parity 测试 | WebSocket、原生账号恢复 |
| 工具调度与错误 | `tools.py`；task tools regression、task exec parity | 每个未覆盖的工具分支仍需对照 |
| Bash 补丁识别与应用 | 固定 grammar、query 及 Python patch 核心；task tools regression | 不据文件成功推断其他语言/平台已等价 |
| Shell snapshot | 后台捕获、验证、条件恢复、子代理共享和生命周期；snapshot/task parity 回归通过 | 持久 state DB 尚未迁移；平台与 wheel 范围见本轮验收 |
| POSIX shell/PTY/取消 | macOS 有现有对照；本轮增加真实 Linux 安装验收 | Linux 容器与主机进程分别报告；Windows 后端未迁移 |
| 受限执行与规则 | macOS Seatbelt 已有测试 | Linux/Windows 受限沙箱、自定义 profile、execpolicy 未迁移 |
| AGENTS、skills、本地插件、hooks | resources/resource walk/integration parity 测试 | managed trust、完整配置发现、远程目录与依赖安装仍有边界 |
| stdio MCP / tool search | 本地 stdio、schema 清理和 BM25；MCP/tool search 测试 | HTTP/OAuth MCP、apps/connectors 及完整 schema 边界 |
| Code Mode / Responses Lite | Python 调度 JS worker；code mode/lite 原生对照 | 全 V8 版本、音频编码和极端计时器边界 |
| 历史、压缩和上下文窗口 | history/compact/long context 测试 | legacy rollout 事件重放、完整多模态用量 |
| v1/v2 子代理 | subagents/subagents v2/fidelity 测试 | 跨进程恢复、部分自定义 profile/provider 配置 |
| 父子共享 rollout budget | 尚未迁移；原生默认关闭 | 整棵代理树计费、提醒及超限终止均需实现 |
| 持久会话 | 只支持一次进程内的线程缓存与续轮 | rollout/state DB、跨进程恢复、rollback/旧压缩重放 |
| Memory 读取与显式笔记 | memory/memory persistence/evaluation 测试；rollout 初始 memory 隔离 | 显式笔记不能替代自动 writer |
| 自动 memory writer | 尚未迁移；原生默认关闭 memories | extraction/consolidation 依赖持久会话、筛选与调度 |
| 图像 | 预算内 PNG/JPEG/WebP 保留原始字节；images 测试 | resize、GIF/TIFF 转码和完整音频/多模态预算 |
| Snapshot 演化与安装 | adapter/evaluation/provenance、独立 wheel 验收 | 后代允许改变基线行为；仍需契约、隔离和任务质量检查 |

本轮回归结果、目标平台和安装 wheel 的哈希另列于本轮验收报告；
不能将历史轮次的通过数算成本轮修改后的验证。

## 原生默认值与尚未逐项验收的开关

`runtime/features/src/lib.rs` 是固定默认值的来源。shell snapshot 默认开启；
memories、rollout budget、token budget 和 zsh fork 默认关闭。
开关“允许使用某项能力”与本次任务“实际触发某条路径”是两件事。

为避免只关注已移植模块，本轮还枚举了固定上游的 104 条 FeatureSpec（包含平台条件开关）。
结果存于 `.cache/codex-python/stage1-20261029/feature-defaults-before.json`。
它记录的是本轮修改前 Python 是否接受显式启用，不能证明功能实现或行为等价。
其中上游默认开启、Python 未接受显式启用的开关还包括：

- apps、tool_suggest、in_app_browser、in_app_updates、browser_use 及其 full_cdp_access/external 变体、computer_use。
- remote_plugin、plugin_sharing、image_generation、skill_mcp_dependency_install、skill_search、mentions_v2。
- guardian_approval、goals、tool_call_mcp_elicitation、auth_elicitation、fast_mode、workspace_dependencies。

上述开关需要逐项确定是否进入目标任务的调用链；当前清单不把它们统称为 UI 包装，
也不把“API-key headless 测试未触发”写成“已经迁移”。本轮优先完成 shell snapshot、
评估状态和 Linux 执行验证，其余路径继续作为明确的覆盖边界。
