# ace + miniagent + terminalbench

Test成功率：66.67% → 70.00%（20/30 → 21/30）。

- `logs.tar.gz`：完整运行目录，含配置、候选Snapshot、Worker记录、逐题轨迹、请求缓存、任务工作记录、日志和固定数据划分。直接依赖的历史搜索、恢复或重新选优记录保存在 `history/`；支持源码与环境说明也一并保留。
- `initial-snapshot.json`、`selected-snapshot.json`：初始和最终实际选中版本，均已验证内容身份。
- `result.json`：原实验结果与既有标记。
- `file-manifest.json`：归档内逐文件大小、SHA-256和凭据脱敏记录。
- `verification.json`：归档SHA-256、逐文件校验、test分数重算、题目顺序和Snapshot核验。

远端运行目录：`/root/data/FlashRSI-TerminalQA/runs/ace-miniagent-terminalbench-final-playbook-20261007-215421-617175`。
归档：66.49 MiB，2978个文件。

凭据已脱敏；依赖环境与Docker镜像未打包。支持源码反映归档时状态，实际候选以Snapshot为准。已有有效性、隔离和审查标记原样保留；归档不会改变实验有效性。原始归档未修改服务器实验、未重新调用模型；本目录以Git LFS保存完整日志。
