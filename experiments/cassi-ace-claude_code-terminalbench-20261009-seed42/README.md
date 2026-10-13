# ACE + Claude Code + Terminal 正式完整归档

正式test：60.00% → 66.67%（18/30 → 20/30）。最终使用最后有效训练playbook，35次已接受更新；dev仅报告，test未参与选择。

- `full-run.tar.gz`：最新完整补测运行目录，包含30题原始模型轨迹、官方评分、缓存、失败与评分恢复记录、配置、支持源码、固定任务和数据划分。
- 包内 `history/original-training/`：从原已核验归档合并的完整训练、Worker调用、候选、baseline及原始协议记录；原包外元数据也保存在 `saved-local-metadata/`。
- 包内 `formal-selected/`：本次正式初始/最终Snapshot、最后训练playbook、选定依据、训练决策及逐题核验资料。
- `initial-snapshot.json`、`selected-snapshot.json`、`final-harness/`：正式版本，可直接查阅；最终文件与Snapshot字节一致。
- `file-manifest.json`、`verification.json`：完整逐文件SHA-256和大小，以及归档、test和Snapshot核验。

初始Snapshot：`524d5ada19ad79e7db416570fe192a21f429050c3320e29fe4ced9e4d6253b0b`。
最终Snapshot：`10b3f0350e3c153c1b7543e162d8d290d59860e2ff2a22ea8cacbf9290af3631`。
最终成绩对应30题独立final test；初始30题记录复用原baseline，不重新调用模型。

最新远端目录：`/root/blockdata/FlashRSI-TerminalQA/runs/ace-claude_code-terminalbench-20261009-002049-704918`。
原训练目录：`/root/data/FlashRSI-TerminalQA/runs/ace-claude_code-terminalbench-20261006-130240-288168`（历史内容已合并保存本地）。
压缩包：777.94 MiB；3683个文件。
归档SHA-256：`d5a8c63ff3ed02cf5b7a04507b010fb153b66f7ee96e705c04c7096c81a8625c`。

本包替代旧60%→60%的正式归档，原始历史记录保存在包内。凭据已脱敏；Docker镜像、虚拟环境不包含在包中。本次未启停实验或重新调用模型。
