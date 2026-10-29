# 限定编辑目录的 Claude Code Worker 示例

此可选 profile 用于只需要文件编辑的 smoke。通过已有 `source_dir` 加载原生
plugin hook，使用原生 `claude_code` system prompt；不改变默认 Target 或 Worker。

在实验配置的 `algorithm.worker` 中设置以下字段，模型凭据仍独立填写：

```yaml
type: agent
name: claude_code
source_dir: /absolute/path/to/examples/claude_edit_worker
tools: [Read, Write, Edit, Glob, Grep]
allowed_tools: [Read, Write, Edit, Glob, Grep]
disallowed_tools: [Bash, Agent, WebFetch, WebSearch]
max_turns: 20
timeout: 240
```

Linux 开发机需要 `python3`，hook 通过
[原生 PreToolUse 协议](https://code.claude.com/docs/en/hooks#pretooluse)检查工具访问的
实际路径，拒绝当前目录之外的读取、写入、搜索和其他工具。算法随 checkout 提供的
临时证据仍可读。请配套使用上述工具列表；这是文件工具访问策略，不是操作系统沙箱，
也不隔离随后执行的候选代码、原生扩展或所有自动加载行为。需要 shell 或联网的任务
应另行配置合适的运行隔离，不能把本示例当作通用执行环境。

本示例的验证包括确定性路径检查、真实原生 hook 越界读取探针与实际算法 smoke；
探针不计入 Benchmark 组合通过数。历史未使用此 profile 的记录不自动获得隔离保证。
