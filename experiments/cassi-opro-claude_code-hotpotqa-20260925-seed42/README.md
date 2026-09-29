# opro / claude_code / HotpotQA — seed 42

状态 finished。固定 train/dev/test=150/300/300、seed 42，fullwiki supplied-context 版本；主指标答案 exact_match，另报 F1，不报告 supporting-fact/joint 指标。不同算法保持原生优化对象和选择规则。test 只在选优结束后评测，未参与选择。当前版本的数据清单已冻结供所有方法和 harness 复用。

|测试指标|初始|最终|
|---|---:|---:|
|EM|50.0000%|52.3333%|
|F1|67.0428%|67.6307%|

[中间优化过程](process.md)、[完整决策](decisions.json)、[版本索引](versions/index.json)。模型和超参见 configs，结果和用量见 summaries。logs.tar.gz 保存原始持久化记录（不删除失败），manifest.json 记录文件数/体积/SHA256；Git LFS 管理压缩包。逐题复算和同一 300 个 ID/顺序核验见 run/evidence/submission-verification.json。源码和环境证据见 run/evidence。打包 commit 不等于历史执行版本。

目标 deepseek-flash、32768 token/600s、高推理、并发4；Worker deepseek-v4-pro、65536 token/900s；完整配置为准。SkillOpt 使用已有有界补丁恢复与 Worker 并发机制，OPRO 为串行候选生成。保留所有失败/重试并区分执行错误与低分。SDK unknown 费用不代表供应商账单。smoke/独立核验用量不包含在正式汇总内。凭据经过打包扫描；原始路径、端点及数据内容保留。本阶段只下载本地，不自动提交或推送。

## All candidate training scores

|Candidate|Round|Train EM|
|---|---|---|
|0|0|82.6667%|
|1|1|85.3333%|
|2|1|80.0000%|
|3|1|82.0000%|
|4|1|78.0000%|
|5|2|86.0000%|
|6|2|86.6667%|
|7|2|86.6667%|
|8|2|84.6667%|
|9|3|87.3333%|
|10|3|85.3333%|
|11|3|86.0000%|
|12|3|86.6667%|
|13|4|84.6667%|
|14|4|86.0000%|
|15|4|84.6667%|
|16|4|86.6667%|
|17|5|86.6667%|
|18|5|83.3333%|
|19|5|86.6667%|
|20|5|86.0000%|

Full instructions and snapshot IDs: [candidate-history.json](candidate-history.json). Selection uses training EM only; ties retain earlier instructions.

## Execution and limitations

This is an OPRO HotpotQA/harness adaptation using5 rounds x4 candidates, not the paper default budget. All20 candidates and the initial instruction are exported. Executed at commitfb4d513 with ordinary runner fingerprint unchanged from the prepared86d115e plan; the new MiniAgent recovery script was not used by this Claude Code experiment. The prepared rank-recovery evidence reflects pre-run preparation migration, not a failure of this run.

Target32768tokens/600s/10turns and Worker65536tokens/900s remained unchanged. One target attempt reached10turns and another timed out at600s; both recovered using the existing retry budget. Matching successful cache keys were verified; both failed records and usage remain archived.

Test EM150/300 to157/300 (+2.33pp),16 improved and9 regressed; paired bootstrap95% interval -1.00 to+5.67pp. F1 increased from67.04% to67.63%. The interval includes zero; this single-seed run does not establish reliable improvement.
