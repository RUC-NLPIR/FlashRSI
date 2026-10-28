# Codex 核心源码的来源与抽取

`flashrsi/agents/codex/runtime/` 保存 Codex **0.147.0** 的 Rust 核心及完整本地依赖闭包。
上游固定为 <https://github.com/openai/codex> 的
`be6e8eac029b183056b7e4402879f15d2c85f61b`，对应固定 tag `rust-v0.147.0`。
抽取前必须验证本地 tag 解析到该 commit。版本号、tag 与 commit 一起记录在
`runtime/UPSTREAM.json`，不随上游分支移动。

抽取从原生 core、配置、协议、arg0 和运行所需的扩展注册入口出发，递归保留所有
平台的普通、构建及开发 path dependencies：92 个生产 crate 和 5 个测试支持 crate，
共 3,463 个上游文件、约 34.2 MB。开发依赖和原测试源码保留，以便后续对照原生测试；
它们不成为 bridge 的生产执行入口。

CLI、`exec`、TUI、app-server 及 app-server-daemon workspace 入口被排除。
`app-server-protocol` 是 core 的实际依赖，因此保留。`exec-server`、sandbox、
MCP、skills、hooks、memory、工具路由和模型连接等 core 依赖同样保留。
code-mode 的 host 和 runtime 也属于执行实现，其源码纳入所选 Snapshot；
发行包 extra 只提供 `rg`、`zsh` 等工具及上游 CLI 对照基线。
抽取不删除 core 内部能力，不将 Rust 逻辑重写成 Python。

## 机械变化与字节一致性

全部 Rust 文件、crate 级 `Cargo.toml`、提示词和编译时资源保持上游字节一致。
初始抽取唯一修改是 workspace 根 `Cargo.toml` 的 `members` 和
`default-members`：成员裁剪为依赖闭包，并预留 `bridge`。
其余依赖版本、features、平台依赖、Rust toolchain 和上游 patch 配置保持原样。
上游根 `LICENSE`、`NOTICE` 和各 crate 内的许可证一并保留。

Cargo 会将同一依赖的 features 按构建上下文联合启用，因此文件字节一致本身不足以
证明裁剪后的编译语义一致。固定 bridge 显式恢复原 CLI 通过产品层间接开启的共享库
features，例如 `serde_json/preserve_order` 和 `image/tiff`，不重新引入产品入口。
[codex-core-features.json](codex-core-features.json) 保存原 CLI 与抽取核心的依赖特性
对照：在所列 macOS host/target 上，14 个包的差异已恢复，保留各个 host/build 与
target 特性配置，未将其混成一个并集。该记录不替代运行测试或其他平台的特性校验。
补齐 model refresh 和 plugin startup 生命周期后，重新对照的 859 个核心共享包及
888 个含 code-mode host 的共享包仍无特性配置差异；外部依赖锁标识没有变化。

构建还必须保留上游 `profile.release`。`dev-small` 继承 `dev`，不只是编译速度与
符号信息不同：`debug_assertions` 会改变首个 WebSocket 重试事件、部分错误的
panic/日志处理、遥测导出及测试专用环境开关；arg0 的 helper 路径检查也不同。
仅关闭 debug assertions 和 overflow checks 仍不能消除依赖构建脚本读取
`PROFILE`、`OPT_LEVEL` 的差异，例如 V8 源码构建的 GN `is_debug` 和 aws-lc 的
C 编译参数。因此适配器直接使用原版 release profile，不重写其配置。
依赖特性对照独立于 profile；该对照没有覆盖运行行为或构建产物的一致性。

`runtime/UPSTREAM.json` 为每个文件记录：

- 原始仓库路径与 Git blob SHA-1；
- 原始文件和落盘文件的 SHA-256；
- 原始可执行位。

workspace 的机械变化记录在 `runtime/upstream-build.patch`。bridge 加入后由 Cargo
生成的 `Cargo.lock` 差异也可通过下面的命令记录到同一 patch，不修改 Rust 文件。
这些记录描述初始来源；算法产生的后代 Snapshot 可以按其 code scope 修改核心源码，
修改后的完整文件内容由 Snapshot 自己的内容哈希标识。

## 固定桥与构建目录

`flashrsi/agents/codex/_bridge/` 是 FlashRSI 的固定输入输出包装，位于 Snapshot 之外。
构建时，适配器将选中的 runtime Snapshot 复制到构建缓存，然后把 `_bridge/` 注入为
该构建副本的 `bridge/`。因此原始 `runtime/` 的 `members` 虽然包含 `bridge`，
其中没有实际的 bridge 目录，也不应直接在原始 runtime 目录构建。

原生 core 处理模型调用、工具执行和线程运行；bridge 选择并构造原生入口，转发输入与事件。
这种进程边界不要求把 Rust 核心翻译为 Python，也允许演化后的 core 在独立构建目录编译。
编译产物、Cargo 缓存、凭据和任务状态不放进 runtime Snapshot。

固定桥同时保留原 exec/app-server 的原生配置、扩展注册和启动/关闭动作，包括
模型目录刷新、plugin analytics、后台 plugin startup 与消费者缓存刷新。
模型刷新循环由固定上游 `app-server/src/models_refresh_worker.rs` 机械搬入桥中，
生产函数体保持一致并标注出处；其余动作调用原生公开方法。
不支持 native login，因而不接入依赖账号登录与 app-server 配置 RPC 的远程插件
自动 hook trust；该边界与框架仅接受角色 `llm.api_key` 的现有运行契约一致。

### code-mode 宿主的已验证构建缓存

核心始终从选中源码编译。code-mode 的独立宿主还允许复用固定官方 tag 的构建产物，
目前只记录了 macOS arm64 的官方发布文件、归档 SHA-256 和可执行文件 SHA-256。
固定 `_companion.json` 位于 Snapshot 外，记录宿主的完整生产 path 依赖闭包和
workspace 配置的逐文件哈希；候选不能通过修改自己的 `UPSTREAM.json` 改写这些基线。

只有该闭包文件集合、内容、可执行位及 workspace/lock/toolchain 配置全部匹配时，
才可以复用该产物。修改无关的核心模块仍能复用未改变的宿主；修改宿主或其依赖、
增加/删除文件、改变构建参数时，必须编译候选源码，失败即返回错误。固定 bridge 和
宿主缓存策略/元数据也参与核心构建指纹，避免接入实现改变后命中旧执行产物。

该分支用于处理上游 `v8=150.4.0` 未发布 sandbox 预编译库的构建限制，未关闭 V8
sandbox。宿主源码构建使用原版 V8；在 macOS 上需要完整 Xcode。构建记录明确区分
`verified-upstream-build-cache` 与 `selected-source-build`，不将官方产物记为本机源码编译。

## 重新抽取与校验

使用 Python 3.11 或更高版本。`--upstream` 指向包含固定 commit 的本地 Git 仓库：

```bash
uv run python scripts/extract_codex_core.py \
  --upstream /path/to/openai-codex
uv run python scripts/extract_codex_core.py --verify
```

脚本读取 Git tree，不切换或修改上游工作树。默认下载固定 commit 的 codeload tarball
到 `.cache/codex-build/`，避免 sparse/partial clone 按文件触发大量网络请求。
下载文件中的每个实际选中 blob 必须与本地固定 Git tree 一致，才会写入 runtime。
可通过 `--archive /path/to/codex-COMMIT.tar.gz` 使用已下载归档；归档本身的
SHA-256 也记录在 manifest。脚本不会直接解压归档路径到文件系统。

`--verify` 检查固定来源标识、初始基线的所有文件哈希和可执行位、额外文件，
以及构建 patch 的哈希，不运行模型或编译器。
需要验证抽取结果时使用它；预期已被算法修改的后代 Snapshot 应使用其自身版本记录。

在构建副本成功解析 bridge 并生成 lockfile 后，维护者可将该 `Cargo.lock` 复制回
初始 runtime，再执行：

```bash
uv run python scripts/extract_codex_core.py --record-build-lock
uv run python scripts/extract_codex_core.py --verify
```

该命令先复核来源标识、除 `Cargo.lock` 内容以外的完整基线及现有 patch，验证失败
不更新来源记录或 patch；然后验证归档 SHA-256 仍与来源 manifest 一致，并检查当前 lockfile 中每个
外部依赖的 `(name, version, source, checksum)` 均来自原始上游锁。
允许裁掉不再引用的包、将所选本地 crate 按其可信 `Cargo.toml` 和 workspace 版本
重新记入锁，以及添加固定 bridge 包。本地包的许可集合从已校验归档重新计算的依赖
闭包导出，并逐个比对其原始 manifest；不按名称前缀或仅凭旧锁条目放行任意 path 包。
不允许变更外部版本、源码引用或校验和，也不允许增加其他包。它还拒绝已经修改的
workspace manifest，并复核其余源文件。
重新执行抽取命令会恢复所选上游文件，包括原始 lockfile。

源码字节校验能证明初始实现来源一致。行为保真还需要 bridge 的配置和扩展注册与
原生入口相匹配，并通过固定模型响应、工具响应及错误路径的对照测试；仅编译成功或
最终答案相同不足以证明所有运行路径完全等价。
