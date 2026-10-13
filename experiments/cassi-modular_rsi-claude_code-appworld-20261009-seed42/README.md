# modular_rsi + claude_code + appworld

当前按用户明确要求保存后续首轮合并 Snapshot `9cf5cca95b01503bc34455a157499d5c1dbbe44d5da88d09452b99d423b8297e`，`selected-snapshot.json` 与 `final-harness/` 已同步替换并逐文件校验。

完整 test：58.33% → 56.55%（98/168 → 95/168），变化 −1.79 个百分点。Scenario 成功率：17/56 → 13/56。最终测试于北京时间 2026-10-11 00:37:02 完成，复用历史 baseline，final 为独立完整 168 题测试。本次保存调整未调用模型。

用户说明调整原因是此前超参设置问题。本次属于用户明确指定保存版本，原算法按 dev/gate 选择初始版本的历史记录及 gate 失败标记保留，未改写为算法自动选中或 gate 通过。采用时已知补充 test 结果，详见 `selection-adoption.json`。

- `initial-snapshot.json`：原初始版本，保持不变。
- `selected-snapshot.json`、`final-harness/`、`final-harness-manifest.json`：当前用户指定保存版本及逐文件哈希。
- `result.json`、`verification.json`：与当前保存版本对应的完整测试摘要和校验。
- `adopted-test-evidence/`：既有 baseline/final 逐题记录、补充测试结果和原选择/gate 证据。
- `selection-history/user-adoption-20261011-071153-615930/`：替换前的 Snapshot、harness、结果、README 和校验记录。
- `full-run.tar.gz`、`file-manifest.json`：原历史完整运行归档，字节不变；归档内部原选中版本保持历史原貌，当前保存版本以外部 `selected-snapshot.json` 为准。

补充测试来源：`/root/data/FlashRSI-AppWorld/runs/modular_rsi-claude_code-appworld-first-merge-test-20261011-000433-692666`。完整历史归档 421.83 MiB，28684 个文件，凭据已脱敏，依赖环境和 Docker 镜像未打包。本次仅调整本地保存版本，不修改 MiniAgent，不重新评估，不推送 GitHub。
