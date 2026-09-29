# opro / miniagent / HotpotQA — seed 42

状态 finished。固定 train/dev/test=150/300/300、seed 42，fullwiki supplied-context 版本；主指标答案 exact_match，另报 F1，不报告 supporting-fact/joint 指标。不同算法保持原生优化对象和选择规则。test 只在选优结束后评测，未参与选择。当前版本的数据清单已冻结供所有方法和 harness 复用。

|测试指标|初始|最终|
|---|---:|---:|
|EM|51.0000%|52.0000%|
|F1|67.9048%|66.8440%|

[中间优化过程](process.md)、[完整决策](decisions.json)、[版本索引](versions/index.json)。模型和超参见 configs，结果和用量见 summaries。logs.tar.gz 保存原始持久化记录（不删除失败），manifest.json 记录文件数/体积/SHA256；Git LFS 管理压缩包。逐题复算和同一 300 个 ID/顺序核验见 run/evidence/submission-verification.json。源码和环境证据见 run/evidence。打包 commit 不等于历史执行版本。

目标 deepseek-flash、32768 token/600s、高推理、并发4；Worker deepseek-v4-pro、65536 token/900s；完整配置为准。SkillOpt 使用已有有界补丁恢复与 Worker 并发机制，OPRO 为串行候选生成。保留所有失败/重试并区分执行错误与低分。SDK unknown 费用不代表供应商账单。smoke/独立核验用量不包含在正式汇总内。凭据经过打包扫描；原始路径、端点及数据内容保留。本阶段只下载本地，不自动提交或推送。

## All candidate training scores

|Candidate|Round|Train EM|
|---|---|---|
|0|0|83.3333%|
|1|1|86.0000%|
|2|1|84.6667%|
|3|1|86.0000%|
|4|1|85.3333%|
|5|2|88.0000%|
|6|2|86.6667%|
|7|2|85.3333%|
|8|2|86.6667%|
|9|3|84.6667%|
|10|3|86.6667%|
|11|3|87.3333%|
|12|3|84.6667%|
|13|4|86.6667%|
|14|4|87.3333%|
|15|4|83.3333%|
|16|4|85.3333%|
|17|5|87.3333%|
|18|5|86.0000%|
|19|5|86.0000%|
|20|5|86.6667%|

Full instruction text and snapshot IDs: [candidate-history.json](candidate-history.json). Selection uses training EM only; ties retain the earlier instruction.

## Budget and recovery disclosure

This is an OPRO adaptation to HotpotQA and agent harnesses, with a reduced 5-round x4-candidate search budget, not a strict reproduction of the paper's default budget. Frozen150/300/300 seed42 data and all20 candidate evaluations were retained.

The run started at commit86d115e and stopped during initial-test after the same task twice exhausted32768 tokens. User authorized token escalation. Commitfb4d513 adds length-only recovery at65536 tokens/900s, at most two persistent extra attempts per logical task. All3401 pre-recovery cache records were SHA256-verified unchanged before audited fingerprint migration. Five logical requests ultimately recovered, each using one64k attempt. Six failed attempts are retained, including the initial two32k failures; reasoning stayed high. Successful original calls were reused. Baseline config remains32k/600s; actual recovery configurations are in ResponseRecovery/RunConfig messages. Do not describe this run as using32k uniformly.

Historical interruption, old summaries, source archives and migration evidence are preserved in logs.tar.gz. Test EM153/300 to156/300 (+1pp),17 improved and14 regressed; paired bootstrap95% interval -2.67 to+4.67pp. F1 decreased. This single run does not establish a reliable improvement.
