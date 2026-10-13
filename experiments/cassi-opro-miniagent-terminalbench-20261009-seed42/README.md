# opro + miniagent + terminalbench

Test成功率：66.67% → 66.67%（20/30 → 20/30）。

- `full-run.tar.gz`：完整运行目录，含配置、候选Snapshot、Worker记录、逐题轨迹、请求缓存、任务工作记录、日志和固定数据划分。支持源码与环境说明也一并保留；用户排除的四个历史完成版本未打包。
- `initial-snapshot.json`、`selected-snapshot.json`：初始和最终实际选中版本，均已验证内容身份。
- `result.json`：原实验结果与既有标记。
- `file-manifest.json`：归档内逐文件大小、SHA-256和凭据脱敏记录。
- `verification.json`：归档SHA-256、逐文件校验、test分数重算、题目顺序和Snapshot核验。

远端运行目录：`/root/data/FlashRSI-TerminalQA/runs/opro-miniagent-terminalbench-20261008-013022-955410`。
归档：134.96 MiB，6067个文件。

凭据已脱敏；依赖环境与Docker镜像未打包。支持源码反映归档时状态，实际候选以Snapshot为准。已有有效性、隔离和审查标记原样保留；归档不会改变实验有效性。仅保存本地，未修改服务器实验、未重新调用模型、未上传GitHub。

Final user-selected run only. Superseded completed experiments are excluded. Existing validity, scoring and protocol annotations are preserved; archiving does not validate results.

最终选中版本的文件已导出至 `final-harness/`，逐文件字节与 `selected-snapshot.json` 一致。用户排除的四个历史完成版本未打包。
