# MetaHarness + claude_code + Terminal-Bench

Test：63.33% → 70.00%。初始、最终各30题；按 train 选优，未评估 dev，test 不参与选优。初始版本加5个候选，6个 Snapshot 均已验证内容身份。

`full-run.tar.gz` 保存本次完整实验的配置、全部 Snapshot、Worker 与评测轨迹、逐题记录、请求缓存、评分与隔离审查、日志、失败及恢复证据，并附支持源码、冻结任务划分和镜像身份。凭据已脱敏。

`initial-snapshot.json`、`selected-snapshot.json` 及 `initial-harness/`、`final-harness/` 可用于迁移；文件内容已逐字节核对，可执行权限见相应 manifest。`sealed-train-selection.json` 保留原始选优依据。

`file-manifest.json` 与 `verification.json` 记录逐文件校验、完整包 SHA-256、初始/最终各30题成绩重算及题目顺序检查。本归档保留既有评分和恢复标记，不代表另做一次结果有效性审计。

仅排除清单明确列出的可重新安装的公共依赖缓存、Python runtime 和 uv 二进制；相关诊断和恢复记录保留，Docker 镜像不打包。未保存其他被替代实验，未调用模型、修改远端实验或上传 GitHub。

远端：`/root/blockdata/FlashRSI-TerminalQA/runs/meta_harness-claude_code-terminalbench-20261010-150123-908227`。

大小：1137.99 MiB；文件数：3226。
SHA-256：`0d6d51ee9c7a0449c09eb4b06082a817ae73da3d202d4550b9ece9d0dffbf5b5`。
