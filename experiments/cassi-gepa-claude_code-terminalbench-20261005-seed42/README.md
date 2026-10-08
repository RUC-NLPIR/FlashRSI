# GEPA + Claude Code + Terminal-Bench

Test成功率：63.33% → 66.67%（19/30 → 20/30），提升3.33个百分点。

1 epoch，固定train/dev/test划分20/15/30题。最终选中了新的Snapshot，随后进行独立sealed test评估。

- `logs.tar.gz`：完整配置、候选Snapshot、轨迹、逐题评估、日志、固定任务数据、镜像身份清单和支持源码。
- `selected-snapshot.json`：最终实际选中并用于test的harness内容。
- `result.json`：正式结果。
- `file-manifest.json`：包内文件清单与哈希。
- `verification.json`：逐文件SHA-256核验、test分数重算及初始/最终逐题顺序核验。

源码副本反映归档时的项目状态；候选内容以Snapshot为准。凭据已脱敏；依赖环境和Docker镜像不包含在实验归档中。
