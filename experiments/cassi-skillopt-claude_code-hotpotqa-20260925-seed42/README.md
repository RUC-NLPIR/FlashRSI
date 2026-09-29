# skillopt / claude_code / HotpotQA — seed 42

状态 finished。固定 train/dev/test=150/300/300、seed 42，fullwiki supplied-context 版本；主指标答案 exact_match，另报 F1，不报告 supporting-fact/joint 指标。不同算法保持原生优化对象和选择规则。test 只在选优结束后评测，未参与选择。当前版本的数据清单已冻结供所有方法和 harness 复用。

|测试指标|初始|最终|
|---|---:|---:|
|EM|50.3333%|51.0000%|
|F1|67.1994%|64.7106%|

[中间优化过程](process.md)、[完整决策](decisions.json)、[版本索引](versions/index.json)。模型和超参见 configs，结果和用量见 summaries。logs.tar.gz 保存原始持久化记录（不删除失败），manifest.json 记录文件数/体积/SHA256；Git LFS 管理压缩包。逐题复算和同一 300 个 ID/顺序核验见 run/evidence/submission-verification.json。源码和环境证据见 run/evidence。打包 commit 不等于历史执行版本。

目标 deepseek-flash、32768 token/600s、高推理、并发4；Worker deepseek-v4-pro、65536 token/900s；完整配置为准。SkillOpt 使用已有有界补丁恢复与 Worker 并发机制，OPRO 为串行候选生成。保留所有失败/重试并区分执行错误与低分。SDK unknown 费用不代表供应商账单。smoke/独立核验用量不包含在正式汇总内。凭据经过打包扫描；原始路径、端点及数据内容保留。本阶段只下载本地，不自动提交或推送。


## Execution and rejected updates

Executed at commit 86d115e with unchanged frozen 150/300/300 seed42 data and prepared budgets. The prepared plan was migrated from 39ff52b before this run started; the rank-recovery evidence refers to that preparation migration, not an interruption of this Claude Code run.

All 16 fast steps and three slow decisions are retained; two fast candidates were accepted. Fast step14 was rejected because the edit target did not occur exactly once, and the epoch3 slow update was rejected because guidance did not identify an existing text path with string content. These are invalid_patch rejections, not scored candidates. One target attempt reached max_turns=10; an existing bounded retry succeeded under the same budget, with matching successful cache key verified. The failed trajectory and usage remain archived. No Worker protocol retries were recorded.

Test EM: 151/300 to 153/300 (+0.67 percentage points); 21 improved, 19 regressed, paired bootstrap 95% interval -3.33 to +4.67 points. F1 decreased from 67.20% to 64.71%. This single run does not establish a reliable test improvement. Full optimization history, raw Worker responses, scores and snapshots are preserved.
