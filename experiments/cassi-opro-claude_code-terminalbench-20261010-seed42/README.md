# OPRO + Claude Code + Terminal

Test：60.00% → 63.33%（18/30 → 19/30）。最终选中候选8，dev为11/15；test未参与选优。

- `full-run.tar.gz`：本次完整实验记录，含配置、9个Snapshot、30批演化/评估轨迹、Worker记录、请求缓存、逐题评分及日志、恢复与审查记录、固定数据划分和支持源码。
- `initial-snapshot.json`、`selected-snapshot.json`：初始和最终选定版本；全部9个Snapshot均通过内容身份校验。
- `initial-harness/`、`final-harness/`：对应Snapshot的原始文件，已按字节核对。可执行属性记录在对应manifest中，迁移Linux时按清单恢复。
- `selection.json`：原始dev选优依据；并列时选较晚候选。
- `supplemental-recovery-records/`：依赖bootstrap目录中的3份诊断记录（状态、下载器源码和日志），按独立manifest核验；依赖下载包本身不保存。
- `result.json`、`file-manifest.json`、`verification.json`：原始结果、逐文件大小和SHA-256、凭据脱敏记录、完整归档校验和及评分重算结果。

初始、最终test均为30题且题目顺序一致，重算成绩与原始报告相符。原始运行因基础设施问题进行过受控恢复；全部审查与恢复记录保留。最终补测复用29题已完成记录，仅剩余任务续跑，既有标记未更改。

初始Snapshot：`524d5ada19ad79e7db416570fe192a21f429050c3320e29fe4ced9e4d6253b0b`。
最终Snapshot：`891726bb7bf9f7126b27a0f4f26860f7549c1a874740960db4c1205e614e3e6f`。
远端目录：`/root/data/FlashRSI-TerminalQA/runs/opro-claude_code-terminalbench-20261008-203444-163873`。
归档：2060.39 MiB，7816个文件。
SHA-256：`d07aa3da08f2a23dc8b321d5641fd36642f0ce4d74cbbd2eca73a186a192de33`。

凭据已脱敏。可重新安装的Python运行环境、依赖缓存、uv二进制和Docker镜像不包含在归档中；明确排除路径记于清单，相关恢复日志及验证报告保留。未打包用户排除的四个旧完成版本。支持源码反映归档时状态，实际harness以Snapshot为准。本次仅保存本地，未调用模型、修改远端实验或上传GitHub。

GitHub 发布说明：原始 `full-run.tar.gz` 因超过 GitHub LFS 单文件 2 GiB 上限，被无损拆分为 `full-run.tar.gz.part01` 和 `full-run.tar.gz.part02`。按顺序拼接即可复原原始归档，分段及复原 SHA-256 见 `publication-parts.json`；本地原始归档保留。上文“未上传 GitHub”描述的是归档创建时状态。
