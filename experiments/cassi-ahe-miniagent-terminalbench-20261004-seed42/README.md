# AHE + MiniAgent + Terminal-Bench

官方 DeepSeek API，Flash target、Pro worker。AHE 外层迭代 2 次；target 并发 10，诊断 worker 并发 8；最终选择第一次迭代候选。冻结 train/dev/test 为 20/15/30，seed 42；仅用 dev 选择版本，test 保持 sealed。

## 实验结果

| 评估 | 成功题数 | 成功率 |
| --- | ---: | ---: |
| 初始 test | 22/30 | 73.33% |
| 最终 test | 18/30 | 60.00% |

变化：-13.33 个百分点。两次测试均以全部 30 题为分母，原生 token、轮数或时间预算耗尽计 0 分。确认读取 benchmark 专属答案、参考解法或隐藏测试信息的记录计 0 分；任务本身明确提供的测试文件不因此判零。

## 归档内容

完整归档为 logs.tar.gz，包含评估轨迹、逐题和缓存记录及结果汇总；保留初始与最终 harness、所有候选快照、运行配置、日志、失败与恢复证据、源码和冻结任务记录。result.json 为实验成绩汇总。integrity-audit.json 保存判零原因及命令/返回内容证据。file-manifest.json 和 verification.json 保存文件哈希及逐题重算检查。凭据已脱敏，服务器记录未修改。

归档大小：55.56 MiB；已核验 9362 个文件。
