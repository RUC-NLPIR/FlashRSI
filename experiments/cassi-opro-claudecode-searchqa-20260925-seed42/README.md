# OPRO / Claude Code / SearchQA · 2026-09-25 · seed 42

Contributor: cassi。状态：finished。正式实验北京时间 16:07–19:26，约 3 小时 19 分钟。

|指标|初始测试|最终测试|
|---|---:|---:|
|hard / EM|73.3571%（1027/1400）|81.4286%（1140/1400）|
|F1|84.2449%|88.4985%|

配对提升 8.0714 个百分点：143 题改善、30 题退步；bootstrap 95% 区间 [6.2857, 9.8571] pp。单 seed 结果，不能替代多 seed 验证。

## 中间过程

直接阅读 [20 个候选及训练分数](process.md)，[机器可读候选历史](candidate-history.json) 和 [各版本提示词](prompts/)。初始训练 hard 为 74.25%，最终为 80.25%，选中第五轮第 20 个候选。只优化 CLAUDE.md，保留原生 Claude Code system prompt。

## 配置与核验

固定 train/dev/test = 400/200/1400，与此前 MiniAgent 实验的数据清单完全一致；5 轮 × 4 候选，history 20、few-shot 3、seed 42；训练集选优，dev 不用于选优，选定后分别评测初始和最终版本的同一 1400 道测试题。逐题 hard/F1 已独立复算，与汇总一致。

目标官方 deepseek-flash（模型列表名称 DeepSeek-V4.1-Flash），Anthropic 兼容端点；Worker deepseek-v4-pro，官方 OpenAI 兼容端点。目标并发 4、32768 token、600 秒、10 turns、high effort、原生请求重试 1；Worker 串行、65536 token、900 秒、high reasoning、SDK 重试 1。独立请求核验确认实际目标请求 max_tokens=32768、adaptive thinking、effort=high。缓存层每次调用至多两次尝试，失败停止、不自动无限重启。

这些上限从实验开始生效，与之前 MiniAgent 的初始预算和中途恢复策略不同，不能声称只改变了 harness。执行 commit 0fb05ef；执行源代码归档、环境版本、参数检查、smoke 摘要和独立分数核验位于日志中的 run/evidence/。打包 commit 不替代执行版本。

正式运行成功目标任务记录 11200、Worker 20，失败记录 0；不代表 SDK 内部没有重试。记录输入 token 135385090，输出 4962521，缓存读取 54430080（输入的子集）。SDK 成本估计 USD 432.3372416 的 cost_basis 为 unknown，不是官方实际账单，Worker 费用也未计入。独立 smoke 和参数探测用量不属于正式运行汇总。

## 归档

configs/ 保存配置与数据清单；summaries/ 保存结果和用量；logs.tar.gz 保留完整持久化记录，包括候选、Worker、逐题答案、快照、规范缓存和证据；临时 working、锁和缓存产物按打包脚本排除。manifest.json 保存 SHA256、文件数和体积。新增 process.md、prompts/、candidate-history.json 仅供直接阅读，不替代完整日志。

已扫描已知凭据和常见 sk-token（含快照内容）；原始路径、端点和题目内容保留。完整压缩包应使用 Git LFS。解包不会自动转换历史路径为可续跑配置。本次只保存本地，不提交或推送。
