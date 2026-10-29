# Codex Python 核心验收：审计前记录

本次实现固定为 `rust-v0.147.0` /
`be6e8eac029b183056b7e4402879f15d2c85f61b`。验收日期：2026-10-28。
当前工作是 **Python 语义移植**，不是把原有 Rust 验收结果改名为 Python 验收。
下面的测试只能证明各自覆盖的路径，尚不证明完整 Codex 的所有细节等价。

2026-10-29 后续源码审查与原生差分复现了新的任务行为差异；
详见 [任务执行等价性复核](codex-core-audit-2026-10-29.md)。
本报告的通过数不能覆盖该复核中新发现的分支。
后续实现、当前默认行为、测试数量和 wheel 哈希以
[审计修复验收](codex-core-repair-2026-10-29.md) 为准；下文保留审计前证据。

## 实际执行边界

默认调用链是固定 Adapter → 固定 Python loader → **选定 Snapshot 的 Python core**。
`python_core/**` 是 code 组件，主循环、协议、历史、工具和资源代码都在其中。
没有 Rust 编译、CLI 或宿主核心模块兜底；候选语法错误在请求模型前失败。
当前仅支持 Python 核心执行路径；仓库不提供 `cli_path` 或原生 CLI fallback。

逐模块映射与资源原文/派生规则由 `python_core/UPSTREAM.json` 和
`scripts/verify_codex_python_port.py` 核验；固定上游源码需要在仓库外提供。
这个校验只证明来源和资源一致，不能证明移植语义等价。

## 做任务时的等价标准

任务验收针对同一框架配置下的 Responses / Lite、shell、文件编辑、上下文切换和子代理流程。
MCP、app、账号登录等外围能力不作为这轮任务验收的通过条件。
向原生 Codex 和 Python 核心提供相同初始文件、任务、配置和模型回复，
实际执行命令、补丁及检查程序，再比较每一步的完整模型请求、工具反馈、
最终文件、状态和用量。交互终端只额外归一化 session/chunk 标识，并保留引用关系；
命令、退出码、输出内容和工具 schema 均参与比较。

原生侧也通过框架适配层：两侧共同使用 `approval_policy=never`、自定义 API-key provider，
关闭项目 AGENTS 自动发现和 ambient skills，使用 Snapshot 中的指令及技能。
这些结果证明相同接入配置下的行为；不代表裸 CLI 默认配置、原生 shell snapshot
路径或任意模型/执行模式都已等价。

模型回复使用 localhost 回放，工具和文件操作真实执行。没有进行真实模型闭环或
benchmark 解题对照，因此不声称已验证所有任务的解题成功率、采样结果或速度一致。

本轮新增以下原生任务及临界状态对照，逐步比较完整请求，而非仅比较最终回答：

| 场景 | 实际执行及断言 | 测试 |
| --- | --- | --- |
| 测试失败后修复代码 | 读取已有代码、测试退出 1、修改函数并添加 Unicode/空输入检查、重新执行通过；分别运行普通权限与 macOS workspace-write | `test_codex_task_parity.py` 两个参数用例 |
| 坏补丁后修复 | 补丁因上下文不匹配失败、重新读文件、正确修改和验证；同样覆盖两种权限 | `test_codex_task_parity.py` 两个参数用例 |
| 交互终端任务 | 启动真实 PTY、发送 JSON 输入、空轮询、通过第二次 stdin 释放进程、独立检查生成报告；6 次模型请求、5 次工具调用 | `test_codex_task_exec_parity.py` |
| 并行、大输出及多文件编辑 | 两条命令互等标记证明实际并发；长日志截断后保留首尾证据；修改、移动、删除、新增文件并运行检查 | `test_codex_task_history_parity.py` |
| 自动压缩临界阈值 | provider 报告 32,000 tokens、阈值 32,065；两侧均在工具后压缩，3 次完整请求及用量一致 | `test_codex_python_compact.py` |

临界阈值对照在修复前真实失败：Python 少发一次压缩请求。原因是持久化历史缺少
原生逐轮 metadata，低估了本地新增历史的 token 数；现已补齐，并保留 fork 继承的
turn ID。压缩输出、摘要和重注入上下文也使用相同的历史准备边界。
另按固定源码修复 context-length 错误后的窗口用量状态，并验证缓存续轮会先压缩；
后者是源码定向测试，不计作原生双跑对照。

## 验证方法

全部模型调用使用 localhost Responses 回放与假 API key，没有付费模型或真实 benchmark。
历史对照曾使用安装包固定的 `openai-codex-cli-bin==0.147.0`；该依赖已从项目 extras 和锁文件移除。
测试保留完整模型 instructions、工具 schema、历史和元数据，只归一化 UUID、时间及
临时路径；工具退出码、文本和历史顺序仍参与比较。

已建立的专项包括：

- 模型解析与两模型完整请求、SSE 任意分帧/UTF-8、HTTP/stream 重试、部分失败流。
- 完整调用链的回答、工具成功/失败、未知工具、HTTP 重试/拒绝与用量。
- 部分失败流中已完成工具只执行一次；end_turn=false、并行工具和串行屏障。
- 真正修改 Python 主循环的候选、保存/加载、rollout 隔离、update/切回、坏源码不兜底。
- 真实 shell/PTY、stdin、进程组取消、macOS Seatbelt、补丁落盘及验证后应用。
- AGENTS/skills、本地插件、stdio MCP、读写许可、elicitation decline、MCP resources。
- SessionStart/UserPromptSubmit/工具/Stop/PermissionRequest hooks 与 notify。
- v1/v2 子代理角色、输入队列、等待/中断/续跑及会话内保留的线程资源。
- 本地压缩、上下文/权限渲染及已支持图片原样传递的专项测试。

此前 Rust 接入的 1,728 项报告、Rust 候选编译和 V8 宿主测试属于历史参考，
不计入这次 Python 等价验收。

## 本轮长任务扩展

本轮新增的实现与固定原生版本做以下对照。模型回复来自 localhost，shell、补丁、
子代理和 memory 文件操作实际执行；比较包含完整请求、工具反馈、用量和最终文件。

| 能力 | 主要验证 | 测试文件 |
| --- | --- | --- |
| 长上下文 | 手动/自动窗口切换、thread/name 模式、文件证据保留、提醒/fallback、`body_after_prefix`、远程 v1/v2 压缩与失败重试 | `test_codex_python_long_context.py`、`test_codex_python_compact.py` |
| v2 子代理 | 父/子完整首请求；none/all/lastN fork；真实 shell 子任务；中断→排队消息→followup→完成；schema 与角色权限 | `test_codex_python_subagents_v2.py`、`test_codex_python_subagents.py` |
| memory | summary 注入、list/read/search/显式 note、引用解析、I/O 失败行为；原生与 Python 完整任务请求 | `test_codex_python_memory.py` |
| Code Mode | 实际 shell、patch、图片；store/load、yield/wait、通知、终止、错误与工具声明 | `test_codex_python_code_mode.py`、`test_codex_core_extensions.py` |
| Responses Lite | 两个固定目录模型的完整初始请求，包括工具、指令、metadata 与 header | `test_codex_python_lite.py` |
| 缓存续轮 | 模型/effort 更新、会话指令不变、旧模型压缩及失败重试、steering 顺序、续轮后 fork 当前历史 | `test_codex_python_session_resume.py` |
| memory 持久化 | 独立进程读取、候选隔离与切回、符号链接拒绝、并行发布完整笔记 | `test_codex_python_memory_persistence.py` |

缓存旧模型 comp_hash/downshift 分支使用受控 ModelInfo 验证固定源码语义，
不计作原生双跑差分。通知的跨采样到达位置受原生并发调度影响；严格差分使用完成
屏障，另以运行中 cell 测试验证即时注入，没有用延时补丁强制改变通知语义。
新增两个 memory 隔离/并发回归在旧适配实现上均失败，在新实现上通过。

本轮覆盖的 memory 能力是摘要注入、读工具和显式 append-only 笔记。
后续审查纠正：该 commit 的 app-server 有 phase1/phase2 自动抽取与合并调度，
ephemeral exec 不触发；Python 尚未迁移，不能用本轮测试证明它已经接入。
可选 `memory_dir` 由固定适配层按 Snapshot ID 隔离，原子发布笔记，不修改版本资源。

## 本次回归结果

| 检查 | 结果 | 本地记录 |
| --- | --- | --- |
| 冻结代码后的 `tests/test_codex*.py` | **377 passed**，270.99 秒 | `pytest-long-task-frozen.xml`、`.txt` |
| 其余框架测试 | **1,567 passed，1 skipped**，201.48 秒 | `pytest-framework-long-task.xml`、`.txt` |
| Codex 源码、测试、来源脚本 Ruff check | 通过 | `ruff-check-codex-long-task.txt` |
| 上述 Python 文件 Ruff format check | 通过 | `ruff-format-codex-long-task.txt` |
| 离线来源检查 | 24 个核心映射、94 份原样资源、15 份派生资源通过 | `provenance-long-task-final.txt` |

合计 **1,944 项通过、1 项跳过**，没有失败。
这些包括单测、集成回归和原生对照，不能把通过总数解释为同样数量的原生等价证明。
本次未编译 Rust。全仓库 Ruff 仍报告既有实验快照中的 28 项 lint 问题与 26 个
待格式化文件，记录为 `ruff-check-long-task.txt` 和 `ruff-format-long-task.txt`；
本次涉及的 Codex 文件均通过。

复现命令：

```bash
uv run pytest tests/test_codex*.py -o tmp_path_retention_policy=failed
uv run pytest --ignore-glob='tests/test_codex*.py' -o tmp_path_retention_policy=failed
uv run ruff check flashrsi/agents/codex tests/test_codex*.py scripts/verify_codex_python_port.py
uv run ruff format --check flashrsi/agents/codex tests/test_codex*.py scripts/verify_codex_python_port.py docs/codex*.md
uv run python scripts/verify_codex_python_port.py --offline
```

## 安装产物实测

从本次 wheel 安装到新建独立 venv，只选择 `[codex]`；没有安装任何原生 CLI。在源码仓库之外以 Python `-I` 实测：

- 默认 Python 核心回答、BM25 延迟工具检索和实际 shell 执行。
- 选定 Python 源码候选的 save/load、隔离 rollout、update 与基线恢复；坏源码在 HTTP 前失败。
- Responses Lite 中执行 Code Mode，通过安装后的 JS worker 调用真实 shell。
- `new_context` 归档旧窗口后继续读取此前实际写入的任务文件。
- 显式 memory note 跨独立进程保留，候选版本不可读，切回后恢复，Snapshot 内容不变。
- 安装后的 `flashrsi --help` 与 `examples/codex.yaml --prepare-only` 成功。

环境为 Python 3.12.13、macOS 26.5.2、arm64；Code Mode 使用本机 Node。
wheel 为 `flashrsi_lite-0.1.0-py3-none-any.whl`，**787,694 bytes**；SHA-256：

```text
213c7da2f93bbdeb8a18a857a4e6735fcbcbd728543e8be521b42433406d9bd2
```

产物保存在 `dist/` 与 `.cache/codex-python/dist/`。
逐文件检查确认 **137 个核心文件**内容与执行位一致，
包含 `code_mode_worker.js`；安装后 **109 份资源哈希**和
4 份可执行脚本权限通过。wheel 不含 Rust runtime、bridge、编译辅助二进制或字节码缓存。

审计前核心为 **23 个 Python 模块、11,413 行**，另有 180 行 JS worker；
行数包含注释和空行，不含固定适配层、测试、提示词、schema 和其他资源。
Python 负责 harness；JS worker 只对模型提供的 Code Mode 程序求值。

2026-10-29 另对当前代码复跑任务 smoke：**19 passed，12.31 秒**。覆盖两种权限下
测试失败后修复/坏补丁后修复、Lite、Code Mode、手动/自动上下文切窗、六组 v2
父子任务配置，以及 memory 持久化/并发/候选隔离。记录为
`smoke-20261029.xml` 和 `smoke-20261029.txt`。模型响应仍为 localhost 回放，
工具及文件操作实际执行；这不等同于真实模型自主解题闭环。
同日从 `/tmp` 以独立安装环境的 Python `-I` 复跑上述 7 组 wheel 验收，全部通过；
144 个 Codex 包文件与当前源码、安装内容逐字节一致，没有安装原生 CLI。
复验记录为 `smoke-wheel-20261029.json`，wheel 哈希与上述产物相同。

证据位于 `.cache/codex-python/`：`wheel-inventory-long-task.json`、
`wheel-acceptance-long-task.json`、`wheel-cli-help-long-task.txt`、
`wheel-cli-prepare-long-task.txt`、构建/安装日志和验收脚本。
`long-task-evidence.json` 列出本轮主要记录。

## 尚未完成的等价范围

- 子代理跨进程恢复、完整 rollout 数据库与 rollback/legacy compaction 事件重放。
- app-server 自动 memory 提炼/合并，以及 `features.rollout_budget` 父子线程共享任务预算。
- 缓存续轮中的工具/协作协议、初始化资源配置及运行环境变更；这些会明确拒绝。
- WebSocket、账号登录/恢复和账户后端模型 fallback。独立 JS REPL 已由固定上游版本移除。
- execpolicy、shell snapshot/zsh-fork、Linux/Windows 受限 sandbox、自定义权限 profile、交互审批 UI；Windows shell/PTY 后端。
- 远程 HTTP/OAuth MCP、app connectors、managed hook trust/配置层发现及全部插件/skills/schema 边界。
- GIF/TIFF 转码与需 resize 的图片、完整音频/多模态预算。
- Code Mode 不同 V8 版本的全部行为、部分 JSON/serde 错误文案、非 WAV 音频预算和超长计时器。

custom role 的 provider/profile 重载及相对 typed 路径会明确拒绝；同分 BM25
结果的顺序依注册顺序，上游 HashSet 同分顺序本身没有稳定保证。

验证只支持这里列明的路径。尚未运行真实模型闭环或 benchmark 解题对照，
因此不能据此声称任意任务的原生成功率、采样结果、速度或全部行为已经完全一致。
