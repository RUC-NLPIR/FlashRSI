# Codex

默认执行选定 Snapshot 中的 **Python 核心**。固定基线是 OpenAI Codex
`rust-v0.147.0`，commit `be6e8eac029b183056b7e4402879f15d2c85f61b`。
上游核心使用 Rust，因此这里是依据源码进行的 Python 语义移植，不能称为字节相同的抽取，
也不能把已通过的局部对照解释为整个 Codex 已经完全等价。

`python_core/` 包含模型解析、Responses/SSE、历史、主循环、工具调度、shell、补丁、
资源、MCP、hooks、v1/v2 子代理、本地/远程压缩、上下文窗口和 memory。它属于 Snapshot 的 `code` 组件。
固定框架适配层只处理配置、目录、进程和 Trajectory 映射；启动独立 Python 进程后，
从选定运行副本导入核心，不导入宿主包中的核心作为兜底。不需要 Cargo、Rust 或 Codex CLI。

来源映射和原始资源校验见 [codex-core-extraction.md](codex-core-extraction.md)，
当前状态、shell snapshot 与平台验收见 [任务基线验收](codex-task-baseline-2026-10-29.md)，
上一批修复见 [审计修复验收](codex-core-repair-2026-10-29.md)，
更早记录见 [codex-core-validation.md](codex-core-validation.md)。
后续迁移顺序、状态隔离和演化验收建议见 [Codex 演化方案](codex-evolution-plan.md)。
任务路径与未覆盖开关见 [任务机制清单](codex-task-mechanisms.md)。

## 安装和使用

```bash
uv sync --extra dev --extra codex
uv run flashrsi run --config examples/codex.yaml --agent codex --prepare-only
```

`codex` extra 安装 Python HTTP 客户端和图片依赖。shell 使用机器上已有的 shell/工具，
不会下载或调用 Rust 引擎。Code Mode 模型另需本机 `node`（V8 async module 支持）；Python 控制工具和会话，隔离的 JS worker 只执行模型提供的 JavaScript，模型代码不能直接访问 Node、文件或网络。`--prepare-only` 仅准备配置，不调用模型。

```python
import asyncio
from flashrsi.agents import Codex

agent = Codex(
    {
        "llm": {
            "model_name": "gpt-5",
            "api_key": "your-api-key",
            "base_url": "https://your-responses-endpoint/v1",
        },
        "sandbox": "workspace-write",
        "timeout": 300,
    }
)
result = asyncio.run(agent.run("Explain the supplied task."))
print(result.status, result.output)
```

端点必须支持流式 Responses API。模型、API key 和端点来自当前角色的 `llm`；
目标 Agent 与 `algorithm.worker.llm` 独立，不继承宿主 Codex 登录态。
默认 OpenAI 端点保留 `OpenAI` provider 身份，Azure 端点使用 `Azure`；其余端点
默认使用 custom provider。兼容网关可显式设置 `llm.provider_name: OpenAI` 或 `Azure`，
使远程压缩等机制按对应原生 provider 工作；网关必须支持这些接口。
当前非交互执行采用 `approval_policy=never`。执行超时由 `timeout` 控制，
不会另加一个上游没有的模型调用轮数上限。

作为算法 Worker，使用 `type: agent`、`name: codex`，算法仍调用
`worker.ask(prompt)` 或 `worker.edit(directory, prompt)`。

## Snapshot 与资源

| 组件 | 路径 | 作用 |
| --- | --- | --- |
| code | `python_core/` 的请求、上下文、历史、压缩和模型核心模块 | 主循环和协议上下文 |
| tool | `tools.py`、shell、patch、Code Mode、MCP 和工具资源；外部 `servers/**` | 工具执行与工具协议 |
| agent | `subagents*.py` 与角色/模板资源；外部 `agents/**` | v1/v2 子代理运行时及角色资源 |
| hook | `hooks.py` 与 hook schema；外部 `hooks/**` | hook 运行时和输出 schema |
| memory | `memory.py` 与 memory 资源；外部 `memories/**` | memory 读取和笔记机制 |
| plugin | `plugins.py` 与 plugin 提示；外部 `plugins/cache/**` | 本地 plugin 机制 |
| prompt | `AGENTS.md` 与 `python_core/assets/` 的提示模板 | 版本全局指令和内置提示模板 |
| skill | `skills/**` 与 `resource_assets/system_skills/**` | 自定义及内置技能资源 |
| config | `config.toml`、`rules/**`、模型目录、权限模板和来源元数据 | 原生形状配置及静态元数据 |

开启 `code: rw` 后，算法可以修改主循环和协议上下文；需要演化工具、子代理、hook、
memory 或 plugin 机制时，分别选择对应组件。`{"*": "rw"}` 仍表示整个 Snapshot。
`rollout(tasks, snapshot=candidate)` 执行候选；`update(candidate)` 才切换默认版本。
候选保存/加载后仍使用候选源码，语法损坏会在模型请求前失败，不回退基线。
`source_dir` 自定义版本必须提供 `components.yaml` 和完整 `python_core/`。
固定 `_entry.py`、`_python.py` 和 Agent 适配器均不属于 Snapshot。

当前默认 Snapshot 有 141 个文件，文件内容合计 1,835,309 bytes；保存为 JSON 为
2,466,080 bytes，gzip 后为 739,602 bytes。这里的大小只统计 Snapshot 文件 payload，
不含适配器、依赖、Rust 参考目录、凭据和运行状态；分类明细见
[组件拆分记录](codex-component-split-2026-10-29.md)。

每次调用复制资源到用户 cache 下 `flashrsi/codex/` 中的独立临时 home，尊重
`XDG_CACHE_HOME`，缓存父目录和每次运行目录权限为 `0700`，调用结束后删除运行目录；
它不提供跨运行会话持久化。
这个位置保留原生可执行 helper 对系统临时目录的限制，不需要修改该限制。
凭据、日志、工具进程和任务目录不进入 Snapshot。
显式传入的 `working_dir` 与核心 home 分开；未传时创建临时任务目录。
任务项目的 AGENTS、AGENTS.override.md 和项目 skills 遵循原生发现与显式选择规则，
它们属于任务输入，不写入 Snapshot。宿主用户及系统的无关 skills 被隔离；项目
config/hooks 保持不受信任，避免覆盖所选 harness。原生即使在不受信任的项目中
也可能发现 `.codex/skills`，此行为保留。
需要固定任务上下文时，在 Snapshot 的 `config.toml` 中显式设置
`project_doc_max_bytes = 0`，并通过 `[[skills.config]]` 的 name/path selector 禁用特定技能。

stdio MCP 的 `command` 和独立 `args` 元素若指向版本内的相对路径，且包含 `/`，
会重定位到运行副本。裸命令、模块名和外部绝对路径保持原样。复合 shell 命令可使用
`$CODEX_HOME`。例如：

```toml
[mcp_servers.local_tools]
command = "python3"
args = ["servers/tools.py"]
env_vars = ["CODEX_HOME", "FLASHRSI_TASK_DIR"]
default_tools_approval_mode = "approve"
```

仅有组件文件不代表已启用；MCP、hooks、插件、角色均需要对应配置。

## 长上下文、子代理与 memory

压缩遵循 provider：普通 custom provider 用本地摘要，OpenAI/Azure 使用远程压缩；
`features.remote_compaction_v2` 选择流式 v2 或 unary v1。启用 `features.token_budget`
时按原生窗口机制 rollover，保留环境和工具进程，重建模型上下文；支持提醒、fallback
buffer、`new_context` 与 `get_context_remaining`。配置形状和默认值来自固定上游。

子代理版本遵循模型目录，亦可通过 `features.multi_agent_v2` 配置。v2 提供任务路径、
spawn、send_message、followup_task、list_agents、wait_agent 和 interrupt_agent；
持续子线程保留自己的历史、工具和 memory 资源，支持 SubagentStart/SubagentStop hooks。
这些线程保留在一次运行内；跨进程恢复、完整 rollout 数据库及 rollback/旧压缩事件重放尚未迁移。
缓存续轮可更新兼容的模型、effort 和预算；改变已初始化的工具协议、资源配置或环境会明确拒绝。

memory 默认与该版本原生配置一样关闭；需要时在版本的 `config.toml` 中启用：

```toml
[features]
memories = true

[memories]
dedicated_tools = true
```

`memories/memory_summary.md` 自动注入初始上下文；工具支持 list、read、search 和显式
add_ad_hoc_note。固定上游的 app-server 另有自动 extraction/consolidation 管线；
它不在 ephemeral exec 任务路径中触发。Python 尚未迁移这条长期持久会话管线，
当前支持的 memory 读取与显式笔记不能替代它。

每次运行的默认 home 独立。若需要跨运行保留显式笔记，在 Agent 执行配置中设置
`memory_dir` 为 Snapshot 源目录之外的路径。适配层按完整 Snapshot ID 分目录保存
append-only 笔记；切换候选不会读取另一版本的运行时笔记，版本资源本身不被改写。
该选项用于普通 `run` 的在线积累。`rollout` 评估每题只读取所选 Snapshot 内的初始
memory，不加载或回写 `memory_dir`；题内读写保持可用，结束后丢弃临时改动。
因此同一候选的重复评估不会因前面题目产生笔记而改变初态。
需要评估训练得到的记忆时，将冻结后的记忆显式放入候选的 `memory` 组件。

Python 运行轨迹中的 `CodexRunEnvironment` 记录评估/在线模式、初始 memory 指纹、
模型/provider、feature 配置、预算、权限、平台及运行依赖。状态过大或采集未完成时
明确标记不完整，不将截断状态的哈希当作完整初态。环境记录不包含记忆正文和凭据。

## 明确的能力边界

目前支持普通 Responses HTTP/SSE、Responses Lite/Code Mode、原生模型目录和提示词、历史归一化/截断、
工具完成项驱动的续跑、并行/串行调度、普通 shell、PTY 会话、apply_patch、
POSIX shell snapshot 的后台生成与条件恢复、
计划、原样传递的 PNG/JPEG/WebP 图像、AGENTS/skills、本地插件、stdio MCP、常用 hooks、v1/v2 子代理、本地及远程 v1/v2 压缩、token-budget 窗口切换、`body_after_prefix` 预算、memory 读取和显式笔记。
具体已验证的路径以验收文档与测试为准。

尚未完成的分支包括 WebSocket、账号恢复、
HTTP/OAuth MCP、app connectors、`features.rollout_budget` 父子代理共享任务预算、
zsh-fork 后端，以及完整的执行策略规则引擎。GIF/TIFF 转码和需缩放的图片尚未实现字节等价，因此明确拒绝。
shell snapshot 恢复上游默认开启：后台捕获不阻塞采样，执行时仅使用已完成且 cwd 匹配的快照；
关闭 login shell 或快照生成失败时沿用原生直接执行路径。
子代理继承父环境的 shell 与共享 snapshot，最后一个使用者释放后删除文件；
v2 驱逐后重载保留这一继承关系。
启用未移植功能应报错，不能切换到 Rust 运行。
独立 JS REPL 已在该固定上游版本移除；JavaScript 工具执行走 Code Mode。

受限 shell 使用 macOS Seatbelt。Linux 的受限沙箱尚未移植，会拒绝运行；
Linux 显式选择 `danger-full-access` 的 POSIX shell、PTY、补丁与 Code Mode 路径，
已通过真实 Linux 和实际 Docker 的固定原生对照及安装验收；条件与范围见
[任务基线验收](codex-task-baseline-2026-10-29.md)，不能据此推断受限沙箱或完整 benchmark 已通过。
Windows 的 shell、进程组和 PTY 后端尚未移植，即使选择 `danger-full-access`
也不能运行 shell 工具。`external-sandbox` 和自定义网络/文件系统权限 profile 同样未接入。

保留的 `runtime/`、`_bridge/` 和 Rust 构建脚本仅作为上游参考及历史验证资料，
不属于当前 `code` Snapshot，也不随当前 wheel 打包或参与默认执行。
如需固定版本的原生对照，可安装 `--extra codex-oracle` 并显式配置 `cli_path`；
该模式运行指定的外部 CLI，**不会执行 Python 候选源码**，仅用于对照，不用于 Python
源码演化验收。启用该模式的 RunConfig 会记录 `cli_path`。
