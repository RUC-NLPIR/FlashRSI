# DarwinX + Claude Code + Terminal-Bench 后续独立重跑

本组替换 `cassi-darwinx-claude_code-terminalbench-20261009-seed42`。本次实测 initial test **19/30（63.33%）**，用户确认的 final test 统计口径为 **19/30（63.33%）**；共同 baseline 展示值没有替代本次实测。

最终 `filter-js-from-html` 的原官方记录是 VerifierTimeout、没有 reward。原镜像零模型复现证明生成程序在公开测试输入上死循环，用户明确同意该题统计为失败 0；这是仅适用于这一题的事后统计协议修订。`result.json` 保存采用后的统计与授权；`original-official-result.json` 保留 29 题官方/先前协议评分、19 成功和一题未评分的原结论，均未篡改原轨迹、官方异常或 reward。

选中候选 1：`c8cd3b34a1711cd618836f3d50a44388304e52185873b4885bd8e257f34ebd9f`，选优在最终 test 前冻结，test 未参与选优。初始版本：`524d5ada19ad79e7db416570fe192a21f429050c3320e29fe4ced9e4d6253b0b`。原 train/dev/test、5 步搜索、10 次成功 Worker、候选、对话、逐题轨迹、缓存、恢复链、失败与部分调用费用证据均随完整日志保存。Target 并发按此前授权为 4、Worker 为 1。

恢复中的 Caffe CPU 可见性修复、离线依赖、获授权的原会话原题重发及历史 dev 评分超时审查均保留；未声称环境逐字节一致或全容器无损恢复。未知 token/USD 不填 0，可能重叠的原生 session 用量不盲目相加。`publication-evidence/` 含历史归档核验、统计修订和费用审计，原始文件未删除。

- `initial-snapshot.json` / `selected-snapshot.json`：实际版本；`final-harness/` 与选中 Snapshot 文件逐字节一致。
- `full-run.tar.gz.part*`：Git LFS 完整日志分卷，按文件名顺序连接后为一个 tar.gz；`manifest.json` 记录每卷及合并流 SHA-256。
- `file-manifest.json`：发布归档逐文件 SHA-256、原始 SHA-256、凭据脱敏及本地临时文件排除记录；原远端清单中的 9524 个普通文件全部逐文件复核。
- `verification.json`：归档读回、评分重算、任务顺序、Snapshot 和隐私核验。

```bash
cat full-run.tar.gz.part* > full-run.tar.gz
tar -xzf full-run.tar.gz
```

本次只整理上传已保存结果，未新增模型、Worker 或官方评分调用。原本地旧组和后续组均保留；Git 历史保留被替换版本。归档不改变实验有效性或既有协议标记。

重复的完整文件内容在 tar 内用仅指向先前归档成员的安全硬链接存储；解压后仍保留全部原路径。符号链接目标仅在清单中记录，不跟随到归档范围之外。任务生成的自签名测试证书和私钥属于 benchmark 产物，保留在原路径；不是服务器或模型 API 凭据。

`sanitize-git-repo` 原始任务镜像自带的 GitHub token 形状测试字符串已与镜像内输入文件逐字节核对，非运行时凭据；该精确测试值的 SHA-256 和原镜像证据见 `benchmark-fixture-token-review.json`。未探测或使用该测试值。
