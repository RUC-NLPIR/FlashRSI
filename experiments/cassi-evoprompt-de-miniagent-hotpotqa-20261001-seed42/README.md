# cassi-evoprompt-de-miniagent-hotpotqa-20261001-seed42

完整实验归档：`logs.tar.gz`。包含所有尝试、轨迹、快照、配置、缓存、恢复证据、源码和用量记录。原服务器文件未修改。

压缩包及全部 11758 个文件已完成 SHA256 校验；初始和最终测试各 300 题均完成，分数已逐题重算。

测试 exact_match：52.00000000% → 55.00000000%。

详见 `result.json`、`file-manifest.json` 和 `verification.json`。

EvoPrompt-DE：population_size=6，5 generations，donor_random=false；固定 train/dev/test=150/300/300、seed42，test 不参与选择。

测试 F1：67.9760% → 72.3568%。最终测试 1 道题耗尽输出预算，按用户要求 EM/F1 均计 0；原始错误、预算判负证据及恢复入口全部保留。

本地逐题复算全部普通答案的 EM/F1，并核对预算判负标记、冻结任务 ID 和顺序。未修改服务器原始实验记录。
