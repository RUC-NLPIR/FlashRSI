# SkillOpt × SearchQA × DeepSeek 复现指南

本指南使用 `deepseek-v4-flash` 作为 Target 答题模型，使用 `deepseek-v4-pro` 作为
SkillOpt 的演化 Worker，分别运行 MiniAgent 和 Claude Code。配置中的
`agent.llm` 对应 Target，`algorithm.worker.llm` 对应演化 Worker。

这是将 SkillOpt 迁移到上述模型和 harness 的实验设置，与论文的模型和执行协议存在差异。
本页提供运行和结果核查方法，实验数据、模型缓存及运行结果需由运行者自行生成。

## 环境、配置与凭据

先按[快速开始](../README.zh-CN.md#快速开始)安装项目，使用 Linux / WSL 和 Python 3.12，
在仓库根目录运行下列命令。实验脚本使用 POSIX 文件锁。

两份配置分别为 [MiniAgent](../examples/searchqa_deepseek/miniagent.yaml) 和
[Claude Code](../examples/searchqa_deepseek/claude_code.yaml)。它们设置 4 epochs、batch 40、
reflection minibatch 8、merge batch 8、固定 edit budget 4、seed 42，以及 slow/meta update。
MiniAgent 的 Target 使用 `reasoning_effort: high`，Claude Code 使用 `effort: high`；
演化 Worker 使用 `reasoning_effort: high`。这些参数的支持情况取决于实际模型服务。

实验入口从环境变量读取连接信息，也支持通过 `--env-file PATH` 指定凭据文件
（默认 `.env`）。文件由运行者自行创建，权限须为 `0600`；同名环境变量优先。
不要把真实密钥写进配置、技能或版本库。

```bash
export FLASHRSI_BASE_URL="https://your-gateway.example/v1"
export FLASHRSI_API_KEY="your-api-key"
```

网关需提供上述模型，并同时兼容 OpenAI Chat Completions 和 Anthropic Messages。
脚本将该密钥分别注入 Target 与 Worker；MiniAgent 和 Worker 使用给定的 `/v1` 基地址，
Claude Code 使用移除末尾 `/v1` 后的根地址。若需改变模型或算法参数，修改对应 YAML，
并使用新的 `--run-root`。

## 准备数据

```bash
.venv/bin/python scripts/prepare_searchqa.py --output .cache/searchqa/publish
```

准备脚本从 `jinjiajie/EvoOS` 的固定 revision
`2e2d97feb4a3394fd577017024e6d9f3176e9fbc` 获取 `benchmarks/searchqa/`，
生成 `.cache/searchqa/publish/searchqa/` 下的 Parquet 文件及 `manifest.json`。
这是 SkillOpt 的 2,000 题子集，保留来源的 ID、顺序、答案、上下文和 400/200/1400 划分。
来源、字段与校验说明见[数据卡](../scripts/searchqa_dataset_card.md)。

已有同一固定版本的源文件时，可用 `--source-dir PATH` 读取包含 `manifest.json`
及三个 split JSONL 的目录。实验入口默认读取上述准备结果；使用其他输出位置时，
通过 `--data-source PATH` 指向生成的 `searchqa/` 目录。它会核对文件哈希、数量和跨分区 ID，
再按 seed 42 为小规模 profile 抽样；两个 harness 使用同一组题。

## 运行

使用 protocol runner，它包含并行 Worker、上下文溢出处理、无效编辑拒绝和有界格式重试。
为新实验选择独立目录，例如 `runs/searchqa-deepseek-reproduction`。

先准备 smoke 计划，不调用模型：

```bash
.venv/bin/python scripts/run_searchqa_protocol_experiment.py \
  --profile smoke --run-root runs/searchqa-deepseek-reproduction
```

准备计划仍需要有效的凭据字段和已准备的数据，但不会验证远程认证。检查计划后执行：

```bash
.venv/bin/python scripts/run_searchqa_protocol_experiment.py \
  --profile smoke --run-root runs/searchqa-deepseek-reproduction --execute
```

确认模型连接、技能载入及评估链路可用后，再运行完整设置：

```bash
.venv/bin/python scripts/run_searchqa_protocol_experiment.py \
  --profile full --run-root runs/searchqa-deepseek-reproduction --execute
```

| profile | train / dev / test | 演化预算 | 用途 |
| --- | --- | --- | --- |
| `smoke` | 4 / 4 / 8 | 1 epoch，最多 1 fast step | 检查运行链路 |
| `pilot` | 40 / 40 / 100 | 1 epoch，最多 1 fast step | 小规模诊断 |
| `full` | 400 / 200 / 1400 | 4 epochs，共 40 fast steps | 完整迁移实验 |

默认串行运行两个 harness，Target 并发为 4，Worker 并发为 4。可用
`--harness miniagent` 或 `--harness claude_code` 单独运行；`--concurrency`
控制 Target 并发，`--worker-concurrency` 控制演化 Worker 并发。Worker 并发属于算法配置，
修改后须使用新的运行目录。完整设置还包含候选 dev 评估、三组 slow/meta update 及初始/最终 test，
实际调用量取决于候选和重试，并发数不是总调用预算。

## 评分与执行协议

实验专用 `ExperimentSearchQA` 以 SkillOpt 的 `hard` 为主指标：提取最后一个
`<answer>` 标签内的答案；没有标签时取最后一个非空行，再做官方 SQuAD normalization
和 exact match。`f1` 使用相同抽取规则；`exact_match` 和 `lite_f1` 保留普通 Lite
SearchQA 指标供诊断。实现固定对照
[SkillOpt evaluator](https://github.com/microsoft/SkillOpt/blob/79124b37e9a6371e13b753f8bcd7adb1e493ade1/skillopt/envs/searchqa/evaluator.py)。

两个 harness 从相同的空白技能正文开始，保留各自的原生 system prompt 和技能加载方式。
SkillOpt 用 train 反馈生成更新，在 dev 严格提升时接受候选。演化结束并冻结最终 Snapshot 后，
才在同一份 test 上评估初始与最终版本。报告包含 EM、F1、改善/退步题数和配对 bootstrap
95% 区间；test 不参与候选选择。

protocol runner 额外采用以下规则，它们也是与原论文比较时需要报告的执行差异：

- fast reflection / merge / rank 回复格式错误时，在同一逻辑调用内最多追加两次相同 prompt
  和角色配置的请求；额外回复单独保存，不覆盖原始缓存，也不改变后续 Worker 调用序号。
- 完成反思、合并与排序后无法应用的 fast patch 记为 `invalid_patch`，保留当前技能，
  不生成候选或分数；该 step 仍消耗预算。无效 slow/meta 回复也按拒绝规则记录。
- 仅遇明确上下文溢出时，移除 Claude SDK 的纯数字 `thinking_tokens` 进度事件后重试。
  实际推理文本、工具事件、问题、答案和反馈保留，原始 Target 轨迹不变。

这套设置使用 DeepSeek 和 MiniAgent，固定 edit budget、训练 shuffle、反思分组、
patch 协议和原生技能激活方式也与论文存在差异。它不等同于论文 GPT-5.5 条件下的逐调用复现，
也不能仅凭相同 epoch 数认为调用预算相同。

## 缓存与中断后重跑

`plan.json` 固定配置、数据、初始 Snapshot 和相关源码指纹。改变这些内容后须使用新的
`--run-root`；不要修改旧指纹或复用其他实验缓存来绕过检查。

中断后可在原配置、源码和数据均未变化的情况下重跑同一命令。脚本会创建新的 attempt，
从初始版本重放算法，并按调用序号复用已经完成的 Target / Worker 请求；未完成请求重新执行。
相同题目在不同评估轮次仍有不同调用身份。两个格式重试的次数和回复也跨重启保留。
已有 `status: finished` 的结果会直接复用。重新运行前应确认原实验进程已退出，
同一 harness 的并发启动会被文件锁拒绝。

这是独立 SearchQA 实验脚本的请求缓存机制，普通 `flashrsi run` 不提供这套重放恢复。
新实验无需使用 `--adopt-*` 选项；那些选项只用于核对特定旧入口计划的受限迁移。

## 查看结果与独立核查

```text
runs/searchqa-deepseek-reproduction/<profile>/
  data-manifest.json  data/  summary.json
  miniagent/  claude_code/
    plan.json  status.json  result.json
    seed/  cache/  final_skills/
    attempts/skillopt-<harness>-searchqa-<timestamp>/
      config.yaml  snapshots/  trajectories/  result.json
```

各 harness 的 `result.json` 保存完成状态、初始/最终 test 和最终 Snapshot；`final_skills/`
保存最终技能，attempt 下保存逐轮证据。单独启动两个 harness 时，公共 `summary.json`
可能暂时只包含一侧，以各自的结果为准。可离线重建合并报告：

```bash
.venv/bin/python scripts/summarize_searchqa_experiment.py \
  --run-root runs/searchqa-deepseek-reproduction --profile full
```

它生成 `full/report.md` 和 `full/report.json`，汇总 dev、前后 test、配对区间及已记录的用量，
不会调用模型。然后从保存的轨迹重算评分并检查完整性：

```bash
.venv/bin/python scripts/verify_searchqa_experiment.py \
  --run-root runs/searchqa-deepseek-reproduction --profile full \
  --output runs/searchqa-deepseek-reproduction/full/verification.json
```

退出码 `0` 表示保存证据通过，`1` 表示不一致，`2` 表示尚未完成。检查包括数据哈希、
固定题数、初始与最终 test 一致、测试晚于训练、训练覆盖、dev 选择、slow/meta 证据和
最终技能哈希。它验证保存产物的完整性与评分一致性，不会独立重跑模型，也不能验证服务端权重身份。
