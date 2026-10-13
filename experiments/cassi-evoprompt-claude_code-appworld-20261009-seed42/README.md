# EvoPrompt + Claude Code + AppWorld

Test成功率：64.88% → 61.90%（109/168 → 104/168）。最终版本由dev选定；独立final test未参与选优。

- `full-run.tar.gz`：完整运行目录，含全部候选Snapshot、Worker记录、逐题轨迹、请求缓存、任务工作记录和日志；另含固定数据划分、支持源码、冻结的私有启动入口及优化器源码。
- `initial-snapshot.json`、`selected-snapshot.json`：初始及最终实际选定Snapshot，内容身份校验通过。
- `final-harness/`：最终选定Snapshot的逐文件原始内容；与Snapshot字节一致。可执行属性另记在`final-harness-manifest.json`，迁移Linux时需按清单恢复。
- `sealed-dev-selection.json`：原始封存选优记录，dev为51/57，test未参与选优。
- `result.json`、`file-manifest.json`、`verification.json`：结果、逐文件SHA-256及大小、脱敏记录、完整归档SHA-256、评分重算和Snapshot核验。

初始Snapshot：`4637fbe95a36b06b1f46d9f6b02d225365a89d5625ab6bf29ed3949d311c9dac`。
最终Snapshot：`9d8e030235a38d270436f630c07a98786667b08498313f53cbafefc2003e0617`。与初始版本不同，变化文件：CLAUDE.md。

初始/最终test均为168题，顺序一致；官方评分记录及已记录预算终止规则逐题核验。56组scenario成功率：32.14% → 35.71%。

开发机：adas（37744）。远端目录：`/root/blockdata/FlashRSI-AppWorld/runs/evoprompt-claude_code-appworld-20261009-101945-204394`。
压缩归档：713.95 MiB，43704个文件。
归档SHA-256：`6becba301117168adfdfdb8342f98b444e1face48468b1bc58926dd681788aab`。

凭据已脱敏；依赖环境与Docker镜像未打包。支持源码以归档时版本及冻结包记录为准，实际最终harness以Snapshot为准。仅保存本地，未重新调用模型、修改服务器实验、上传GitHub或删除开发机。
