# Codex 核心的来源与 Python 语义移植

当前执行核心是 `flashrsi/agents/codex/python_core/`，由 Python 实现。
它以 <https://github.com/openai/codex> 的固定版本语义为参考：

- 版本：`0.147.0`
- tag：`rust-v0.147.0`
- commit：`be6e8eac029b183056b7e4402879f15d2c85f61b`

这是一份人工完成的**语义移植**。上游执行逻辑使用 Rust，不能通过删除 CLI、app
和前端代码机械地得到 Python 实现。当前代码没有宣称全部原生行为等价；已支持路径
通过本地进程测试和固定原生 CLI 对照验证，尚未移植的能力有明确边界。

## 执行边界

框架把选中的 Snapshot materialize 到独立目录，再从其中加载 Python 核心、配置、
指令、skills、hooks、plugins 和 MCP 配置。核心运行过程中不需要编译 Rust，也不
通过原生 Codex CLI 执行模型循环。修改 Snapshot 中的核心或资源会影响下一次执行。
Code Mode 的模型输入本来就是 JavaScript；`code_mode_worker.js` 在每个 cell 的独立 Node V8 上下文求值，工具委派和会话生命周期仍由 Python 管理，不调用 Rust harness。
适配器负责配置、目录、输入输出和事件映射；会话循环、Responses 请求、历史、工具
执行等逻辑位于选中的 Python 核心中。

主要模块及其移植职责与 Snapshot 组件边界如下。组件只影响 checkout/commit 的编辑面，
完整执行仍导出全部 Snapshot 文件，因此拆分不会把运行时依赖截断：

| 模块 | 职责 |
| --- | --- |
| `loop.py`、`context.py` | `code`：会话、初始上下文、采样与工具执行顺序 |
| `models.py`、`client.py` | `code`：固定模型目录、请求字段、HTTP Responses/SSE、重试 |
| `history.py`、`compact.py`、`remote_compact.py`、`context_budget.py` | 历史、用量、压缩 v1/v2、窗口切换和预算 |
| `images.py` | PNG/JPEG/WebP 原始字节传递和图像输入限制 |
| `tools.py`、`shell.py`、`shell_snapshot.py`、`apply_patch.py` | `tool`：工具注册、shell 生命周期、后台环境快照、补丁解析与执行 |
| `subagents.py`、`subagents_v2.py` | `agent`：v1/v2 子代理、mailbox、fork、持续任务与生命周期 |
| `memory.py` | `memory`：summary 自动注入、读取/搜索/列表和 append-only 笔记 |
| `code_mode.py`、`code_mode_spec.py` | `tool`：Python 管理 V8 cells、工具委派、声明和输出 |
| `tool_search.py`、`mcp.py` | `tool`：延迟加载工具、BM25 检索、stdio MCP |
| `resources.py` | `code`：AGENTS.md、skills、指令注入和资源组装 |
| `hooks.py` | `hook`：command hooks、notify 和 hook 生命周期 |
| `plugins.py` | `plugin`：本地已安装插件资源 |

Codex 当前把原先整体 `code` 的核心拆成 11 个核心模块、26 个工具模块、6 个子代理模块、
11 个 hook、2 个 memory、2 个 plugin，以及独立的静态 prompt/skill/config/agent 资源。
`models.json` 仍是混合模型能力、预算、工具配置和 system instructions 的整体 config，
`tools.py` 仍是工具描述、schema 构造和执行逻辑的整体 tool；这两处需要后续提取文件后才能
继续细分，不能只靠 YAML 伪造语义边界。

上表描述实现职责，不能作为完整行为等价的证明。逐模块上游源路径记录在
`python_core/UPSTREAM.json`。

## 原样资源与派生数据

原生模型目录、基础提示词、权限与压缩模板、内置 system skills、hook 输出 schema、
apply_patch 语法和 Seatbelt 策略保持上游字节一致。Codex 的 `LICENSE`、`NOTICE`
一并保留在 Python 核心目录。

部分上游字符串嵌在 Rust 源码中，移植时将其提取为运行时数据：skills 目录提示、
plugins 提示、MCP resource 工具定义、spawn_agent 模板、v2 协作提示、Code Mode 声明模板与工具返回 schema、bash/zsh/sh snapshot 捕获脚本，以及内置角色描述。
这些属于**派生数据**：JSON 容器的字节不同于 Rust 文件，字段与字符串内容可以
机械地对照上游重建，不能称为整个文件原样复制。

工具检索还使用固定 `Cargo.lock` 中 deunicode 1.6.2 和 stop-words 0.9.0 的数据，
以及 bm25 2.3.2、rust-stemmers 1.2.0 的算法语义。来源记录包含 registry archive
checksum、归档内路径及文件哈希；相应许可证一并保留。依赖数据通过归档对照，
不需要运行这些 Rust crate。

`python_core/UPSTREAM.json` 分别记录：

- Python 模块的语义来源及集成模块类型；
- 每个上游参考文件的固定路径和 SHA-256；
- 运行时资源的 SHA-256、原样复制或派生类型、派生规则；
- 已知未移植范围，以及不宣称完整行为等价的声明。

模块源码是本项目维护的 Python 代码，其内容不可能与 Rust 文件字节相等。
来源检查不会把模块路径映射解释成实现等价，也不会将测试通过解释成全路径证明。
算法产生的后代 Snapshot 可以修改核心或资源；这些候选版本由 Snapshot 自身内容
哈希标识，初始上游来源校验用于维护仓库中的基线。

## 校验

在仓库根目录执行：

```bash
uv run python scripts/verify_codex_python_port.py
```

脚本不访问模型、不运行 Rust 编译器。它检查固定版本身份、Python 模块清单、
参考源哈希、运行时资源清单与哈希、复制资源的逐字节一致性，以及派生数据能否从
固定 Rust 源码重新提取。`--core` 可指定待验证的 Python 基线目录，`--reference`
可指定包含 `UPSTREAM.json` 的 Rust 参考目录。
第三方 crate 归档优先复用本机缓存；缺失时下载固定 crates.io 归档并验证锁中的
checksum，缓存到 `.cache/codex-python-provenance/`。加 `--offline` 可要求只用已有缓存。

该检查证明来源和资源数据一致；语义移植需要另外运行受影响的 Python 测试及
原生对照。参见 [任务基线验收](codex-task-baseline-2026-10-29.md) 了解当前验证
结果和限制。原生 CLI 对照只连接 localhost 的预设响应服务，不调用付费模型。

## 上游来源记录

Rust runtime、bridge 和原生构建辅助文件已从仓库移除。固定版本、上游路径和资源
来源仍记录在 `python_core/UPSTREAM.json`，用于维护 Python 语义移植和资源哈希；该
记录不要求仓库内保存 Rust 源码，也不提供原生 CLI fallback。需要重新核对上游时，
在仓库外检出固定 commit，并将参考目录传给
`scripts/verify_codex_python_port.py --reference /path/to/reference`；仓库不再提供
把 Rust 源码复制进运行目录的 extraction/build 工具。

## 当前限制

当前主要覆盖 custom API-key provider 的 HTTP Responses / Lite 任务和持久子代理会话，
包括 Code Mode、本地/远程压缩、token-budget rollover 和 `body_after_prefix` 预算。
WebSocket、原生账号登录与恢复、音频及多模态用量估算尚未完整移植。
该固定版本已移除独立 JS REPL，保留 Code Mode；不将旧版功能自行加回基线。
Code Mode 由 Python 调度本机 Node V8 worker；不同 V8 版本、全部错误诊断文字、
非 WAV 音频预算及超长计时器边界尚未证明等价。
图像当前保留原生预算内 PNG/JPEG/WebP 的原始字节；需要 TIFF/GIF 转码或 resize
的路径在原生编码器与滤镜移植完成前明确拒绝。

执行层已经迁移 POSIX shell snapshot 的后台捕获、验证、条件恢复和清理；
使用文件系统查询清理遗留快照，尚未接入原生持久 state DB。
执行层尚未覆盖 execpolicy 规则、zsh-fork、交互审批 UI、
Linux/Windows 受限 sandbox 及自定义网络/文件系统 sandbox profile。
Windows 还缺少 shell、进程组和 PTY 执行后端；`danger-full-access` 不能使其可用。
`external-sandbox` 也未接入。
自定义子代理角色 TOML 尚不支持重新加载 provider/profile，明确拒绝顶层
`model_provider`、`model_providers`、`profile`、`profiles`。它也拒绝有类型约束的
相对路径字段：嵌套 `config_file`、`cwd`、`model_instructions_file`、
`experimental_compact_prompt_file`、`model_catalog_json`、`js_repl_node_path`、
`sqlite_home`、`log_dir`、`export_dir`、`load_path`，以及 `writable_roots`、
`js_repl_node_module_dirs` 数组中的相对路径。
资源层尚未覆盖远程 MCP HTTP/OAuth、远程 MCP 执行环境、plugin apps/connectors，
以及原生 managed hook trust 和完整配置层发现流程。v1/v2 子代理及
`SubagentStart`、`SubagentStop` hooks 已接入；未接入的配置层发现流程不能统一归为显式拒绝。
memory 当前覆盖该 commit 的 summary 注入、读工具和显式笔记行为。
上游 app-server 另有 phase1 extraction / phase2 consolidation 管线，
ephemeral exec 不触发；Python 尚未移植这条长期持久会话能力。
可选运行时笔记持久化属于固定适配层，保存在 Snapshot 之外，用于普通 `run` 的在线积累。
`rollout` 的初始 memory 只来自选定 Snapshot，题内笔记不跨题传播；memory 指纹和环境证据写入轨迹。
子代理会话持久性限于一次运行，跨进程恢复、完整 rollout 数据库以及 rollback/旧压缩事件
重放尚未迁移。缓存续轮支持兼容模型、effort 和预算更新；改变工具协议、资源配置或环境会明确拒绝。
`features.rollout_budget` 的父子线程共享预算、提醒和超限终止尚未移植；该开关
在固定上游默认关闭，Python 显式启用时会拒绝。

本地插件、skills 目录压缩、MCP schema 清理等已有实现也未覆盖全部原生边界条件。
这些属于后续逐项移植和补充对照的范围，不能据现有测试推断已经完全保真。
工具检索对相同 BM25 分数保留注册顺序；上游的同分顺序来自 Rust HashSet，
本身没有固定顺序保证。
