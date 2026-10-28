# Codex

默认执行 Snapshot 中的原生 Rust 核心源码，目标 Agent 和文件编辑 Worker 共用同一个
`Codex` 类。核心固定为 Codex **0.147.0**、commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`；从上游机械抽取核心及其完整本地依赖，
保留原有工具、配置、扩展和线程实现，移除 CLI、TUI、app-server 等产品入口。
FlashRSI 的固定 bridge 负责配置输入、调用原生线程入口和转发原生事件。

核心源码属于 Snapshot 的 `code` 组件，演化后会重新编译并执行所选源码。
抽取方法、逐文件来源哈希和允许的构建清单差异见
[codex-core-extraction.md](codex-core-extraction.md)。

## 安装和使用

```bash
uv sync --extra dev --extra codex
uv run flashrsi run --config examples/codex.yaml --agent codex --prepare-only
```

默认源码执行还需要可用的 Cargo 和 Rust **1.95.0**；版本由 runtime 内的
`rust-toolchain.toml` 声明。首次执行会在 Snapshot 外的缓存目录编译核心；依赖尚未
缓存时需要下载。源码、bridge、工具链或编译环境发生变化时使用不同的构建缓存，
成功产物记录 SHA-256。
构建失败会返回错误，不回退到已安装的 Codex 引擎。

`codex` extra 安装固定版本 `openai-codex-cli-bin==0.147.0`，提供 `rg`、`zsh` 等
发行包工具以及上游 CLI 对照基线，默认执行不调用该 CLI。构建缓存默认位于用户缓存
目录的 `flashrsi/codex-core`，可用
`FLASHRSI_CODEX_BUILD_CACHE` 指定其他目录。

code-mode 的独立宿主源码也在 Snapshot 中。macOS arm64 上，若其全部本地依赖源码、
资源、清单和 lockfile 与固定基线一致，允许复用同一官方 tag 的宿主构建产物；下载和
执行前均校验固定 SHA-256。这是未修改源码的构建缓存，不按候选自行声明的来源判断。
相关文件有任何改动、显式指定不同构建参数或平台没有已验证产物时，必须从候选源码
编译宿主，不能复用旧产物。`CoreBuild.companion_build` 记录实际使用的路径。

上游 V8 150.4.0 未发布此版本所需的 sandbox 预编译库，因此宿主源码构建会保留原有
sandbox 特性并构建 V8；macOS 需要完整 Xcode，仅 Command Line Tools 不够。
主核心的普通源码构建不要求安装完整 Xcode。显式设置 `V8_FROM_SOURCE=1` 会强制走
宿主源码构建，也可用于有完整构建环境时的独立验收。

`--prepare-only` 仅准备配置，不加载任务、编译核心或调用模型。填写示例中两个角色
各自的模型、API key 和端点后，去掉该参数运行 SkillOpt。

显式设置 `cli_path` 时切换为原生 `codex exec --json` 对照模式。该路径按调用进程
当前工作目录解析，兼容性由所选 CLI 决定。此模式执行所指定的外部 CLI；Snapshot
里的资源仍被选用，但 `runtime/` 的源码改动不会进入这个外部二进制。

```python
import asyncio

from flashrsi.agents import Codex

agent = Codex(
    {
        "llm": {
            "model_name": "your-codex-model",
            "api_key": "your-api-key",
            "base_url": "https://your-responses-endpoint/v1",
        },
    }
)
result = asyncio.run(agent.run("Explain the supplied task."))
print(result.status, result.output)
```

端点必须支持 Codex 使用的流式 **Responses API**；仅支持 Chat Completions 的地址
不能直接使用。未提供 `base_url` 时使用 `https://api.openai.com/v1`。
模型、端点和凭据都来自当前角色的 `llm`，不会从另一个角色或宿主 API 环境变量回退。
API key 通过子进程环境传入，返回轨迹会脱敏。
框架负责接收、固定和脱敏这些角色配置，Adapter 负责将其映射为 Codex 原生参数；
本接入只使用显式 API key，不读取宿主 `auth.json` 或启动原生账号登录流程。

作为算法 Worker 时配置如下；其模型配置与目标 Agent 独立：

```yaml
algorithm:
  worker:
    type: agent
    name: codex
    llm:
      model_name: your-worker-model
      api_key: your-api-key
      base_url: https://your-responses-endpoint/v1
```

算法仍调用 `worker.ask(prompt)` 或 `worker.edit(directory, prompt)`。
编辑目标目录不会自动提交 Snapshot，版本提交由调用算法负责。

## Snapshot 中的核心与原生资源

默认版本包含 `runtime/` 核心源码和 `config.toml`，不预装解题指令或 skill；
配置关闭插件发现，避免无插件时刷新外部目录，可在版本配置中启用。
可通过 `source_dir` 提供自己的版本目录，该目录需包含 `components.yaml`；
默认源码执行还要求该版本包含完整的 `runtime/`，不能只提供扩展资源。内置分类为：

| 组件 | 原生路径 | 加载方式 |
| --- | --- | --- |
| `code` | `runtime/**` | 选定版本的 Rust 核心、依赖源码、原生提示词及构建清单，编译后执行 |
| `prompt` | `AGENTS.md` | 作为本次原生资源 home 的全局指令读取，可不存在 |
| `skill` | `skills/**` | 原生发现 `skills/<name>/SKILL.md`，根据任务按需使用 |
| `agent` | `agents/**` | 子 agent 的配置资源，需满足原生配置及注册关系 |
| `hook` | `hooks/**` | 在原生 `config.toml` 中注册的 hook 脚本 |
| `tool` | `servers/**` | MCP 等服务脚本，需在原生配置中注册，并准备其运行依赖 |
| `plugin` | `plugins/cache/**` | 原生已安装插件 bundle，作为一个整体版本化 |
| `memory` | `memories/**` | 显式提供的原生记忆文件，是否使用由原生配置控制 |
| `config` | `config.toml`、`rules/**` | 原生配置和执行规则 |

skill 使用 Codex 原生 frontmatter，包括 `name`、`description` 和后续正文。
`skills/` 下的辅助脚本随版本保留，但普通文件不会因为归入 `skill` 就自动启用。
同样，新增 `servers/` 或 `agents/` 文件后，还需在 `config.toml` 中建立对应原生注册。
组件分类检查文件归属和修改权限，不代替 Codex 的资源发现、解析与加载规则。

stdio MCP 的 `command` 或独立 `args` 元素使用含 `/` 的相对路径、且对应版本内现存
文件或目录时，Adapter 会在本次原生配置 overrides 中转换为运行副本的绝对路径，例如
`args = ["servers/probe.py"]`。顶层文件须写为 `./probe.py`，裸名称按原样传递，
因此 `python -m servers` 和 `--name servers` 不会因版本里存在同名目录而被改写。
指向 `source_dir` 内的绝对路径也会重定位，外部依赖的绝对路径保持原样。
Snapshot 内的原始配置不变；复合 shell 命令中的路径不会被解析或改写，
这类命令可显式使用 `$CODEX_HOME`。

`skills.config` 中指向来源目录内 skill 的绝对路径同样跟随所选版本重定位，
使 `enabled = false` 在资源复制后仍然生效。推荐使用 `skills/probe/SKILL.md`
这样的相对路径，便于跨机器使用。

MCP 子进程的环境变量由原生 `env_vars` 控制；需要读取资源或任务路径时，可注册为：

```toml
[mcp_servers.local_tools]
command = "python3"
args = ["servers/tools.py"]
env_vars = ["CODEX_HOME", "FLASHRSI_TASK_DIR"]
default_tools_approval_mode = "approve"
```

`default_tools_approval_mode` 沿用原生 MCP 工具许可设置。框架采用非交互执行，
需要询问用户且没有预先批准的工具会被原生取消；只读标注与显式批准均由 Codex 处理。
也可按工具配置，例如 `[mcp_servers.local_tools.tools.write_file]` 下设置
`approval_mode = "approve"`，不必批准整个服务。

每次调用先绑定所选 Snapshot 的核心构建，再把扩展资源复制到独立临时 Codex home；
核心源码保留在构建副本中，运行时从资源 home 读取配置、指令、skill 和规则。
`working_dir` 是任务或编辑目录，与资源 home
分开；不传时创建临时任务目录。运行结束后清理进程及临时状态，原始来源目录不变。
`rollout(tasks, snapshot=candidate)` 评估候选，只有 `update(candidate)` 才切换默认版本。
开放 `code: rw` 时，算法可以修改原生实现；候选构建与基线使用各自源码和产物。
Python Adapter、构建辅助函数和固定 `_bridge/` 包装均在 Snapshot 之外。

为固定显式资源，Adapter 关闭任务项目的 `AGENTS.md` 自动发现和用户、项目及祖先目录
`.agents/skills`、旧式 `.codex/skills`（包括符号链接安装）的技能；任务目录及祖先的
项目配置均设为未信任，避免嵌套工作目录继承 Git 根的信任并加载其配置、hooks 和执行规则。
核心保留默认系统指令、bundled skills 及原生功能配置；插件和记忆来自
所选资源 home，`features.plugins`、`features.memories` 等开关不会被强制关闭。
Worker 编辑另一个 Agent 时，加载的是 Worker 自身
Snapshot 中的指令和扩展。这里约束原生资源加载来源，不是操作系统级文件隔离。

模型连接与资源配置分别管理。`config.toml` 不允许设置 `model`、`model_provider`、
`model_providers`、`model_reasoning_effort`、`cli_auth_credentials_store`、
`forced_login_method`、`sqlite_home`、`log_dir` 或 `chatgpt_base_url`。
Adapter 还固定非交互审批、临时状态路径和上述资源发现开关。两种执行模式均使用
原生严格配置解析，不认识的配置键返回错误。
凭据、会话状态、日志、下载的第三方依赖、编译产物和任务目录都不进入 Snapshot。
原生 core 算法和工具实现保留，不表示运行环境等同于用户交互式 Codex 的默认环境；
审批策略、资源发现来源和临时状态边界由上述实验配置确定。

## Hooks 与插件

例如在 `hooks/session.py` 放置 hook 脚本，在版本内 `config.toml` 注册：

```toml
[features]
hooks = true

[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = 'python3 "$CODEX_HOME/hooks/session.py"'
timeout = 5
```

Hook 的工作目录是任务目录，`CODEX_HOME` 指向本次 Snapshot 的运行副本，
`FLASHRSI_TASK_DIR` 指向任务目录。注册关系仍属于 `config`，脚本属于 `hook`；
只开放 `hook` 的算法可以修改脚本，不能同时修改注册配置。

Codex 的 hook 信任键包含配置文件的绝对路径，每次临时导出后原有信任键会失效。
存在显式 hook 配置或 `hooks.json` 时，Adapter 启用原生 hook 信任绕过
（CLI 模式对应 `--dangerously-bypass-hook-trust`）执行所选版本的 hooks；
它不改变任务项目未信任设置，
也不替原生启用被配置为 disabled 的 hook。

插件沿用 Codex 的已安装布局，例如：

```text
plugins/cache/flashrsi/demo/local/
  .codex-plugin/plugin.json
  skills/probe/SKILL.md
  hooks/hooks.json
```

在 `config.toml` 中设置 `[features]` 的 `plugins = true`，并配置
`[plugins."demo@flashrsi"]` 和 `enabled = true`。
插件内的脚本通过原生 `PLUGIN_ROOT` 定位 bundle。插件作为 `plugin` 整包修改，
其中的 skills/hooks 不重复归入顶层 `skill`/`hook`，避免一份文件属于多个编辑 scope。
版本保留 bundle 内的 manifest、安装元数据和辅助文件，启用配置仍在 `config.toml`。
`plugins/` 下只捕获 `cache/**`；`data/**`（原生 `PLUGIN_DATA`）及 bundle 外的状态、
凭据和目录缓存均被忽略。运行产生的数据只留在临时 home，不回写 Snapshot。
开启原生插件发现时，Codex 还会尝试刷新外部插件目录；本地 bundle 不依赖刷新成功。
离线测试通过运行环境的代理将这些后台请求限制在本地。

## 运行参数与框架凭据

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `llm.model_name` | 必填 | 原生模型名 |
| `llm.api_key` | 未设置 | API 模式必须显式提供 |
| `llm.base_url` | OpenAI 官方 `/v1` 地址 | Responses 兼容端点 |
| `llm.reasoning_effort` | 未设置 | 传给原生 `model_reasoning_effort` |
| `timeout` | `300` | 核心构建完成后的单次执行超时秒数 |
| `sandbox` | `workspace-write` | 原生执行 sandbox 模式 |
| `source_dir` | 内置版本目录 | 包含组件声明、核心源码和原生资源的来源 |
| `cli_path` | 未设置，编译 Snapshot 核心 | 设置后使用外部原生 CLI 对照模式 |

`llm` 当前接受表中列出的四个字段；兼容显式 `auth: api_key`，不接受原生
`auth: login`、`extra_body`、`max_tokens`、
`temperature` 等直接请求参数。两种执行模式均没有本接入支持的 `max_turns` 参数，
设置它会明确报错；使用 `timeout` 控制单次执行时长。
源码编译和等待共享构建锁不计入 `timeout`；它们属于执行环境准备，首次构建可能较长。
资源准备和执行进程启动计入该预算；CLI 对照模式从调用开始计时。
超时或取消后先中断原生执行，让 Codex 关闭独立的工具
进程会话，再按需终止进程。清理有独立的有限等待时间，因此返回可能稍晚于 `timeout`。

容器使用同样的角色凭据配置，不能传宿主 `cli_path`。默认源码执行要求容器也具备
匹配的 Rust/Cargo 工具链和构建依赖；宿主构建产物不直接跨平台复用。
来源目录只保留路径身份，用来重定位绝对资源引用；容器加载序列化的 Snapshot，
不读取或重新捕获宿主来源目录。

## 轨迹与验证范围

默认核心模式的 `messages` 先记录基类的 `RunConfig`、`RunInput` 和 `CoreBuild`，
后者包含构建源码指纹、编译器及产物 SHA-256。bridge 直接输出原生
`Event { id, msg }`，保留原生 `msg.type`、工具事件、token 计数和扩展事件，
不经过 CLI 的 item 汇总。启动和终止元数据使用 `flashrsi.core.started`、
`flashrsi.core.completed`；答案和状态来自原生 turn 的终止结果。
这保留核心实际公开的事件，不补造原生入口没有提供的子 agent 完整历史。

CLI 对照模式继续保留 CLI JSONL 的 `item.*`、`turn.completed` 等事件，
答案取最终 `agent_message`。两种模式在失败、超时或缺少正常结束事件时均返回错误轨迹，
保留已收到的事件与脱敏 stderr 尾部。
无论任务是否成功，原生 stderr 均作为 `CodexDiagnostics` 保存，因此 skill、MCP、
规则等可选扩展加载失败的诊断不会随成功回答丢失。可选扩展失败是否终止任务仍由
原生配置决定，例如 MCP 的 `required = true`。
`usage` 将原生输入总量映射为 `prompt_tokens`，输出映射为 `completion_tokens`，
缓存输入另记在 `prompt_tokens_details.cached_tokens`，不会重复累加缓存量。
默认核心模式的用量来自原生主线程的 token 计数；CLI 模式使用主任务
`turn.completed` 提供的用量。两者均不额外估算子 agent 用量，子线程是否计入总量
由原生统计决定。

来源校验命令为 `uv run python scripts/extract_codex_core.py --verify`；
它检查抽取基线的逐文件哈希及额外文件，不能替代运行行为验证。

`tests/test_codex_core_parity.py` 提供同一 localhost Responses 回放下的上游 CLI/核心
对照入口，比较归一化后的模型请求、答案、错误和用量，场景包含回答、工具成功与失败、
未知工具、HTTP 重试和失败；另有修改 Rust 源码、保存/恢复 Snapshot、切换候选并重新编译
后检查实际模型请求变化的用例。这些对照仍需实际编译并运行通过后才能视为已验收；
不能据此推断所有原生能力都已证明等价。

现有 `tests/test_codex.py`、`tests/test_codex_native.py`、
`tests/test_codex_plugins.py` 及资源隔离测试继续覆盖 CLI 对照路径的配置映射、
凭据脱敏、超时/取消、候选资源、原生工具编辑、SkillOpt、hooks、skills、子 agent、
MCP 与插件资源。记忆资源的自动生成与使用尚未验证。
这些本地回放不调用远程模型，也不代表真实 benchmark 效果。

Harbor 复用现有容器入口和 `codex` extra；源码模式的工具链安装与
Docker/Terminal-Bench 实际验收尚未完成。τ³ 的通用文本执行桥接没有新增 Codex
专属分支，真实任务验证也尚未完成。
