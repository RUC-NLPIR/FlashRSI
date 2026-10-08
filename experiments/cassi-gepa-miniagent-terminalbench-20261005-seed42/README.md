# GEPA + MiniAgent + Terminal-Bench

已完成，2026-10-05 16:31:10（北京时间）。官方 DeepSeek Flash target／Pro反思 worker／Flash审校。

| 指标 | 初始版本 | 最终选中版本 |
| --- | ---: | ---: |
| Dev reward | 66.67%（10/15） | 66.67%（10/15） |
| Test reward | 70.00%（21/30） | 70.00%（21/30） |

1 epoch，target并发10；train/dev/test为20/15/30，seed42。最终依据dev选中初始Snapshot，复用初始test完整记录，`independent_final_test: false`，零新增最终评估调用。test中的两道超时题按0分处理，所有30题进入分母。

`logs.tar.gz`保留完整配置、源码副本、候选决策、Snapshot、逐题轨迹、infra重试及防查答案审校记录，凭据已脱敏。`file-manifest.json`和`verification.json`包含SHA256、文件数及逐题分数复核；`result.json`是结果摘要。此归档尚未上传GitHub。
