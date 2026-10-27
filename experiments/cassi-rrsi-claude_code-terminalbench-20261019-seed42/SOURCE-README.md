# RRSI × Claude Code × Terminal Bench

已完成 T=2、seed42、k=2、m=2。初始测试 **22/30（73.33%）**，演化后测试 **23/30（76.67%）**。

- `full-run.tar.gz`：仅本组原实验及恢复链，按内容 SHA 去重的标准 tar.gz。重复文件采用 tar 硬链接，原路径保留。大小 4.836 GiB。
- `initial-snapshot.json` / `selected-snapshot.json`：完整可复用 Snapshot；初始 ID `52d133954850d9f4f4442269c7f47be2e28e9d5c9d2aafbc707777d5972c2c01`，最终 ID `af2f711153587f81712049a34a37047511ccc9ccde77feaab97088557c54e4e6`。
- `initial-harness/` / `selected-harness/`：对应资源的展开副本。复用推荐通过 Snapshot 加载，以保留组件和版本身份。
- `source/`：冻结的 FlashRSI 源码；234 项原源码 SHA 已核实。
- `file-manifest.json.gz`：原文件与包内文件的 SHA、大小、模式、脱敏和去重关系。
- `verification.json`、`ood-snapshot-acceptance.json`、`final-score-verification.json`：本地逐文件验证、真实 Claude Code 绑定零模型验证，以及原 30+30 测试评分重算。
- `remote-cleanup-completed.json`：本地验证成功后的远端定向清理凭据。Mini 的源码、共享评分依赖、原缓存和 CC 完成凭据保留且 SHA 未变。

## OOD 复用

使用 `source/` 中的框架和声明依赖，在新的输出目录中创建 ClaudeCode，`source_dir` 指向 `source/flashrsi/agents/claude_code`，然后 `agent.update(Snapshot.load("selected-snapshot.json"))`。Target 的模型、API 凭据、预算独立提供，使用新的 OOD benchmark/task，勿启动归档中的旧接续脚本。

Snapshot 版本、资源字节、实际新 ClaudeCode 绑定及本地展开都已验证；本次没有运行付费 OOD 测试。Docker 环境、安装好的依赖和新 benchmark 数据需单独准备。原生 status、未知费用和历史失败记录保留；官方评分使用本实验实际采用的 `terminal_verified_reward.py` 映射，不能用旧的“status=error一律0分”移植语义替代。

包内记录包括原生对话、Worker 编辑、候选/选择、完整与未知用量、官方评分和恢复历史。安装环境、Docker 镜像、外部公共依赖缓存及其他实验未打包。历史工作区符号链接保存在 `symlinks.json` 元数据中，未在本地不加选择地展开。


Publication: the full archive is preserved byte-for-byte. When split, concatenate `full-run.tar.gz.part*` in lexical order. Large JSON manifests are losslessly gzip-compressed. Source verification and historical protocol/scoring exceptions remain unchanged. Historical symlinks may refer to original environment paths: this audit reads link metadata without extracting/following it. Use safe extraction filters and do not restore historical links as root. No new model or grader calls.
