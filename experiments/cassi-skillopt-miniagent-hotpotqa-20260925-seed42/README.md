# skillopt / miniagent / HotpotQA — seed 42

状态 finished。固定 train/dev/test=150/300/300、seed 42，fullwiki supplied-context 版本；主指标答案 exact_match，另报 F1，不报告 supporting-fact/joint 指标。不同算法保持原生优化对象和选择规则。test 只在选优结束后评测，未参与选择。当前版本的数据清单已冻结供所有方法和 harness 复用。

|测试指标|初始|最终|
|---|---:|---:|
|EM|53.3333%|52.0000%|
|F1|68.8574%|66.1447%|

[中间优化过程](process.md)、[完整决策](decisions.json)、[版本索引](versions/index.json)。模型和超参见 configs，结果和用量见 summaries。logs.tar.gz 保存原始持久化记录（不删除失败），manifest.json 记录文件数/体积/SHA256；Git LFS 管理压缩包。逐题复算和同一 300 个 ID/顺序核验见 run/evidence/submission-verification.json。源码和环境证据见 run/evidence。打包 commit 不等于历史执行版本。

目标 deepseek-flash、32768 token/600s、高推理、并发4；Worker deepseek-v4-pro、65536 token/900s；完整配置为准。SkillOpt 使用已有有界补丁恢复与 Worker 并发机制，OPRO 为串行候选生成。保留所有失败/重试并区分执行错误与低分。SDK unknown 费用不代表供应商账单。smoke/独立核验用量不包含在正式汇总内。凭据经过打包扫描；原始路径、端点及数据内容保留。本阶段只下载本地，不自动提交或推送。


## Execution interruptions and recovery

Execution started at commit 39ff52b. At fast step 8 the Worker returned indices [0,1,3,5] for five edits (valid 0-4). Commit 86d115e added rank range/budget validation to the existing same-prompt protocol retry policy (at most two retries). All existing cache files were SHA256-verified unchanged before an audited plan-fingerprint migration; the first protocol retry succeeded. Configurations, frozen data and model budgets were unchanged. Historical error.json and the original attempt remain in logs.tar.gz; the final attempt is finished. See run/evidence/rank-recovery.json and rank-recovery-source.tar.gz in the archive.

All 16 fast decisions and three slow decisions are exported. Four fast candidates were accepted. The epoch-2 slow update was rejected as invalid_patch; the other two slow updates did not improve dev. Rejected updates and raw Worker replies remain in the archive. Test EM decreased from 160/300 to 156/300: 17 improved and 21 regressed, paired difference -1.33 percentage points (bootstrap 95% interval -5.33 to +2.67). This run does not establish a test improvement.

Four target attempts exhausted the unchanged 32768-token budget; all four recovered through existing bounded retries, with matching successful cache keys verified. Failed attempt records and usage are preserved.
