# Terminal-Bench 2.0

Terminal-Bench 的任务需要在 Linux 环境内执行命令、修改文件，再由任务自带的 verifier
评分。Benchmark 负责数据与评分，Harbor 负责环境和执行，两者都不选择具体 Agent。
Claude Code 和 MiniAgent 共用容器执行路径；MiniAgent 默认启用 shell 工具，在任务容器中
执行命令。SkillOpt 保持原实现，通过相同的 `rollout`、`grade` 和 Snapshot 接口演化。

## 数据与划分

`benchmark.name` 为 `terminal_bench`。不指定 `data_path` 时，从私有 Hugging Face 仓库
[jinjiajie/flashrsi](https://huggingface.co/datasets/jinjiajie/flashrsi) 下载固定版本的
`terminal_bench` 数据镜像，共 89 个原生任务。上游是官方 `terminal-bench@2.0`，来源提交为
[`69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`](https://github.com/laude-institute/terminal-bench-2/tree/69671fbaac6d67a7ef0dfec016cc38a64ef7a77c)；
镜像固定到 HF 提交
[`d96c128fbc4f7eea52d355f07de3ea3a6e36627c`](https://huggingface.co/datasets/jinjiajie/flashrsi/tree/d96c128fbc4f7eea52d355f07de3ea3a6e36627c)，
也记录在 `TerminalBench.metadata` 中。

仓库保持 private，需要有读取权限的本机 Hugging Face 登录（`hf auth login`）或
`HF_TOKEN` 环境变量。下载使用 `hf_hub_download` 的原生认证与缓存，凭据无需写入 YAML。
框架核对归档 SHA-256，安全解包到本地后由 Harbor 解析任务；默认加载不再经过 Harbor registry。
Harbor 继续负责原生任务解析、容器执行和 verifier。

Terminal-Bench 的一道题是一棵可执行的文件树，包含环境定义、资源文件、测试与参考解法，
不能只保存成问答表格。`tar.gz` 保留目录结构、二进制内容及脚本执行权限；Parquet
用于浏览索引。解压由 `load()` 自动完成，使用者无需手动操作压缩包。

镜像中的文件分别用于浏览索引与执行任务：

| 文件 | 内容 |
| --- | --- |
| `terminal_bench/tasks.parquet` | 89 行索引，列为 `id`、`question`、`task_path`、`task_checksum`、`category`、`difficulty` |
| `terminal_bench/tasks.tar.gz` | 完整原生任务目录，保留脚本执行权限 |
| `terminal_bench/manifest.json` | 上游版本、任务数量与文件校验和 |
| `terminal_bench/README.md` | 镜像来源及使用说明 |

可以像 SearchQA 一样从同一个 HF 仓库读取对应配置：

```python
from datasets import load_dataset

data = load_dataset("jinjiajie/flashrsi", "terminal_bench")
print(len(data["tasks"]))  # 89
```

这里读取的是任务索引。框架的 `TerminalBench.load()` 会自动取得执行需要的完整目录：

```python
from flashrsi.benchmarks import TerminalBench

benchmark = TerminalBench({"split": "auto", "seed": 42, "limit": 6})
splits = benchmark.load()
print({split: len(tasks) for split, tasks in splits.items()})
```

`load()` 只准备数据，不启动 Docker 或调用模型。首次加载会下载完整归档，`limit`
只限制本次选用的任务数。现有 SearchQA 文件及其固定版本保持不变。

官方数据是一组评测任务，没有 train/dev/test 划分。`split: auto` 使用框架的确定性规则，
按 60%/20%/20% 构造演化实验划分；这不是官方划分。`seed` 控制划分，`limit` 限制实验任务数。
自动划分至少需要 3 个任务，SkillOpt 还要求 train/dev 非空。
HF 配置中只有名为 `tasks` 的完整任务集合；运行时划分不会改写镜像。

`benchmark.data_path` 可指向单个原生任务目录，或直接包含多个任务目录的数据目录。
任务目录包含 `task.toml`、`instruction.md`、`environment/` 与 `tests/` 等原生文件。
本轮支持单步 Linux 任务。相对 `data_path` 按当前工作目录解析，与现有 SearchQA 一致；
它不采用 `run.output_dir` 相对 YAML 文件的解析规则。

本地可重新生成发布文件：

```bash
uv run --python 3.12 --extra harbor python scripts/prepare_terminal_bench.py
# 输出到 .cache/terminal_bench/publish；此命令只下载和打包，不上传。
```

脚本固定上游版本并生成归档、索引、manifest 和说明；缓存与发布产物不进入 Git。

## 安装与配置

FlashRSI-Lite 本身仍支持 Python 3.11；Harbor 0.23 需要 Python 3.12 或更新版本。
在项目目录安装 Harbor、所选 Agent 和 Worker 的依赖，例如 Claude Code 目标与纯 LLM Worker：

```bash
uv sync --python 3.12 --extra harbor --extra claude-code --extra llm
docker info
```

Docker Engine 与 Compose 插件必须可用。首次运行还需要下载任务镜像、uv 和容器依赖。
HF 数据镜像不含 Docker 镜像层：89 个 `task.toml` 都引用 `alexgshaw/<task>:20251031`，
执行仍需从镜像仓库取得这些镜像，并能访问安装依赖所需的网络地址。

当前 Harbor 使用预构建镜像，归档中的 Dockerfile 不会自动代替镜像下载；
原生 verifier 也可能在测试阶段安装依赖。因此“任务数据只来自本 HF 仓库”已经成立，
“整个评测执行只依赖本 HF 仓库”尚未成立，预先缓存任务镜像也不保证离线执行。
任务文件固定了版本与校验和，但镜像使用 tag，容器与 verifier 的传递依赖也未全部锁定。
若要实现完整离线运行，还需要镜像归档或自有镜像源，以及容器、测试和任务资源的依赖镜像。

MiniAgent 目标将上面的 `--extra claude-code` 换成 `--extra miniagent`。
容器内通过 uv 安装与宿主相同版本的 `PyYAML` 和 Agent extra 声明的依赖（从安装包元数据读取）：Claude Code 使用
`claude-agent-sdk`，MiniAgent 使用 `openai`、`requests`。当前 FlashRSI 源码与所选
Snapshot 分别传入容器，再运行现有适配器；宿主虚拟环境不会被复制。
安装使用任务中的 curl 或 wget；两者都没有时，通过 apt-get 安装 curl 和 CA 证书，
因此这种最小镜像需要 Debian/Ubuntu 包管理器及安装权限。

目标模型使用 `agent.llm`，Worker 使用 `algorithm.worker.llm`，两者独立。
凭据和端点直接填写在配置中，例如 `api_key: your-api-key`，运行前替换为实际值。
Claude Code 也支持配置 `llm.auth_token` 或 `llm.oauth_token`，三种凭据择一。
MiniAgent 的网页工具配置为 `web.search_url`、`web.browse_url`、`web.api_key`，默认未启用。
入口将完整角色 config 传进容器，不另外转发宿主环境变量。
地址需要从容器内可达；容器中的 `localhost` 指向容器自身。宿主的 Claude 登录状态
不会自动成为容器认证；`llm.auth: login` 只支持本机运行，容器要求显式凭据。

Claude Code 保留原生 `claude_code` system prompt。终端任务需要显式允许命令和文件工具，
例如 `allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]`；现有权限配置仍由原生 CLI 执行。
Claude Code 的容器执行不支持宿主 `cli_path`。

| 配置 | 含义 |
| --- | --- |
| `agent.timeout` | 单任务执行超时；省略时采用任务原生 agent timeout，任务也未声明时为 300 秒 |
| `agent.max_turns` | 所选 Agent 的最大轮数，按任务需要显式设置 |
| `agent.harbor.setup_timeout` | 环境内安装和准备的超时，默认 600 秒 |
| `agent.harbor.cleanup_grace` | Harbor 执行期限比 Agent 内部超时额外增加的时间，供 Agent 退出及写轨迹，默认 30 秒；环境清理由 Harbor 管理 |
| `benchmark.limit` | 本次实验选用的任务数 |

## 先运行一个任务

单任务接入检查可以直接使用 Python，不需要 Worker。将下面代码中的任务路径、模型名和
API key 换成实际值，按需修改连接地址。执行会调用目标模型并启动任务容器。

```python
import asyncio

from flashrsi.agents import ClaudeCode
from flashrsi.benchmarks import TerminalBench
from flashrsi.integrations.harbor import bind


async def main():
    benchmark = TerminalBench(
        {
            "data_path": "/absolute/path/to/one-task",
            "split": {"train": 0, "dev": 0, "test": 1},
        }
    )
    benchmark.load()
    agent = ClaudeCode(
        {
            "llm": {
                "model_name": "your-claude-model",
                "api_key": "your-api-key",
                "base_url": "https://api.anthropic.com",
            },
            "max_turns": 30,
            "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"],
            "harbor": {"setup_timeout": 600, "cleanup_grace": 30},
        }
    )
    bind(agent)
    results = benchmark.grade(await agent.rollout(benchmark.test))
    for result in results:
        print(result.task.task_id, result.status, result.metrics["reward"])
        if result.error_message:
            print(result.error_message)


asyncio.run(main())
```

这里显式把任务放入 test，避免单任务无法自动划分的问题。这种配置用于接入检查，
不能交给要求非空 train/dev 的 SkillOpt。直接 Python 调用返回内存中的 Trajectory；
CLI 演化使用实验目录保存记录。直接 Python 使用需要调用 `bind(agent)`；CLI runner
会为 Terminal-Bench 自动绑定目标 Agent，Worker 保持自己的运行方式。

MiniAgent 使用相同的 `bind(agent)`、`rollout` 和 `grade` 调用，只需替换 Agent 类与
自身配置。默认 `shell` 在镜像原生 WORKDIR 执行 `/bin/sh -c`，支持管道、重定向，
以及可选 `cwd`、`timeout`（默认 60 秒）；整次执行仍受 `agent.timeout` 限制。
工具返回退出码和合并输出，最多保留 32 KiB；每次调用不保留 shell 会话状态，
正常结束后保留任务需要的后台服务，超时或取消时清理当前命令进程组。
服务的 stdout/stderr 应重定向到日志文件，命令退出后工具会关闭输出收集，
不会等待后台进程关闭输出。Harbor 在 verifier 完成后随容器清理服务。
文件工具限于任务工作目录，shell 可访问容器权限允许的路径。

## 运行小规模演化

保存下面配置为 `terminal-bench.yaml`，填写模型名和连接配置。省略 `data_path` 使用固定的
HF 数据镜像；使用本地数据时，在 `benchmark` 中添加该字段。

```yaml
run:
  output_dir: ./runs

benchmark:
  name: terminal_bench
  split: auto
  seed: 42
  limit: 6

agent:
  name: claude_code
  llm:
    model_name: your-claude-model
    api_key: your-api-key
  max_turns: 30
  allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
  harbor:
    setup_timeout: 600
    cleanup_grace: 30

algorithm:
  name: skillopt
  num_epochs: 1
  max_steps: 1
  worker:
    type: llm
    llm:
      model_name: your-worker-model
      api_key: your-worker-api-key
```

```bash
uv run flashrsi run --config terminal-bench.yaml
```

项目已提供同样结构的 [examples/terminal_bench.yaml](../examples/terminal_bench.yaml)，
也可直接覆盖模型运行：

```bash
uv run flashrsi run --config examples/terminal_bench.yaml \
  --model YOUR_CLAUDE_MODEL --worker-model YOUR_WORKER_MODEL
```

这会运行 dev baseline、一个 train batch、候选 dev 评估以及最终 test，调用目标和 Worker
模型。空编辑会跳过候选评估；候选只有严格提高 dev 平均 reward 才会被选择。
`max_steps` 限制演化 batch 数，不是容器数量或模型调用次数。

## 接入边界与验证

`TerminalBench.load()` 把原生任务映射成 `Task`，`env` 保存任务目录。
runner 把 Harbor 执行器绑定到目标 Agent；`Agent.rollout()` 在整批开始时固定 Snapshot
和角色配置，将环境任务交给该执行器。Harbor 0.23 的 Trial 管理任务环境和 verifier。
私有 bridge 按 Agent 类的可导入路径构造适配器、核对 Snapshot 类型，恢复所选版本，
再调用现有 `Agent.run(prompt, working_dir)`。Harbor 与容器入口没有按 Agent 名称分支。
候选保留原始版本 ID 和来源，执行不会选择或改写宿主目标版本。
容器入口以隔离的 Python 导入路径加载框架，保留任务原有的 `PYTHONPATH` 和工作目录，
任务工具仍使用镜像提供的环境。

这里的解耦是算法和 harness 不需要识别具体 benchmark。当前仍有两处明确的连接约定：
runner 为 `TerminalBench` 选择 Harbor；`TerminalBench.grade()` 读取 Harbor 的 verifier
事件，`Task.env` 在此执行器中解释为 Harbor 原生任务目录。这是 MVP 的执行与评分协议，
并不意味着任意 benchmark 或执行环境可以零适配接入。新增环境后端需要在 runner 连接
对应执行器，并将评分结果映射为该 Benchmark 所需的反馈；算法继续使用相同公共接口。

Agent 自己声明容器依赖 extra（外部适配器也可声明发行包列表）及必要检查。未声明容器支持的 Agent
会在执行前报错；接入方法见 [Agent 接入说明](agent-integration.md#可选容器执行)。
外部 Agent 必须可导入，并将适配器的发行包列入容器依赖；接入层不会自动复制任意外部源码。

每个任务使用独立环境；任务执行与原生验证完成后清理环境。`TerminalBench.grade()`
读取宿主追加的 `HarborVerifier` 结果，将 `reward` 写入 metrics，不自行运行容器，也不采信
模型报告的分数。模型正常结束且 reward 为 0 表示任务没有通过；基础设施或执行错误
保留错误状态与诊断，评分为 0。训练反馈可以进入反思，最终 test 反馈不进入 Worker。
Agent 非零退出（包括内部执行超时）通过 Harbor 的原生错误类型报告，verifier 仍会运行，
结果与日志保存在轨迹中；这不会将错误轨迹改为成功。容器入口未生成轨迹时，错误信息
保留 Docker 合并输出中的诊断。

验证需要分别记录三个层次：

1. 离线测试：任务映射、划分、评分、参数传递、候选与配置固定、失败和取消清理。
2. 真实容器检查：环境安装、现有适配器运行、任务文件修改、原生 verifier 和环境清理。
3. 真实模型演化：完整 CLI 流程、候选实际生效、接受或拒绝记录及最终 test。

HF 镜像已回读验证：89 个任务、857 个文件、12 个可执行文件与发布包一致；
两个 HF 配置均可加载，SearchQA 保持 400/200/1400。Terminal-Bench 默认自动划分为
53/18/18；`seed: 42`、`limit: 6` 时为 4/1/1。离线测试使用真实 Harbor
Trial/Verifier、模拟 Environment 和通用容器入口，覆盖两种 Agent 的执行、记录与清理。
MiniAgent 另有真实子进程和 SDK 的本地测试：模拟模型调用文件工具或 shell 修改任务文件，再由
原生 test.sh 评分，验证候选 Snapshot 生效。shell 测试覆盖 Chat/Responses 两种协议的
真实命令执行、退出码、输出截断、单命令超时、整次运行超时与取消时的子进程清理。
新增回归覆盖后台服务跨 shell 调用、Agent 退出及 verifier 验证继续存活，脱离进程组的
子进程持有 stdout 时及时返回，以及任务导入路径保留、失败后的验证与启动错误诊断。
当前机器没有可用的 Docker/Podman，真实容器和真实模型演化尚未验证。
