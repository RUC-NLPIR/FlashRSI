# Codex

通过原生 `codex exec --json` 接入，目标 Agent 和文件编辑 Worker 共用同一个
`Codex` 类。接入不修改 Codex 源码，也不改 Algorithm、Snapshot 或 Benchmark 接口。

## 安装和使用

```bash
uv sync --extra dev --extra codex
uv run flashrsi run --config examples/codex.yaml --agent codex --prepare-only
```

`codex` extra 安装固定版本 `openai-codex-cli-bin==0.147.0`，包含本平台原生二进制。
`--prepare-only` 仅准备配置，不加载任务或调用模型。填写示例中两个角色各自的模型、
API key 和端点后，去掉该参数运行 SkillOpt。也可设置 `cli_path` 使用其他原生 CLI；
该路径按调用进程的当前工作目录解析，兼容性由所选 CLI 决定。

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

## Snapshot 中的原生资源

默认版本只有 `config.toml`，不预装解题指令或 skill；其中关闭插件发现，避免无插件时
刷新外部目录，可在版本配置中启用。可通过 `source_dir`
提供自己的资源目录，该目录需包含 `components.yaml`；内置分类为：

| 组件 | 原生路径 | 加载方式 |
| --- | --- | --- |
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
文件或目录时，Adapter 会在本次 CLI overrides 中转换为运行副本的绝对路径，例如
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

每次调用将所选 Snapshot 的完整资源复制到独立临时 Codex home；原生 CLI 从这个
副本读取配置、指令、skill 和规则。`working_dir` 是任务或编辑目录，与资源 home
分开；不传时创建临时任务目录。运行结束后清理进程及临时状态，原始来源目录不变。
`rollout(tasks, snapshot=candidate)` 评估候选，只有 `update(candidate)` 才切换默认版本。
`code` 组件未声明：Codex 引擎和 Adapter 均在 Snapshot 之外。

为固定显式资源，Adapter 关闭任务项目的 `AGENTS.md` 自动发现和用户、项目及祖先目录
`.agents/skills`、旧式 `.codex/skills`（包括符号链接安装）的技能；任务目录及祖先的
项目配置均设为未信任，避免嵌套工作目录继承 Git 根的信任并加载其配置、hooks 和执行规则。
CLI 保留默认系统指令、bundled skills 及原生功能配置；插件和记忆来自
所选资源 home，`features.plugins`、`features.memories` 等开关不会被强制关闭。
Worker 编辑另一个 Agent 时，加载的是 Worker 自身
Snapshot 中的指令和扩展。这里约束原生资源加载来源，不是操作系统级文件隔离。

模型连接与资源配置分别管理。`config.toml` 不允许设置 `model`、`model_provider`、
`model_providers`、`model_reasoning_effort`、`cli_auth_credentials_store`、
`forced_login_method`、`sqlite_home`、`log_dir` 或 `chatgpt_base_url`。
Adapter 还固定非交互审批、临时状态路径和上述资源发现开关。CLI 使用
`--strict-config`，不认识的原生配置键返回错误。
凭据、会话状态、日志、依赖和任务目录都不进入 Snapshot。

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
存在显式 hook 配置或 `hooks.json` 时，Adapter 使用原生
`--dangerously-bypass-hook-trust` 执行所选版本的 hooks；它不改变任务项目未信任设置，
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
| `timeout` | `300` | 单次调用超时秒数 |
| `sandbox` | `workspace-write` | 原生执行 sandbox 模式 |
| `source_dir` | 内置资源目录 | 需包含组件声明的资源来源 |
| `cli_path` | extra 内的固定二进制 | 自定义 CLI 路径 |

`llm` 当前接受表中列出的四个字段；兼容显式 `auth: api_key`，不接受原生
`auth: login`、`extra_body`、`max_tokens`、
`temperature` 等直接请求参数。`codex exec` 没有本接入支持的 `max_turns` 参数，
设置它会明确报错；使用 `timeout` 控制单次执行时长。
准备和 CLI 启动计入该预算；超时或取消后先中断原生执行，让 Codex 关闭独立的工具
进程会话，再按需终止进程。清理有独立的有限等待时间，因此返回可能稍晚于 `timeout`。

容器使用同样的角色凭据配置，并安装自己的 CLI，不能传宿主 `cli_path`。
来源目录只保留路径身份，用来重定位绝对资源引用；容器加载序列化的 Snapshot，
不读取或重新捕获宿主来源目录。

## 轨迹与验证范围

`messages` 先记录基类的 `RunConfig`，随后是 `RunInput` 和原生 JSONL 事件，
包括工具执行和 `turn.completed`。答案取最终 `agent_message`；失败、超时和
缺少正常结束事件时返回错误轨迹，保留已收到的事件与脱敏 stderr 尾部。
无论任务是否成功，原生 stderr 均作为 `CodexDiagnostics` 保存，因此 skill、MCP、
规则等可选扩展加载失败的诊断不会随成功回答丢失。可选扩展失败是否终止任务仍由
原生配置决定，例如 MCP 的 `required = true`。
`usage` 将原生输入总量映射为 `prompt_tokens`，输出映射为 `completion_tokens`，
缓存输入另记在 `prompt_tokens_details.cached_tokens`，不会重复累加缓存量。
`usage` 的范围就是原生主任务 `turn.completed` 提供的范围，不保证包含子 agent 用量；
CLI JSONL 也不会提供子 agent 的完整消息。框架保留它暴露的协作事件，不补造子轨迹。

本地 CLI 协议测试覆盖配置映射、凭据与诊断脱敏、候选版本隔离、超时和取消。
真实 CLI 对 localhost Responses 服务的测试覆盖回答与用量、候选指令和 skill 发现、
原生工具编辑，以及 Codex 同时作为目标与 Worker 的 SkillOpt 完整演化和最终测试。
扩展测试实际执行候选 hook、读取 skill 正文、派生自定义子 agent，并调用 MCP 的
只读工具与预先批准的写文件工具；插件测试验证候选 bundle 的 skill/hook 及原生路径变量。
非法 skill 的诊断和未知配置键的失败行为也有回归覆盖。测试位于
`tests/test_codex_native.py` 和 `tests/test_codex_plugins.py`。
记忆资源的自动生成与使用尚未验证。这些测试未调用远程模型，也不代表 benchmark 效果。

Harbor 通过 `codex` extra 安装相同版本的 Linux 二进制发行包，再复用现有容器入口；
当前尚未运行 Docker/Terminal-Bench 实际验收。τ³ 的通用文本执行桥接没有新增 Codex
专属分支，真实任务验证也尚未完成。
