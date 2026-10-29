# Codex 任务基线：状态、shell snapshot 与 Linux 验收

本批次按 [演化方案](codex-evolution-plan.md) 完成评估初态隔离、环境记录、
POSIX shell snapshot 和目标平台安装验收。固定参考仍为 `rust-v0.147.0` /
`be6e8eac029b183056b7e4402879f15d2c85f61b`。
这是 Python 语义移植的阶段验收，不是全 Codex 机制或任务成功率已等价的声明。
上一批修复保留在 [历史报告](codex-core-repair-2026-10-29.md)。

## 本批次实现

**固定评估初态。** `Codex.rollout` 沿用现有公共签名，通过已有的私有执行上下文
固定评估配置。每题只从所选 Snapshot 复制初始 memory，题内工具可正常读写，
结束后丢弃改动；显式配置的运行时 `memory_dir` 不参与加载或回写。
该标记经过既有容器配置序列化仍有效。配置 `memory_dir` 的普通 `run` 保留在线积累行为，
两者用 `CodexRunEnvironment.mode` 区分，没有修改公共 Agent/Snapshot/Trajectory 契约。

**可核验的运行条件。** 轨迹记录 Snapshot ID、初始 memory 指纹、模型/provider/effort、
feature overrides、预算、权限、OS、Python/依赖、Node 与实际选中的 shell。
memory 指纹最多扫描 4,096 个条目、16 MiB、50 ms；遇到符号链接、超限或读取失败，
标记 `complete=false`、`sha256=null`，不会把部分结果当完整初态。
版本探测在独立诊断目录后台执行，单项最多 0.5 秒，结束收集最多 0.1 秒；
失败不改变任务结果，重复取消也清理探测进程及其后代。
这些记录不含 memory 正文与凭据，数据划分和题目仍由既有实验配置/Trajectory 记录。

**恢复上游默认的 shell snapshot。** 新增 `python_core/shell_snapshot.py`，
bash/zsh/sh 捕获脚本从同一固定 Rust 源码机械提取，并纳入派生资源校验。
捕获、验证和发布在后台执行，各阶段按原生超时处理；命令只查看已完成结果，
不等待捕获。只有 cwd 词法匹配且使用 login shell 时恢复 snapshot；
显式环境、代理/证书变量和运行时 PATH 按固定上游规则恢复。
生成失败沿用直接执行路径，v1/v2 子代理共享父级 shell/snapshot，保留引用生命周期，
取消工具不删除共享快照，v2 驱逐后能重新加载。成功捕获不误杀启动脚本有意保留的后台服务。
遗留 snapshot 清理使用文件系统 rollout 查询，原生持久 state DB 尚未迁移。

**修复 Linux 的资源 home。** 固定上游会拒绝在系统临时目录下创建可执行 helper。
原先默认 `/tmp/flashrsi-codex-*/codex` 导致复合 shell 中的 `apply_patch` helper 不可用。
现在 Python/native 适配器均使用私有用户 cache 中的每次运行临时资源目录：
优先 `XDG_CACHE_HOME`，否则 macOS 的 `~/Library/Caches` 或 Linux 的 `~/.cache`，
`flashrsi/codex` 父目录及每次运行目录权限为 `0700`，结束后删除运行目录。
任务和诊断目录仍在系统临时目录，避免将用户 HOME 祖先指令带入任务。
没有删除原生 helper guard；用户若显式把 cache 放在系统临时目录，仍会触发该限制。
cache 创建失败直接报错，不回退到会使 helper 失效的目录。

**修复容器时区上下文。** 实际 Docker 对照发现：没有系统时区配置时，原生写入
`Etc/UTC`，旧 Python 写入 `UTC`。现按固定 `Cargo.lock` 的 `iana-time-zone 0.1.65`
移植 Linux 检测顺序：`/etc/localtime` 的原始 readlink、`/etc/timezone`、OpenWRT 配置，
保留上游字符串处理规则，不以 `TZ` 取代系统检测。检测失败时同时使用 UTC 日期和
`Etc/UTC`，避免本地跨日时只修时区名称。增加 16 项回归及依赖 checksum/许可证来源。
非 Linux 的时区检测仍有近似行为，已列入 `UPSTREAM.json`，本轮不宣称该分支完整等价。

Snapshot 继续包含真正执行的 Python 核心；固定 adapter/loader、凭据和运行状态位于其外。
候选核心损坏时失败，没有 Rust、CLI 或宿主核心回退。

## 验证与证据

全部模型响应来自 localhost 预设 Responses/SSE；shell、文件、补丁、PTY、进程取消、
Code Mode 和 memory 操作实际执行。原生 oracle 为安装包
`openai-codex-cli-bin==0.147.0`，未编译 Rust，未调用付费或真实远程模型。
原生差分比较完整模型请求、工具返回和任务产物；只归一化 UUID、时间、临时路径、
session/chunk ID 等非语义字段，并保留它们的引用关系。

证据根目录：`.cache/codex-python/stage1-20261029/`。
首次构建和旧实现结果保留在 `first-build/`、`pre-timezone/`、`linux/before/`、
`linux/fixture-before/`、`docker/timezone-before/`，不算作最终 wheel 验收。

| 检查 | 本批次结果 | 证据 |
| --- | --- | --- |
| 最终 Codex 用例 | **568 passed，10 skipped**；跳过项为 Linux 专属用例 | `pytest-codex-part{1,2,3}.xml` |
| 非 Codex 框架回归 | 1,567 passed，1 skipped | `pytest-framework.xml` |
| 无原生 CLI 的 macOS wheel 安装验收 | 10 组通过，111 份资源哈希、4 份执行位通过 | `wheel-acceptance.json` |
| 安装后 CLI help / 示例 prepare-only | 通过，无模型调用 | `wheel-cli-{help,prepare}.txt` |
| 真实 Linux 安装 wheel | **120 passed**，0 failures/errors/skips | `linux/verification.json`、7 组 XML/log |
| 实际 Docker 安装 wheel | **120 passed**，0 failures/errors/skips | `docker/verification.json`、7 组 XML/log |
| 固定来源核验 | 25 个模块映射、95 份原样资源、16 份派生资源通过 | `provenance.txt` |
| Codex 源码、测试和来源/验收脚本 Ruff | check、format check 通过 | `ruff-{check,format}.txt` |

非 Codex 框架回归在本批次早期执行，后续只修改 Codex 及其测试/文档，
受影响的 Codex 用例在最终生产代码冻结后重新验证。
最终 Codex 用例按三个互不重叠的文件集合执行，分片清单和逐片结果保存在
`pytest-codex-partitions.json`、`pytest-codex-results.json`；无失败复跑合并或重复计数。
Linux 和 Docker 各自另运行了 macOS 专属 snapshot 对照，实测各 **7 skipped**，
保存在各自的 `mac_only_snapshot.xml`，不计入 120 passed。
全仓库 Ruff 仍报告既有实验快照中的 28 项 lint 问题和 26 个待格式化文件；
本批次范围全部通过，原始全仓库输出保留为 `ruff-*-repository.txt`。

失败前验包括旧 Python 拒绝 shell snapshot、评估初态跨题污染、版本探测的
重复取消/诊断 cwd 副作用，以及两端旧资源目录不满足要求。
初态首次红测包含 3 条实际行为失败和 1 条测试 fixture 错误，后者不计为行为差异。
证据另见 `.cache/codex-python/` 下 `shell-snapshot-before.xml`、
`evaluation-state-before*.xml`、`evaluation-cleanup-before-fixed-fixture-20261029.xml`、
`runtime-home-before-20261029.xml`。Linux helper guard 的旧 wheel 红测留在 `linux/before/`。
Docker 的时区差异和进程回收条件留在 `docker/timezone-before/`；
`timezone-before-20261029.xml` 另记录一条跨日时日期/时区联合 fallback 的旧实现失败，
不把新增 16 项绿测都称为旧实现失败。

Linux 主机的全局 `/etc/profile.d` 含 Bash 专用语法，不能由 `/bin/sh` 登录加载。
纯进程生命周期单测因此显式关闭 login，继承/cwd/清理用例使用实际 Bash login；
sh 脚本内容测试隔离宿主 profile。真实 Bash/Zsh startup 与 7 项原生完整请求对照保留，
没有为了通过测试修改生产 shell 行为。
Docker 首次运行另确证孤儿 `sleep` 已退出但处于 `Z` 状态、PPid 为不回收它的 PID 1；
最终容器使用 `--init`，单独复验确认回收。这是明确的容器运行条件，不能据此推断任意 PID 1 都有同样行为。

两端安装验收各覆盖 48 项文件任务/工具/PTY/Code Mode/进程/候选与容器入口，
以及 72 项评估初态、shell snapshot、运行 home 与时区回归。
每端均核验 site-packages 中 235 个 `flashrsi/` 文件与同一最终 wheel 逐字节一致。
使用真实 Linux x86_64 / 5.10.25 内核、Python 3.12.14、Node 16.14.0。
Docker 以非 root 用户运行，使用只读根目录、无外部网络、`--rm`、`--init`（tini 0.19.0），
只挂载本任务资源。其固定镜像 ID 为：

```text
sha256:0a15c19cc78685f8d322945e882ba702ef3d0265d1f621ee00991b8e64ddb750
```

镜像来自本机已有的 Ubuntu 24.04.3 环境，未修改镜像，Python/Node/shell 运行依赖作为
任务夹具挂载。环境和 launcher 留在 `docker/container-environment.json`、
`docker/linux_container.py`。Linux/Docker 只安装 Codex 运行依赖、pytest 和固定原生 oracle，
不代表其他 harness 或数据集依赖已安装，也不代表完整 benchmark 运行已验收。

## 冻结产物

wheel：`.cache/codex-python/stage1-20261029/dist/flashrsi_lite-0.1.0-py3-none-any.whl`，
**810,819 bytes**，SHA-256：

```text
8e3a043ba08f158a0db5c6264a25fcff8b456284ef3de96eef2709d375dcbb98
```

逐文件核验 **145 个核心/适配资源文件**的内容及执行位与冻结源码一致；
wheel 不含 Codex Rust runtime、bridge 或字节码缓存。
macOS 独立安装环境为 Python 3.12.13 / macOS 26.5.2 arm64，
从源码目录外用 `python -I` 运行，没有安装 `codex_cli_bin`。
验收覆盖候选源码 save/load、rollout、update、恢复基线和坏候选失败，
以及实际工具、Code Mode/Lite、上下文 rollover、在线 memory 和评估隔离。

核心为 **24 个 Python 模块、12,909 行**，另有 **180 行 JS worker**。
统计包含注释和空行，不包含固定适配器、测试和提示词/schema/其他资源；
行数用于说明维护规模，不作为保真或精简程度的验收标准。
最终来源与安装核验记录在 `frozen.json`、`wheel-inventory.json` 和 `verification.json`。
`mvp_doc.md` 保持未修改。

## 剩余边界与下一批

本批次不补全共享 rollout budget、持久 rollout/state DB、跨进程恢复、
rollback/旧压缩重放或自动 memory extraction/consolidation。
后续先迁移父子代理共享预算，再迁移持久会话，最后接自动 memory writer，
沿用原生默认值及触发/跳过条件。显式 memory 笔记不能替代自动 writer。

Linux/Windows 受限 sandbox、execpolicy、自定义权限 profile、Windows shell/PTY、
zsh fork、剩余多模态转换、WebSocket、账号恢复及远程 MCP/apps 等仍有未覆盖路径。
固定上游中其他默认开启但尚未逐项验收的 feature 见 [任务机制清单](codex-task-mechanisms.md)，
不将它们统称为前端包装。
Linux/Docker `danger-full-access` 工具验收不能证明受限沙箱或完整 Terminal-Bench 已通过。

没有运行真实模型自主解题或 benchmark 成功率对照，因此没有证据声明 Python 与原生
在任意任务上的效果相同。要评估任务效果，仍需同模型、同预算、同初态的重复任务实验，
另行报告逐题成功率、耗时与成本。演化后代允许改变基线行为，继续受框架契约、
候选执行隔离和任务质量检查约束。
