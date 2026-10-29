# 接入一个 Agent

优先使用 harness 已有的函数、CLI 或 SDK，保留原生代码。框架接入只需要组件声明和
一个 `Agent` 子类；原生文件不必依赖 FlashRSI。

## 只做两件事

**1. 在接入类旁放 `components.yaml`，声明可演化文件。**

按 harness 原有目录填写路径，例如：

```yaml
code:
  - runtime/**
prompt:
  - prompts/**
skill:
  - skills/**
```

接入代码留在规则之外。基类负责收集文件、导出所选版本和清理版本目录。

**2. 继承 `Agent`，声明 `name`、`description` 并实现 `_run`。**

`_run` 调用原生入口，再把结果转为 `Trajectory`。它用到三个输入：

| 输入 | 用途 |
| --- | --- |
| `self.config` | 当前调用固定的角色配置；模型名、地址和请求参数从 `self.config.llm` 读取，执行参数读取该角色自身字段 |
| `self.files_dir` | 从这里执行所选版本的代码、加载配置与资源 |
| `working_dir` | 传给 harness 的任务或编辑目录 |

返回 `Trajectory` 时填写答案和状态；原生提供 messages、usage 就一并带回，没有则用默认空值。
调用结束前关闭自己启动的进程或 SDK 会话；运行产物放在版本目录外，保存的记录按项目要求脱敏。

目标 Agent 使用 `TargetAgent(config.agent)`，Worker 使用
`WorkerAgent(config.algorithm.worker)`；构造函数拒绝整份实验配置。两种角色各自拥有
独立的 `llm`，适配器不需要判断自己的角色。`timeout`、`max_turns`、权限和
`source_dir` 等执行参数留在角色层；原生资源配置继续从 `self.files_dir` 加载。

初始化会复制配置，之后通过实例的 `config` 调整下一次执行的默认值。单次 `run` 和
整批 `rollout` 都固定开始时的配置；`_run` 只读取本次副本。基类在 messages 前加入
脱敏的 `RunConfig`，记录角色配置和 Snapshot ID；适配器直接返回原生 messages 即可。
该记录包含当前角色配置，不展开后端默认值，也不等同于完整模型请求。
用户参数统一来自 config；模型、凭据和端点直接填写在各角色的 `llm` 中。
原生 CLI 必须使用 env 时，由适配器从 config 构造子进程 env。
登录与连接由框架的角色配置提供：目标和 Worker 分别设置自己的 `llm`，凭据不进入
Snapshot。接入 harness 时重点保留它的工具、skills、hooks、子 agent 等执行能力；
不要求复刻原生产品的账号登录界面或账号管理命令。
日期、二进制、集合等非 JSON 的 YAML 值以 `type: yaml` 和 YAML 文本 `value`
记录，保证 trajectory 可序列化；实验配置文件保留这些值的原类型。
`update(snapshot)` 只选择资源版本，不更改模型或连接配置。

先看短例子：[进程接入](../examples/agents/open_harness/__init__.py)、
[SDK 接入](../examples/agents/closed_harness/__init__.py)。
MiniAgent 的完整实现是 [适配类](../flashrsi/agents/miniagent/__init__.py) 和
[_entry.py](../flashrsi/agents/miniagent/_entry.py)。后者只是它的子进程入口，其他 harness 不必照搬。
Claude Code 的 [适配类](../flashrsi/agents/claude_code/__init__.py) 直接创建官方 SDK 会话，
默认使用原生 `claude_code` system prompt，不预装 skill 或附加指令；
从 `files_dir` 加载按需添加的原生插件（skills、agents、hooks 等）、MCP 和 settings，
将 `working_dir` 传为 cwd，并关闭隐式项目配置。SDK 事件含子 agent 的文本和父子 ID；
适配器负责等有限子任务结束及收集其主 agent 回复，公共 Trajectory 保持不变。
`CLAUDE.md` 可以不存在或为空；版本中提供非空内容时，经 SDK `system_prompt.append`
追加。这是显式选择 Snapshot 资源，不是 CLI 的目录发现与分层加载。默认版本不含这个文件。
会话与子任务输出使用独立临时运行目录，关闭历史 auto memory，仅在 `llm.auth: login` 时从原位置读取原生凭据。
扩展加载失败、SDK 异常和暂停／中止结果返回错误轨迹，并保留脱敏诊断。

Codex 的 [适配类](../flashrsi/agents/codex/__init__.py) 默认在独立 Python 进程中执行
选定 Snapshot 的 `python_core/`，不调用原生 CLI，也不回退宿主核心。
将 Snapshot 的核心与资源复制到每次调用独立的 home，加载 `AGENTS.md`、skills、
配置、hooks 和显式插件；任务 cwd 仍由 `working_dir` 指定。宿主的技能、插件
和历史记忆不会自动混入所选资源；项目 AGENTS/skills 作为任务输入发现。
未迁移能力有明确边界，例如 rules 执行策略尚未实现。POSIX shell snapshot 默认开启，
生成、条件恢复与清理均由 Snapshot 内的核心负责。
插件只版本化 `plugins/cache/**` 下的已安装 bundle 及其元数据；`plugins/data/**`
等运行状态不从来源目录捕获，插件启用配置保留在 `config.toml`。
模型与凭据通过角色配置映射，Python 核心的 JSONL 事件和脱敏诊断转为 Trajectory，
退出时清理进程与运行状态。服务、hooks 和子 agent 仍需配置注册；
显式设置 `cli_path` 的原生 CLI 模式仅用于对照，不执行 Python 候选源码。接入与验证边界见
[Codex 说明](codex.md)。

## 可选：容器执行

只有接入带 `Task.env` 的任务时才需要这一步；普通问答、文件编辑和 Worker 接入仍按
上面的两步完成。环境执行器由 runner 连接，Agent 不需要实现 Terminal-Bench 或 Harbor 专属钩子。

内置适配器用 `_container_extra` 引用 `pyproject.toml` 中已有的 extra（如 `miniagent`），
从安装包元数据读取依赖，避免维护第二份包名列表。外部适配器仍可用
`_container_dependencies` 声明发行包名元组；两者默认 `None` 表示未支持容器。
`_check_container()` 做执行前检查，覆写时先调用基类检查；Claude Code 在这里检查
`cli_path` 和显式凭据。容器直接接收解析后的完整角色 config，不转发宿主环境配置。
版本化资源仍从 `self.files_dir` 读取，容器任务目录仍通过 `working_dir` 传给 `_run`。

Harbor 安装声明依赖在宿主上的对应版本，将框架源码和 Snapshot 分别传入容器，
按可导入的 Agent 类路径创建实例，再调用现有 `run`。外部适配类必须可导入，其发行包
也需列入依赖；任意外部源码不会自动复制。声明容器支持前应确认 harness 能在 Linux 中
运行，并具备目标任务所需的工具。内置 MiniAgent 已通过原生 workspace tool 提供 shell；
容器支持声明本身不检查某个 harness 是否能完成具体任务。
框架入口隔离自身的 Python 导入路径，保留任务环境的 `PYTHONPATH` 供任务工具使用。

CLI runner 为 Terminal-Bench 自动绑定 Harbor。直接 Python 使用在 `rollout` 前调用：

```python
from flashrsi.integrations.harbor import bind

bind(agent)
```

未绑定环境执行器时，`rollout` 会在开始任何任务前拒绝带 `Task.env` 的整批任务。
数据、依赖和验证范围见 [Terminal-Bench 说明](terminal-bench.md)。

## MiniAgent 的调用路径

```text
MiniAgent._run → 子进程 _entry.py → 原生 run → Trajectory
```

适配类通过 stdin JSON 直接传入 `llm_config=config.llm`、`web_config=config.web`、
`debug_llm_io` 和其他原生运行参数。原生 `run` 接收普通字典并初始化当前子进程的
模型与网页工具设置；无需导入框架 Config，也不读取 `FLASHRSI_*` 或 `OPENAI_*` 回退。
`source_dir` 提供的 harness 需支持同样的函数参数；没有返回 messages 时，
最终轨迹仍包含基类添加的 `RunConfig`。

## harness 的小改动

内置 harness 保留以下独立优化；它们不需要 FlashRSI，也不是新 Agent 的接入模板：

| 文件 | 改动 |
| --- | --- |
| `agent.py`、`editor.py` | 增加可选编辑目录，Context 向工具提供任务工作目录；保留自身指令；原生返回已有 messages，保留失败时已产生的输出和用量；检查工具是否启用 |
| `llm.py` | 移除 provider 专用默认值和未使用的 analyzer/LiteLLM 路由；统一使用 OpenAI SDK，保留 Chat/Responses；推理设置和 `extra_body` 显式传入；SDK 重试交给原生循环管理 |
| `trace.py` | 用显式配置和运行环境中的密钥对原生日志脱敏 |
| `workspace.py` | 默认资源目录改为本包的 `agent.yaml` 所在目录；自动发现目录型 SKILL.md，只展示 description 并提供按需读取工具；平铺 skill 继续内联 |
| `tools/read_skill.py`、`tool_descriptions/read_skill.json` | 存在目录型 skill 时自动提供的原生工具，按需读取发现的 skill 正文，不返回 frontmatter；与 workspace 配合，不依赖框架或算法 |
| `tools/shell.py`、`tool_descriptions/shell.json`、`agent.yaml` | 默认启用原生 shell 工具，支持工作目录、超时和有界输出收集；正常完成时保留后台服务，超时或取消清理当前命令进程组；随 Snapshot 版本化，不依赖框架或 benchmark |

`web_config.py` 改为读取传入的 `web` 字典；`reader.py`、`tools.py`、`tool_result.py` 保持原生逻辑。
`usage` 沿用原生统计范围，包含主循环、辅助调用与强制回答；网页提取用量没有额外补齐。

原生差异集中在 [miniagent-harness.patch](miniagent-harness.patch)，对比来源是旧 FlashRSI
提交 `5efe9b438483710060183c6c3ecbc5062b410a58` 的 `miniagent/harness/*.py`。
对比前对基线使用同样的 Ruff 格式化，以排除纯格式差异。

目录型 skill 的发现与加载属于 MiniAgent 原生 workspace 能力：扫描
`skills/<name>/SKILL.md`，展示 description，按需读取正文。目录存在时提供 `read_skill`，
删除最后一个目录后工具随之移除（原生配置显式启用的工具仍保留）。配置中的
`skills` 列表仍只负责原有平铺 `.md` 的全文内联；同名目录和平铺文件会明确报错。
Evo-Harness 只编辑 skill 文件，配置由既有 Snapshot 权限保持只读，无需额外激活声明。
自定义来源目录需要自行保留相应的原生发现和加载能力；算法不会改写其 runtime。

Review 顺序：`components.yaml` → 适配类 `_run` → `_entry.py` → 上述差异文件。
进程桥接在收到终止信号时取消原生执行；适配类给工具最多两秒完成清理，再强制终止。
