# AIME 接入与 CRUXEval 历史记录

> 2026-10-28：按用户要求移除 `cruxeval_output` 适配器、注册和示例。本文 CRUXEval 段落及旧验证报告仅保留为历史证据，当前不可运行；AIME 仍可使用。执行型 Coding 基准见[当前接入说明](coding-working-benchmarks.md)。

新增两个适配器，复用现有 `QABenchmark`、数据划分、Agent 文本执行和 runner。
无需 Docker、GPU、Judge 或额外 Python 依赖。算法与 Target Agent 的组件要求仍由
原有初始化检查负责，没有在算法内添加基准分支。

| 配置 | 内容 | 固定来源与下载规模 | 评分 |
| --- | --- | --- | --- |
| `name: aime`, `year: 2026`（默认） | 2026 AIME 数学题，30 题 | [math-ai/aime26](https://huggingface.co/datasets/math-ai/aime26/tree/79037aebdb6580008fb960d17cb21fd3099083e3)，JSONL 13,101 字节 | `integer_exact`，最终整数准确率 |
| `name: aime`, `year: 2025` | 2025 AIME 数学题，30 题 | [math-ai/aime25](https://huggingface.co/datasets/math-ai/aime25/tree/563bb8404243c5f09de6ec262f2db674fe5bce9b)，JSONL 15,813 字节 | 同上 |
| `name: cruxeval_output` | CRUXEval-O（2024），800 道短 Python 函数输出预测 | [cruxeval-org/cruxeval](https://huggingface.co/datasets/cruxeval-org/cruxeval/tree/b96af0450242eb4da433032b90998f25588a5d0f)，JSONL 186,873 字节 | `literal_output`，Python 字面量的值比较 |

AIME 优先覆盖新年份；CRUXEval 年份较早，但原始数据小、公开可下载，且输出预测
可以在不执行函数或模型代码的情况下评分，适合当前的轻量实验环境。
下载使用 Hugging Face 缓存并固定 revision。数据不随 wheel 分发，也不进入 Snapshot。

## 运行

复制示例到项目根目录，填写目标 Agent 与 Worker 各自的模型、连接和凭据：

```powershell
Copy-Item examples/aime_opro.yaml aime.local.yaml
python scripts/run_experiment.py --config aime.local.yaml --plan
python scripts/run_experiment.py --config aime.local.yaml --check-only
python scripts/run_experiment.py --config aime.local.yaml
```

切换到 2025 年可追加 `--benchmark.year 2025`。
旧代码方向示例 `examples/cruxeval_output_opro.yaml` 已于 2026-10-28 删除。
示例均为 OPRO、一轮、一个候选、8 train / 4 dev / 4 test；AIME 总题量小，这个
划分用于验证链路，不足以支持稳定的泛化结论。
`--check-only` 加载真实数据并初始化组件，不调用模型、不验证 API 认证。

一键入口可用 `--cache-dir` 指定可写缓存；直接运行已安装的 `flashrsi` 时可设置
`HF_HOME`（已有 `HF_HUB_CACHE` 优先）。`limit` / `split_counts` 只减少实验题数，
仍会下载完整原始文件。

## 数据与划分

三个题池都只有原生公开 `test`。默认 `split: auto` 保留这一角色，train/dev 为空；
需要训练数据的算法会报错。示例显式将公开题池划分为互斥的实验 train/dev/test，
使用既有 seed 与任务 ID 规则；这是**自定义实验划分**，不能报告成未见过的官方榜单测试。
最终测试仍沿用 runner 的 sealed test 流程。

本地数据保持原字段即可，支持现有 JSON / JSONL / Parquet / CSV 和路径映射：

```yaml
benchmark:
  name: aime
  year: 2026
  data_path:
    train: ./data/train.jsonl
    dev: ./data/dev.jsonl
    test: ./data/test.jsonl
```

路径相对配置文件解析。也可用单文件加 `split_counts`；任意文件名若没有明确角色，
不会自动作为训练数据。

- AIME 要求 `id`、`problem`、`answer`。原始 2025 ID 为字符串、2026 ID 为整数，
  均接受；答案须为 0–999 的整数或 1–3 位数字字符串。任务 ID 带年份前缀。
  本地数据的年份由 `benchmark.year` 指定，题目文本原样保留，仅追加答案格式要求。
- CRUXEval 要求非空字符串 `id`、`code`、`output`，`input` 为字符串，允许空字符串表示
  无参调用 `f()`（原始题池包含 1 题）。答案须可解析为 Python 字面量。
  题目使用原生 direct output 提示，其中自带两道示例；当前题的参考输出不加入提示。

重复 ID 会在划分时拒绝；失败轨迹计零分；评分依据加载时保存的答案与输入，
不会使用轨迹里被替换的参考答案。

## 评分协议

**AIME** 使用 `scoring: integer_exact`。先读取最后一个 `\boxed{...}` 或
`\fbox{...}`；没有框时读取最后一个非空行。只接受 1–3 位十进制数字，前导零等价。
末尾不完整的框计错，不回退到前面的正确答案。整数之外的算式、浮点数、选项或
含说明文字的答案行不做猜测，也不调用符号数学或 Judge。指标 `accuracy` 是逐题均值。

**CRUXEval-O** 使用 `scoring: literal_output`。原生提示来自
[固定 commit 的 prompts.py](https://github.com/facebookresearch/cruxeval/blob/190faf16d175b5847b0af05d937872b1fb395942/prompts.py)
中的 `make_direct_output_prompt`。接受以下输出：

```text
[ANSWER]
assert f(0) == [1, 2]
[/ANSWER]
```

也接受不带标签的单条断言或裸字面量，以及原生提示已预填 `[ANSWER]` 后的续写。
断言必须调用题目给定的同一个输入，右侧必须是可解析的字面量。评分只解析语法树和
调用 `ast.literal_eval`，不执行题目函数、不执行断言、不执行模型生成代码。
因此字符串的单双引号、字典顺序不影响结果，列表与元组仍有区别；数值遵循 Python
`==`，例如 `True == 1`，与上游在有效字面量上的比较语义一致。

函数调用、推导式、多条语句、错误输入和超长输出（超过 65,536 字符）均计错。
不采用上游按 `==` 切字符串的后处理，避免损坏本身含 `==` 的字符串字面量。
配置 `scoring: official` 会报错，避免误称完整上游评估。
未接入 CRUXEval-I 输入反推、CoT / Phind 提示、任意代码执行回退和多样本 pass@k；
当前结果是每题一次输出的准确率。需要实际代码生成、执行测试或仓库修改的任务，
继续使用已有的 SWE-bench / Terminal-Bench 等执行型适配器。

## 来源与验证

AIME 使用上述 math-ai 镜像，数据卡标注 Apache-2.0；没有将镜像当作竞赛主办方发布的
官方评测实现。CRUXEval 的数据与上游提示为 MIT，许可与归属信息统一放在项目外部发布材料中；
提示 AST 与固定上游 commit 对齐。来源还包括 [CRUXEval 论文](https://arxiv.org/abs/2401.03065)
及其[原始评估逻辑](https://github.com/facebookresearch/cruxeval/blob/190faf16d175b5847b0af05d937872b1fb395942/evaluation/utils_general.py)。

验证记录见本地记录 `validation-coding-math-benchmarks-20261025.json`和
本地记录 `smoke-matrix.md`。全量数据加载、参考答案回填与格式化答案回填
用于检查适配器和评分协议，不等于模型解题，也不验证参考答案在数学或程序上的正确性。
真实算法 × Target Agent × Benchmark 模型 smoke 尚未运行；本地未配置角色 API 密钥。

实测结果：AIME 两年份各 30/30、CRUXEval 800/800 的裸答案与格式化答案回填通过，
自定义划分可重现且互斥。全量回归 626 项通过、9 项跳过、3 个 subtest 通过；
随后补充无参函数适配与两项用例，受影响的专项及启动器测试复测 78 项通过。
全部源码 lint / 格式检查通过。最新 wheel 已独立安装，AIME 两年份和 CRUXEval 的
MiniAgent + OPRO `--check-only` 均通过；提示代码、适配代码与许可证在 wheel 内核验一致。


## AIME 独立演化来源

`benchmark.evolution_year` 可以显式选择另一个已接入的固定年份，例如 AIME2026 的实验使用 `evolution_year: 2025`、`evolution_limit: 1`。这是将另一年的公开 test 题池用于自定义演化实验，不是声称它存在官方 train split。两个完整题池先检查题目文本重合，之后才抽取演化题；2026 的 dev/test 划分保持原样，train 替换为2025题目。原生整数评分不变，元数据记录真实来源、revision、年份、题池校验和与用途，不能通过手填 evolution_source 绕过检查。

见 [ModularRSI + AIME 示例](../examples/modular_rsi_aime.yaml)。Claude Code 版本使用公开的 [三扩展示例](../examples/modular_rsi_claude_code.yaml) 中的 `agent.source_dir` 与 prompt/skill/hook 文件映射；仅修改 benchmark 为上述两年配置，保留独立角色预算，不将 Claude 默认未提供的五个运行时模块映射成已存在。旧数据缺失拒绝记录保留，新配置通过真实模型 smoke 后另计。
