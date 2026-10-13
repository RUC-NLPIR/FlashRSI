# darwinx + claude_code + appworld

Test成功率：61.31% → 70.83%（103/168 → 119/168）。

- `full-run.tar.gz`：完整运行目录，含配置、候选Snapshot、Worker记录、逐题轨迹、请求缓存、任务工作记录、日志和固定数据划分。直接依赖的历史搜索、恢复或重新选优记录保存在 `history/`；支持源码与环境说明也一并保留。
- `initial-snapshot.json`、`selected-snapshot.json`：初始和最终实际选中版本，均已验证内容身份。
- `result.json`：原实验结果与既有标记。
- `file-manifest.json`：归档内逐文件大小、SHA-256和凭据脱敏记录。
- `verification.json`：归档SHA-256、逐文件校验、test分数重算、题目顺序和Snapshot核验。

远端运行目录：`/root/blockdata/FlashRSI-AppWorld/runs/darwinx-claude_code-appworld-gate10-20261008-124620-351153`。
归档：756.76 MiB，33969个文件。

凭据已脱敏；依赖环境与Docker镜像未打包。支持源码反映归档时状态，实际候选以Snapshot为准。已有有效性、隔离和审查标记原样保留；归档不会改变实验有效性。仅保存本地，未修改服务器实验、未重新调用模型、未上传GitHub。

初始/最终168题的reward均核对官方AppWorldGrade记录；56组scenario成功率也已重算。

用户确认：本组合最终进化后的 harness 使用候选9。最终 Snapshot ID：`b13abd552e81f2772a69463830804db124e33b3a4b99c5dd2337b02e6a55a0c8`。

`final-harness/` 是从最终 Snapshot 导出的完整原生 harness 文件，逐文件字节哈希已核验；`final-harness-manifest.json` 保留组件与可执行属性。`final-harness-selection.json` 是后续复用和迁移的最终版本指针。

本次是已完成搜索后的10% dev gate补测：允许最多6题回退、相对父版本净增为正；候选9 dev为52/57（91.23%），最终test为119/168（70.83%）。原5% gate结果与全部历史记录保留在归档history下；本次不覆盖历史结果，沿用的搜索、dev和初始test均已核验，只有新候选test新增模型调用。
