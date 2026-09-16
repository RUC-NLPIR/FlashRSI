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
| `self.config` | 按原生接口传入模型名、地址等设置；原生用环境变量，就配置子进程的环境 |
| `self.files_dir` | 从这里执行所选版本的代码、加载配置与资源 |
| `working_dir` | 传给 harness 的任务或编辑目录 |

返回 `Trajectory` 时填写答案和状态；原生提供 messages、usage 就一并带回，没有则用默认空值。
调用结束前关闭自己启动的进程或 SDK 会话；运行产物放在版本目录外，保存的记录按项目要求脱敏。

先看短例子：[进程接入](../examples/agents/open_harness/__init__.py)、
[SDK 接入](../examples/agents/closed_harness/__init__.py)。
MiniAgent 的完整实现是 [适配类](../flashrsi/agents/miniagent/__init__.py) 和
[_entry.py](../flashrsi/agents/miniagent/_entry.py)。后者只是它的子进程入口，其他 harness 不必照搬。

## MiniAgent 的调用路径

```text
MiniAgent._run → 子进程 _entry.py → 原生 run → Trajectory
```

适配类直接把 config 映射为原生参数和子进程环境变量，原生 `run` 不接收框架 config，
也没有给 Context、llm、reader 注入客户端。模型设置只在子进程中生效。
`source_dir` 提供的 harness 需支持同样的原生参数和环境变量；没有返回 messages 时留空。

## harness 的小改动

内置 harness 保留以下独立优化；它们不需要 FlashRSI，也不是新 Agent 的接入模板：

| 文件 | 改动 |
| --- | --- |
| `agent.py`、`editor.py` | 增加可选编辑目录，保留自身指令；原生返回已有 messages，保留失败时已产生的输出和用量；检查工具是否启用 |
| `llm.py` | 移除 provider 专用默认值和未使用的 analyzer/LiteLLM 路由；统一使用 OpenAI SDK，保留 Chat/Responses；推理设置和 `extra_body` 显式传入；SDK 重试交给原生循环管理 |
| `trace.py` | 用运行环境中的密钥对原生日志脱敏 |
| `workspace.py` | 默认资源目录改为本包的 `agent.yaml` 所在目录 |

`reader.py`、`tools.py`、`web_config.py`、`tool_result.py` 保持原生逻辑。
`usage` 沿用原生统计范围，包含主循环、辅助调用与强制回答；网页提取用量没有额外补齐。

原生差异集中在 [miniagent-harness.patch](miniagent-harness.patch)，对比来源是旧 FlashRSI
提交 `5efe9b438483710060183c6c3ecbc5062b410a58` 的 `miniagent/harness/*.py`。
对比前对基线使用同样的 Ruff 格式化，以排除纯格式差异。

Review 顺序：`components.yaml` → 适配类 `_run` → `_entry.py` → 上述差异文件。
