# Codex Python 核心审计修复：2026-10-29

本文保留上一批修复及当时的验证结果。后续已迁移 shell snapshot、评估 memory 隔离与
环境记录；当前平台、安装产物和剩余边界见 [任务基线验收](codex-task-baseline-2026-10-29.md)。

固定基线仍为 `rust-v0.147.0` /
`be6e8eac029b183056b7e4402879f15d2c85f61b`。本轮修复
[首次审计](codex-core-audit-2026-10-29.md) 中的任务行为差异，恢复适配层屏蔽的任务输入，
并对相邻的原生机制补充回归。当前实现仍是 Python 语义移植，未完成全量原生机制复刻。

## 已修复的机制

| 机制 | 修复后的行为 | 主要回归 |
| --- | --- | --- |
| Code Mode 错误传播 | 嵌套工具失败拒绝 Promise，模型编写的 catch/恢复分支正常执行 | `test_codex_task_tools_regression.py` |
| Shell 环境 | 以运行时环境作为过滤输入；inherit/exclude/set/include_only 生效；统一执行层再设置原生环境常量 | 同上 |
| Shell 中的补丁 | 用上游同版 Bash grammar 和相同 AST query 识别整条补丁命令；复合脚本通过 Python helper 调用选定核心 | 同上，包含 alias、cwd、heredoc、hook、sandbox |
| 补丁应用 | 工具先验证，再逐次重读文件应用；失败允许保留先前写入；独立 helper 保留原生独立执行路径的部分写入语义 | 同上，包含重复更新、二进制删除、无效正文 |
| 工具参数与退出状态 | 可空预算/超时恢复原生默认值；unified SIGTERM 为 143，classic shell 保留 Sandbox(Signal) 错误 | 同上 |
| v1 子代理容量 | 使用 `max_concurrent_threads_per_session`，计数包含已完成但未关闭的线程 | `test_codex_python_subagents_fidelity.py` |
| v2 派生与角色 | 不套用 v1 深度 guard；full fork 正确替换或追加子代理 developer 指令 | 同上 |
| 服务响应验证 | 统一验证 ResponseItem 的必需字段、类型、嵌套内容和枚举；SSE 丢弃无效项；远程 v1 拒绝无效响应，v2 不安装无效 checkpoint | `test_codex_task_response_validation_parity.py` |
| Skill 规则 | 可选 MCP 缺失继续任务；空白名称回退；64 字符上限；常见环境变量过滤；配置 selector、发现/选择顺序及 include_instructions 生效 | `test_codex_task_resource_validation_parity.py` |
| 项目输入与 provider | 默认恢复项目 AGENTS/skills；显式禁用仍生效；保留宿主资源隔离；OpenAI/Azure 远程压缩可由正常配置触发 | `test_codex_task_integration_parity.py`、`test_codex_python_long_context.py` |
| 技能目录发现 | 按原生完整 BFS 发现嵌套技能；设置深度、目录、条目及结果大小预算；宿主嵌套技能同样隔离，循环链接不导致任务失败 | 资源发现及适配层专项 |
| Git 工作区 metadata | 每轮后台收集 HEAD、remotes、工作区状态；不阻塞首次采样；结束/失败/取消时清理；并发状态查询共享生命周期 | `test_codex_python_turn_metadata.py` |
| 已移除的旧开关 | 按固定上游接受 Removed feature 的兼容 no-op，包含旧 JS REPL 开关 | 同上 |
| 旧 local_shell 协议 | 保留原始历史项，不执行、不单独触发续采样；若其他工具触发续采样，缺失结果由历史规范化补 aborted | `test_codex_task_tools_regression.py` 三种续采样场景 |

最初的七项工具、三项子代理、十三项资源/响应回归先在旧实现上失败，随后修复。
`include_instructions`、Git metadata、Removed feature 和旧 local_shell 分支也分别先验证旧实现失败。
技能 selector 和更多 typed ResponseItem 用例用于验证统一机制，避免只修复单一示例。

主循环、历史、工具、资源和本轮修复代码都位于 Snapshot 的 `python_core/**`。
固定 adapter/loader 只处理配置、临时目录、进程和 Trajectory；没有 Rust、CLI 或宿主核心兜底。
shell 补丁 helper 同样调用选定 Snapshot 内的 Python 文件。

## 验证口径

原生 oracle 使用安装包 `openai-codex-cli-bin==0.147.0`，没有编译 Rust。
全部模型回复来自 localhost 假 key 回放，shell、PTY、补丁、子代理和 memory 文件操作实际执行。
任务差分比较完整模型请求、工具反馈、最终文件、状态及用量，只归一化 UUID、时间、临时路径，
交互工具另归一化 session/chunk ID 并保留引用关系。

Git metadata 的原生后台完成时间不固定，单独比较最终 enrichment 字段及生命周期，
不把其首次出现的请求序号当成确定性等价条件。项目指令专项使用同一自定义项目标记，
避免混入 Git 后台调度差异；真实 Git 仓库由 metadata 专项覆盖。

本轮没有运行付费模型、真实模型自主解题闭环或 benchmark 成功率对照。
回放验证的是覆盖路径中的 harness 行为，不能证明所有任务的成功率或完整执行语义都已等价。

## 最终回归与安装产物

| 检查 | 结果 | 本地记录（均在 `.cache/codex-python/`） |
| --- | --- | --- |
| Codex 全部用例最终结果 | **488 passed**，0 个未解决失败 | `pytest-codex-repair-20261029-final.xml` |
| 其余框架测试 | **1,567 passed，1 skipped** | `pytest-framework-repair-20261029.xml` |
| 适配层完整复跑 | **25 passed** | `pytest-adapter-final-repair-20261029.xml` |
| 取消与记录发布的竞态重复检查 | **10 次通过** | `pytest-cancellation-stress-repair-20261029.txt` |
| Codex 源码/测试/来源脚本 Ruff check、format check | 通过 | `ruff-{check,format}-codex-repair-20261029.txt` |
| 无 CLI 的 wheel 安装验收 | **9 组通过**；109 份资源哈希、4 份执行位通过 | `wheel-acceptance-repair-20261029.json` |
| 安装后的 CLI help / 示例 prepare-only | 通过，无模型调用 | `wheel-cli-{help,prepare}-repair-20261029.txt` |

全量 Codex 用例分为三个互不重叠的批次执行，划分记录在
`pytest-codex-repair-20261029-partitions.json`。原始结果为 487 通过、1 条测试 fixture 失败：
取消测试只等待记录文件出现，在 JSON 写完前就取消了进程。修复为等待完整 PID 记录后，
整个适配层 25 项复跑通过，取消场景再重复 10 次通过。
最终 XML 按每个 case 最后一次实际执行的结果合并；原始三批 XML、失败及复跑证据均保留。
此前还修正了清理测试扫描真实 HOME 导致任务启动前超时的问题；测试现在使用隔离 HOME，
生产适配层的宿主资源枚举也已按固定上游的完整 BFS 和预算限制有界执行。

合计最终 **2,055 个不同测试通过、1 个跳过**；复跑不重复计入总数。
全仓库 Ruff 仍有既有实验快照中的 28 项 lint 问题和 26 个待格式化文件；
本轮 Codex 范围全部通过，原始全仓库记录亦保留。

wheel：`dist/flashrsi_lite-0.1.0-py3-none-any.whl`，**798,288 bytes**。
SHA-256：

```text
c7d6b5e18bb8abd33ed2c201f488f58b07f7ddc844ae121283234fd691a652b7
```

逐文件核验 wheel 中 **137 个核心文件**的内容和执行位与冻结源码一致；
不含 Rust runtime、bridge、编译辅助二进制或字节码缓存。
安装环境为独立 Python 3.12.13 venv、macOS 26.5.2 arm64，没有安装 `codex_cli_bin`。
从 `/tmp` 使用 Python `-I` 验证以下流程：

- 默认核心回答、旧 local_shell 项不触发执行/续采样。
- 延迟工具检索与真实 shell；Lite/Code Mode 的真实嵌套 shell 和错误 catch 分支。
- 核心候选源码 save/load、隔离 rollout、update/恢复；坏候选在 HTTP 前失败，无兜底。
- 上下文 rollover 后继续读取先前写入的任务文件。
- 显式 memory note 在独立进程之间保留、按候选隔离、切回恢复，Snapshot 不变。
- 项目 AGENTS、嵌套项目技能发现及实际 shell 补丁拦截，包含安装后的 Bash parser。

核心现在为 **23 个 Python 模块、12,325 行**，另有 **180 行 JS worker**。
统计包含注释和空行，不包含固定 adapter/loader、测试、提示词/schema/其他资源。
冻结实现哈希在构建、安装和全部回归后保持一致。
汇总证据为 `verification-repair-20261029.json`，来源基线保持原固定 commit。

## 未完成的任务机制

| 能力 | 当前边界 | 固定上游情况 |
| --- | --- | --- |
| Shell snapshot | POSIX 后台捕获、验证、按 cwd 恢复与父子共享已迁移；默认开启 | 持久 state DB、Windows PowerShell/cmd 后端和跨平台执行仍有边界 |
| zsh fork | 显式开启拒绝 | 上游默认关闭 |
| Execpolicy | 发现选定 home 的规则文件后拒绝 | 上游有完整规则与审批决策机制 |
| Rollout budget | `features.rollout_budget` 显式开启拒绝 | 本地父子代理共享预算、提醒和超限终止；默认关闭 |
| 跨进程线程恢复 | 支持运行内缓存、续轮、fork；没有完整 rollout DB、rollback/legacy compaction 重放 | 上游可重建持久会话 |
| 自动 memory 写入 | 只覆盖 summary/读工具/显式 append-only 笔记及可选运行时持久化 | app-server 有 phase1 extraction / phase2 consolidation；ephemeral exec 跳过 |
| 跨平台执行与权限 | macOS Seatbelt 已有对照；Linux/Windows 受限 sandbox、自定义权限 profile、Windows shell/PTY 未完成 | 需要各平台执行后端 |
| 图像和多模态预算 | 预算内 PNG/JPEG/WebP 保留原字节；需 resize/GIF/TIFF 转码拒绝；音频预算只覆盖部分编码 | 不能推断完整多模态任务等价 |

自动 memory 入口为固定源码的 `app-server/src/request_processors/turn_processor.rs:582`，
`memories/write/src/start.rs:33` 跳过 ephemeral、关闭 MemoryTool 或非 root 的会话。
此前文档“该版本没有生产自动 memory 管线”的判断已纠正。
独立 JS REPL 在此版本已移除，不属于待迁移机制；Code Mode 是当前 JavaScript 工具路径。

HTTP/SSE 已覆盖；WebSocket、原生账号登录/恢复、远程 MCP/OAuth、apps/connectors、
managed hook trust 与完整配置层发现仍有边界。自定义子代理 provider/profile 重载、
相对 typed 路径和全部 JSON/serde 错误文案也未证明等价，详见
[来源与范围](codex-core-extraction.md) 和 `docs/codex.md`。

后续任务机制迁移应优先补共享 rollout budget 和持久会话恢复，
再接自动 memory 写入管线；每项均需固定源码映射、失败前验及真实工具差分。
