# 协作实验提交

## 已整理的实验

- [SkillOpt / SearchQA · DeepSeek · 2026-09-20 · seed 42](skillopt-searchqa-deepseek-20260920-seed42/README.md)：约 5.1 MiB 的精简记录，包含结果图、完整候选决策、逐题测试答案、技能版本及失败恢复记录。可直接提交普通 Git，不需要 LFS。

该精简版省略完整消息历史和重复缓存，不能直接用来续跑。完整原始文件已在仓库外无损归档；备份校验信息及精简范围见该目录的 `manifest.json` 和 `README.md`。

## cassi 完整实验归档 · 2026-09-25 · seed 42

以下六份提交保留原始配置、结果、失败与恢复记录以及完整日志。归档哈希、大小和文件数见各目录的 `manifest.json`；日志通过 Git LFS 下载。

| 算法 | Agent | Benchmark | 实验记录 |
| --- | --- | --- | --- |
| OPRO | MiniAgent | SearchQA | [配置、结果与日志](cassi-opro-miniagent-searchqa-20260925-seed42/README.md) |
| OPRO | Claude Code | SearchQA | [配置、结果与日志](cassi-opro-claudecode-searchqa-20260925-seed42/README.md) |
| SkillOpt | MiniAgent | HotpotQA | [配置、结果与日志](cassi-skillopt-miniagent-hotpotqa-20260925-seed42/README.md) |
| SkillOpt | Claude Code | HotpotQA | [配置、结果与日志](cassi-skillopt-claude_code-hotpotqa-20260925-seed42/README.md) |
| OPRO | MiniAgent | HotpotQA | [配置、结果与日志](cassi-opro-miniagent-hotpotqa-20260925-seed42/README.md) |
| OPRO | Claude Code | HotpotQA | [配置、结果与日志](cassi-opro-claude_code-hotpotqa-20260925-seed42/README.md) |

SearchQA 使用 400/200/1400、HotpotQA 使用 150/300/300 的 train/dev/test 划分。各运行的模型、选择规则和预算恢复存在差异，以归档配置和说明为准；这些记录不代表严格等预算对照。`manifest.json` 中的打包 commit 不等同于执行 commit。

## 完整归档提交

实验执行时继续写到本地 `runs/`，该目录不直接提交。需要分享完整原始记录时，用框架的打包脚本导出到
`experiments/<唯一 run-id>/`，所有协作者使用相同的提交结构：

```text
experiments/<contributor>-<experiment>-<date>-<seed>/
  README.md          实验提交说明
  manifest.json      提交者、打包版本、完整日志 SHA256、体积及文件数
  configs/           已保存的实验配置、数据划分清单（存在时）
  summaries/         成绩、token、缓存与费用汇总
  logs.tar.gz        完整持久化日志，包括失败、重试、轨迹及技能快照
```

`logs.tar.gz` 由 Git LFS 管理，其余小文件直接提交普通 Git。仓库的 `.gitattributes`
已设置规则；每位协作者需要先安装 Git LFS，并在克隆仓库后执行 `git lfs install`。
远端仓库也必须支持 Git LFS，并有足够的存储额度。不要在没有 Git LFS 的环境中直接添加压缩包。

## 操作步骤

1. 使用团队指定的框架 commit；实验代码先提交，避免结果无法对应代码版本。记录模型、配置、随机种子，
   每个独立实验使用不同输出目录，不能覆盖已有结果。`manifest.json` 的 commit 是**打包时**版本；
   真正执行配置和原有源码指纹仍保留在日志中，不应把打包 commit 当作历史运行版本。
2. 等实验结束、自动生成 `end-summary.md/json` 后打包。普通 runner 传入该次运行目录；
   SearchQA 专用 runner 传入 `full`/`pilot`/`smoke` profile 目录，可包含两种 harness。
3. 检查配置、汇总和原始日志中的可公开内容，提交本人唯一 run-id 对应的目录。修正实验应使用新 ID，
   不覆盖别人的目录，不删除失败记录只保留高分结果。

```bash
# 一次性配置；此命令要求已安装 Git LFS。
git lfs install

# 示例：从现有 SearchQA 双 harness 结果生成统一提交包。
.venv/bin/python scripts/prepare_experiment_submission.py \
  --run-dir runs/skillopt-searchqa-deepseek/full \
  --run-id alice-skillopt-searchqa-deepseek-20260920-seed42 \
  --contributor alice

# 第一次引入此规范时，将框架脚本、文档和 .gitattributes 单独提交。
# 后续实验各自只添加唯一目录，避免 git add . 混入无关改动。
git add experiments/alice-skillopt-searchqa-deepseek-20260920-seed42
git lfs status
git diff --cached --stat
git commit -m "experiment: alice SearchQA DeepSeek seed42"
```

协作者先拉取共同框架版本，再各自在分支提交实验目录，通过团队的合并流程汇总。
不要求所有人编辑共享的结果表，避免冲突；各目录里的 JSON 可用于后续自动汇总。

## 保存范围

打包不会运行模型、修改原始日志、提交或推送。保留持久化的完整实验目录（包括核验和进程日志），
排除 `working/`、锁文件、临时文件、Python 缓存及 `.env*`。失败实验有 `error.json` 也可打包，
标记为 running 的实验须先停止并确认状态。

工具会检查本机已知凭据及常见 `sk-` token（含 Snapshot 的 base64 内容），发现后拒绝打包；
这不是所有敏感信息的完整检测。它不改写原始 prompt、路径、服务地址，公开提交前需检查。
日志中原有绝对路径是历史引用；解包后不会自动成为可直接续跑的配置。

```bash
# 获取完整归档后解包；只拿到 LFS 指针文件时需先 git lfs pull。
mkdir -p /tmp/inspect-run
tar -xzf experiments/alice-skillopt-searchqa-deepseek-20260920-seed42/logs.tar.gz -C /tmp/inspect-run
```

目前原始运行目录仍有两种内部格式，统一的是上面的提交包格式；无需为提交改写已有实验轨迹。


## 2026-10-05 补充归档

- [cassi-ace-claude_code-hotpotqa-20261004-seed42](cassi-ace-claude_code-hotpotqa-20261004-seed42/README.md)
- [cassi-ace-claude_code-searchqa-20261001-seed42](cassi-ace-claude_code-searchqa-20261001-seed42/README.md)
- [cassi-ace-miniagent-hotpotqa-20261001-seed42](cassi-ace-miniagent-hotpotqa-20261001-seed42/README.md)
- [cassi-ace-miniagent-searchqa-20260930-seed42](cassi-ace-miniagent-searchqa-20260930-seed42/README.md)
- [cassi-ahe-claude_code-tau3_banking-20261004-seed42](cassi-ahe-claude_code-tau3_banking-20261004-seed42/README.md)
- [cassi-ahe-claude_code-terminalbench-20261005-seed42](cassi-ahe-claude_code-terminalbench-20261005-seed42/README.md)
- [cassi-ahe-miniagent-tau3_banking-20261004-seed42](cassi-ahe-miniagent-tau3_banking-20261004-seed42/README.md)
- [cassi-ahe-miniagent-terminalbench-20261004-seed42](cassi-ahe-miniagent-terminalbench-20261004-seed42/README.md)
- [cassi-evoprompt-claude_code-searchqa-20260930-seed42](cassi-evoprompt-claude_code-searchqa-20260930-seed42/README.md)
- [cassi-evoprompt-de-claude_code-hotpotqa-20261001-seed42](cassi-evoprompt-de-claude_code-hotpotqa-20261001-seed42/README.md)
- [cassi-evoprompt-de-miniagent-hotpotqa-20261001-seed42](cassi-evoprompt-de-miniagent-hotpotqa-20261001-seed42/README.md)
- [cassi-evoprompt-miniagent-searchqa-20260930-seed42](cassi-evoprompt-miniagent-searchqa-20260930-seed42/README.md)
- [cassi-gepa-claude_code-hotpotqa-20261003-seed42](cassi-gepa-claude_code-hotpotqa-20261003-seed42/README.md)
- [cassi-gepa-claude_code-searchqa-20261003-seed42](cassi-gepa-claude_code-searchqa-20261003-seed42/README.md)
- [cassi-gepa-miniagent-hotpotqa-20261003-seed42](cassi-gepa-miniagent-hotpotqa-20261003-seed42/README.md)
- [cassi-gepa-miniagent-searchqa-20261003-seed42](cassi-gepa-miniagent-searchqa-20261003-seed42/README.md)
- [cassi-skillopt-claude_code-tau3_banking-20261004-seed42](cassi-skillopt-claude_code-tau3_banking-20261004-seed42/README.md)
- [cassi-skillopt-claude_code-terminalbench-20261004-seed42](cassi-skillopt-claude_code-terminalbench-20261004-seed42/README.md)
- [cassi-skillopt-miniagent-tau3_banking-20261002-seed42](cassi-skillopt-miniagent-tau3_banking-20261002-seed42/README.md)
- [cassi-skillopt-miniagent-terminalbench-20261001-seed42](cassi-skillopt-miniagent-terminalbench-20261001-seed42/README.md)


## 2026-10-08 补充归档（25组）

- [cassi-ace-claude_code-terminalbench-20261008-seed42](cassi-ace-claude_code-terminalbench-20261008-seed42/README.md)
- [cassi-ace-miniagent-terminalbench-20261008-seed42](cassi-ace-miniagent-terminalbench-20261008-seed42/README.md)
- [cassi-adas-claude_code-hotpotqa-20261007-seed42](cassi-adas-claude_code-hotpotqa-20261007-seed42/README.md)
- [cassi-adas-claude_code-searchqa-20261007-seed42](cassi-adas-claude_code-searchqa-20261007-seed42/README.md)
- [cassi-adas-miniagent-appworld-20261008-seed42](cassi-adas-miniagent-appworld-20261008-seed42/README.md)
- [cassi-adas-miniagent-hotpotqa-20261007-seed42](cassi-adas-miniagent-hotpotqa-20261007-seed42/README.md)
- [cassi-adas-miniagent-searchqa-20261007-seed42](cassi-adas-miniagent-searchqa-20261007-seed42/README.md)
- [cassi-ahe-miniagent-appworld-20261008-seed42](cassi-ahe-miniagent-appworld-20261008-seed42/README.md)
- [cassi-darwinx-claude_code-hotpotqa-20261007-seed42](cassi-darwinx-claude_code-hotpotqa-20261007-seed42/README.md)
- [cassi-darwinx-claude_code-searchqa-20261007-seed42](cassi-darwinx-claude_code-searchqa-20261007-seed42/README.md)
- [cassi-darwinx-miniagent-appworld-20261008-seed42](cassi-darwinx-miniagent-appworld-20261008-seed42/README.md)
- [cassi-darwinx-miniagent-hotpotqa-20261007-seed42](cassi-darwinx-miniagent-hotpotqa-20261007-seed42/README.md)
- [cassi-darwinx-miniagent-searchqa-20261007-seed42](cassi-darwinx-miniagent-searchqa-20261007-seed42/README.md)
- [cassi-darwinx-miniagent-terminalbench-20261008-seed42](cassi-darwinx-miniagent-terminalbench-20261008-seed42/README.md)
- [cassi-gepa-claude_code-terminalbench-20261005-seed42](cassi-gepa-claude_code-terminalbench-20261005-seed42/README.md)
- [cassi-gepa-miniagent-terminalbench-20261005-seed42](cassi-gepa-miniagent-terminalbench-20261005-seed42/README.md)
- [cassi-meta_harness-claude_code-hotpotqa-20261007-seed42](cassi-meta_harness-claude_code-hotpotqa-20261007-seed42/README.md)
- [cassi-meta_harness-claude_code-searchqa-20261007-seed42](cassi-meta_harness-claude_code-searchqa-20261007-seed42/README.md)
- [cassi-meta_harness-miniagent-hotpotqa-20261007-seed42](cassi-meta_harness-miniagent-hotpotqa-20261007-seed42/README.md)
- [cassi-meta_harness-miniagent-searchqa-20261007-seed42](cassi-meta_harness-miniagent-searchqa-20261007-seed42/README.md)
- [cassi-modular_rsi-claude_code-hotpotqa-20261007-seed42](cassi-modular_rsi-claude_code-hotpotqa-20261007-seed42/README.md)
- [cassi-modular_rsi-claude_code-searchqa-20261007-seed42](cassi-modular_rsi-claude_code-searchqa-20261007-seed42/README.md)
- [cassi-modular_rsi-miniagent-hotpotqa-selected-20261007-seed42](cassi-modular_rsi-miniagent-hotpotqa-selected-20261007-seed42/README.md)
- [cassi-modular_rsi-miniagent-searchqa-20261007-seed42](cassi-modular_rsi-miniagent-searchqa-20261007-seed42/README.md)
- [cassi-opro-miniagent-appworld-20261008-seed42](cassi-opro-miniagent-appworld-20261008-seed42/README.md)


## 2026-10-18 DarwinX Terminal 后续组替换

- [DarwinX + Claude Code + Terminal-Bench：后续独立重跑](cassi-darwinx-claude_code-terminalbench-20261015-020453-223515-rerun31556/README.md)：替换原 `cassi-darwinx-claude_code-terminalbench-20261009-seed42`，本次实测及用户采用的统计口径为 19/30 → 19/30（63.33% → 63.33%）。最终一题超时按用户明确决定计失败；原官方异常、未评分记录和事后协议修订一并保留。完整恢复链、原生轨迹、候选与费用证据通过 Git LFS 分卷保存。
