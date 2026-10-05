# AHE + Claude Code + Terminal-Bench

官方 DeepSeek API：Flash target、Pro worker、Flash 答案访问审核。Target 和 worker 均为 Claude Code。AHE 外层迭代 2 次，target 并发 10，诊断 worker 并发 8，汇总与编辑串行。冻结 train/dev/test 为 20/15/30，seed 42；仅按 dev 选版本，test 不参与选择。

## 实验结果

| 评估 | 成功题数 | 成功率 |
| --- | ---: | ---: |
| 初始 test | 21/30 | 70.00% |
| 最终 test | 21/30 | 70.00% |

变化：0.00 个百分点。最终选择初始 harness，最终 test 复用初始 test 的完整逐题评估，非第二次独立测量；记录 independent_final_test=false。全部 30 题计入分母，7 题原生预算耗尽计 0 分。初始 test 的 21 条成功记录均经过答案访问审核，未发现确认违规；Snapshot 和题目 ID 已复核。

Dev：初始 12/15（80%），两个候选均为 9/15（60%），因此保留初始版本。训练初始为 13/20（65%），两个候选为 14/20（70%）和 12/20（60%）。

北京时间 2026-10-04 22:39:44 开始，2026-10-05 07:46:03 完成，约 9 小时 6 分钟。

## 归档内容

logs.tar.gz 保存完整实验目录、全部候选与初始 snapshots、逐题轨迹、缓存、审核、预算与 infra 重试证据、配置、选择记录、源码、冻结任务与镜像身份。result.json 为统一成绩汇总；final-test-reuse.json 在包内记录复用来源及 SHA256。既有独立重复测试的轨迹仅作为过程证据保留在 recovery/test-reuse-policy-20261005/，不参与上述成绩。

verification.json 和 file-manifest.json 保存逐文件哈希、从完整轨迹重算的 test reward 和测试题目顺序核对。凭据脱敏。本次复核、汇总和归档没有新增模型调用；不修改已记录的历史实际用量。

归档校验通过：压缩包773.44 MiB，2916个文件逐一通过SHA-256校验；初始与最终test均从完整逐题记录重算为21/30，题目顺序一致。
