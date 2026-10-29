# Codex 任务执行等价性复核：2026-10-29

复核基线为 `rust-v0.147.0` /
`be6e8eac029b183056b7e4402879f15d2c85f61b`。
对照使用已安装的 `openai-codex-cli-bin==0.147.0`，没有编译 Rust。
以下为首次只读审计时的**修复前记录**，源码位置对应当时版本。
后续修复和新的验收结果见 [审计修复验收](codex-core-repair-2026-10-29.md)。

审计时的结论：已有可复现的单次任务行为差异，不能把 Python port 的任务效果视为与原生等价。
此前 377 项 Codex 回归和 19 项任务 smoke 的通过结果，仍只支持那些测试覆盖的路径。

所有模型请求均为 localhost 回放，shell、补丁、子代理和文件操作实际执行。
部分回放根据真实请求/工具反馈选择后续动作，使分支和最终文件差异可被观察。
本报告证明 harness 的行为分歧，没有测量真实模型的解题成功率差距。

## 正常任务与错误恢复中的确定差异

| 编号 | 触发条件 | 固定原生行为 | 修复前 Python 行为 | 对任务的影响 |
| --- | --- | --- | --- | --- |
| T1 | Code Mode 中 `try { await tools.view_image({path:"missing.png"}) } catch (...) { ... }` | 缺失文件使 Promise reject，执行 catch | 工具错误被转换为成功返回值，执行成功分支 | 模型生成的检查、重试与恢复逻辑走错分支 |
| T2 | 配置 shell environment 的 inherit/exclude/set，父环境存在相同变量 | 排除的变量消失，set 值生效 | 过滤完成后被整份父环境重新覆盖 | 执行环境与显式配置不同，可能使用错误工具链或测试配置 |
| T3 | 在 shell 中使用 `apply_patch <<'PATCH' ... PATCH`，PATH 没有外部 apply_patch | harness 拦截并应用补丁，创建文件 | 当普通 shell 命令执行，退出 127，文件未创建 | 原生能够完成的常见编辑动作直接失败 |
| T4 | 同一补丁两次 Update 同文件，两个 hunk 都匹配旧内容 `a` | 第一处写入 `b`，第二处因上下文不匹配失败，最终文件为 `b` | 两处都基于旧 `a` 预计算，报告成功并最终写 `c` | 文件状态、成功判定和后续修复依据都不同 |
| A1 | v2，默认 max_depth 下 root→worker→grandchild | 创建孙代理并真实写入 `grandchild-proof.txt` | 复用了 v1 深度 guard，拒绝孙代理 | 多层任务分解能力被额外限制 |
| A2 | v2 full-history fork，父代理没有 developer 指令，配置了 subagent_developer_instructions | 补充子代理 developer 指令 | 仅尝试替换已有片段，漏掉补充 | 子代理收到的角色/执行要求不同；已观察到实际文件内容不同 |
| A3 | v1，`agents.max_concurrent_threads_per_session=1`，已有一个未关闭子线程 | 拒绝第二个子线程 | 读取了旧配置名 max_threads，仍启动第二代理并执行 shell | 并发/容量限制、任务数量与成本行为不同 |
| R1 | 显式使用声明了未配置 MCP 依赖的 skill | 仍将 skill 注入上下文并继续模型请求 | 在请求模型前抛异常，整个任务 error | 缺少可选依赖时无法采用原生的继续/降级路径 |

T1、T2、T3、A1、A2、A3 应优先修复；T4 涉及合法补丁语法下的失败恢复，同样必须对齐。
R1 涉及用户不优先要求的 MCP 能力，但它当前会中止整个 skill 任务。

## 源码位置与证据

- **T1**：`python_core/tools.py:510`、`:974`。原始请求和反馈位于
  `.cache/codex-python/audit-20261029/tools/code_mode_nested_error/`。
  原生输出 `CATCH_BRANCH`，Python 输出 `SUCCESS_BRANCH`。
- **T2**：`python_core/shell.py:55`、`:103`；adapter 将完整 environment 交给 Shell。
  `tools/environment_policy_canary/summary.json` 中，原生得到
  `AUDIT_ENV_CANARY=null`、`AUDIT_ENV_OVERRIDE="configured-value"`；Python 得到
  `"parent-visible"`、`"parent-value"`。测试只输出无敏感信息的 canary。
- **T3**：`python_core/shell.py:275` 缺少原生 shell handler 中的 apply_patch 拦截路径。
  `tools/shell_apply_patch_without_binary/summary.json` 中原生创建 `from-shell.txt`，
  Python 返回 `/bin/sh: apply_patch: command not found`。
- **T4**：`python_core/apply_patch.py:267`、`:295`。
  `tools/patch_repeated_file/summary.json` 保留了退出码、完整反馈及 `b`/`c` 文件状态。
- **A1**：`python_core/subagents_v2.py:554`。原生 v2 的工具可见性及 spawn 路径没有这一 v1 深度 guard。
- **A2**：`python_core/subagents_v2.py:687`；原生
  `runtime/core/src/agent/control/spawn.rs:796` 有缺少父片段时追加子代理指令的逻辑。
- **A3**：`python_core/subagents.py:456`；原生
  `runtime/core/src/config/mod.rs:3793` 使用 max_concurrent_threads_per_session。
- **R1**：`python_core/resources.py:493`；原生
  `runtime/core/src/mcp_skill_dependencies.rs:42` 的条件安装/继续逻辑不会无条件中止任务。

上述相对路径中的 `python_core/`、`runtime/` 均相对
`flashrsi/agents/codex/`；证据路径中的 `tools/` 相对
`.cache/codex-python/audit-20261029/`。

子代理完整记录在 `subagents/summary.json` 及每项的 native/python requests 文件，
工具完整记录在每个场景的 `native.json`、`python.json` 和 `summary.json`。
独立审查员的逐项上游源码对照另保存在 `subagents/REPORT.md` 与 `tools/findings.md`。

## 输入与服务响应边界

另外确认以下边界，不能据此推断正常有效 checkpoint 也存在同样差异：

- **无效远程压缩 checkpoint 被安装**：服务返回 compaction item，但缺少必需的
  encrypted_content。原生丢弃无效 item 后报错，2 次请求；Python 接受并替换历史，
  清除原工具结果后继续第 3 次请求，最后返回 finished。
  位置：`python_core/history.py:209`、`remote_compact.py:308`、`:348`。
  原生约束：`runtime/protocol/src/models.rs:1021`、
  `codex-api/src/sse/responses.rs:334`、`core/src/compact_remote_v2.rs:425`。
  证据：`semantics/malformed-checkpoint-{native,python,summary}.json`。
- **空白 skill 名称的 fallback**：`name: "   "` 时，原生使用目录名称并注入 skill，
  Python 报名称无效并跳过。位置：`python_core/resources.py:89`。
  证据：`resources/blank_name-{native,python}.json`。
- **环境变量被识别为 skill mention**：存在名为 HOME 的 skill 时，普通 `$HOME`
  在原生中被环境变量过滤规则排除；Python 会注入该 skill 正文。
  位置：`python_core/resources.py:468`，原生 `runtime/skills/src/mentions.rs:201`。
  证据：`resources/environment_name-{native,python}.json`。
- **可空参数**：`exec_command` 的 max_output_tokens 为 null 时，原生使用默认上限并
  返回实际输出；Python 执行命令后 int(None) 出错，历史中只剩合成的 aborted。
  这是原生 serde 接受但工具 JSON schema 未显式允许的参数边界。
  证据：`tools/exec_null_max_output/summary.json`。
- **文本补丁删除二进制文件**：原生验证要求 UTF-8，遇到无效字节时拒绝并保留文件；
  Python 只验证文件可读，随后删除。证据：`tools/patch_delete_binary/summary.json`。
- **信号退出码**：进程收到 SIGTERM 时，原生 exec_command 返回 143，Python 返回 -15。
  两侧都表示失败，但模型可见的退出码语义不同。证据：`tools/exec_signal/summary.json`。

## 与裸 CLI 默认设置的区别

以下是审计时的集成策略，不应混入上述移植缺陷的数量；后续修复已调整这些默认值：

- 固定适配层在 `__init__.py:327` 将 project_doc_max_bytes 设为 0，并禁用宿主/项目 skills。
  因此任务项目的 AGENTS 自动发现与裸 CLI 默认行为不同。原生差分测试的两侧都使用了这个覆盖。
- `__init__.py:389` 将 API-key 连接配置为显示名 FlashRSI endpoint 的 custom provider。
  普通 OpenAI URL 下，这会选择 custom provider 的本地摘要路径；原生内建 OpenAI
  provider 的远程压缩默认行为不能直接据相同适配层的测试推断。
  远程压缩专项测试显式替换过 provider 显示名，而普通调用没有这项替换。

这些设置有资源可复现和运行隔离的目的，但比较“原生效果”时必须对齐。

## 复现

在 FlashRSI-Lite 根目录执行以下脚本；均使用 localhost，原生可执行文件来自固定安装包：

```bash
uv run python .cache/codex-python/audit-20261029/tools/audit_tools.py
uv run python .cache/codex-python/audit-20261029/tools/extra_tools.py
uv run python .cache/codex-python/audit-20261029/subagents/repro.py
uv run python .cache/codex-python/audit-20261029/resources/probe.py
uv run python .cache/codex-python/audit-20261029/semantics/reproduce.py
```

复现材料保留在 `.cache/`，属于本机审计记录，不随 wheel 发布。
上述材料保留审计时的失败证据；修复后的正式回归在 `tests/test_codex_task_*.py`
及子代理专项中，详见 [审计修复验收](codex-core-repair-2026-10-29.md)。
