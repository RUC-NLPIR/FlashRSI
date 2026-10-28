# SearchQA 独立演化来源

## 使用独立的 TriviaQA 原生 train

[可运行来源示例](../examples/modular_rsi_searchqa_triviaqa.yaml) 通过
`benchmark.evolution_triviaqa: {split: train}` 读取完整原生 TriviaQA
`rc.wikipedia` train，仅替换 SearchQA 的实验 train。来源固定为
`mandarjoshi/trivia_qa` revision `0f7faf33a3908546c6fd5b73a660e0f8ff173c2f`。
真实来源检查显示，完整 61,888 条 train 与 SearchQA 的全部三个原生池均无
ID 或规范化原始问题交集；仍由公开加载器在每次加载时检查完整实际来源，
然后才使用 `evolution_limit` 取样，不依赖外部脚本伪造元数据。

外部任务保留 TriviaQA 原生问题、Wikipedia 证据、ID、答案及别名，使用其
已有原生 Task 加载器。所有演化和下游任务仍由 SearchQA 既有 text EM/F1
评分，不宣称演化题采用 TriviaQA 官方评分器。SearchQA 的 dev/test、题目、
原始搜索片段、算法和 gate 不变；这是跨数据集外部演化实验，不是 SearchQA
官方 train，也不是官方榜单评测。`evolution_triviaqa` 与 `evolution_split`
互斥。

`evolution_triviaqa.dataset` 可显式覆盖完整原生来源，例如使用经过逐文件
SHA 校验的原始 Parquet 缓存目录：

```yaml
evolution_triviaqa:
  split: train
  dataset:
    source: /absolute/path/to/complete-native-triviaqa-parquet-directory
    config: default
    revision: 0f7faf33a3908546c6fd5b73a660e0f8ff173c2f
```

该目录由 `datasets` 原生流式读取，保留全部原始 train 分片；本地 Parquet
builder 的配置名为 `default`。此来源字符串遵循 `datasets` 本身的解析规则，
相对值基于运行时工作目录，推荐明确写绝对路径。缓存和零模型来源验证不
替代两 Target 的真实算法 smoke。

## 原生 SearchQA split 的重合诊断

[公开示例](../examples/modular_rsi_searchqa.yaml) 声明完整原生 train ZIP 演化、完整 validation ZIP 作自定义下游 1/1/1 划分，用于检查来源独立性。真实全池核查已确认该配置会在 `--check-only` 拒绝：train/validation、train/test、validation/test 分别有 439、145、23 个规范化问题交集。它目前不是可直接正式运行的 ModularRSI 配方，不能删题或关闭检查来使它通过；见[完整原生来源核查](smoke-searchqa-native-pool-overlap-20261026.json)。后续需真正独立的来源；公开 `data_path` 可指定真实独立的原生格式下游数据，仍接受同样的全池检查。

通过统一入口的 `--plan`、`--check-only` 后，条件具备时才正式运行。首次准备可能需要下载较大的原生 ZIP；已有完整 Hugging Face 缓存可以复用。本轮仅做零模型来源检查，没有因为该配置重复付费。

`benchmark.evolution_split` 支持原生 `train`、`validation`、`test`。加载器先检查完整来源的 ID 和规范化原始问题文本，再应用 `evolution_limit`。相同问题即使上下文不同也会被拒绝；不能把下游已经包含的原生 split 再声称为独立来源。仅替换实验 train，下游 dev/test 不变。使用原生公开 test 作演化时应明确声明为外部实验来源，不宣称官方独立 test 评测。

来源固定为 `kyunghyuncho/search_qa` 的 `train_test_val`，revision `06907e45883b7cae435453b65d598447039fde79`。元数据记录实际 source/revision/native split、全池数量和校验和。原始问题、搜索片段、答案和既有 text EM/F1 评分均保留；空 snippet 仍按原有规则处理。实现复用 QA 基类的完整来源检查，不修改算法、gate 或预算。

MiniAgent 使用五模块，Claude Code 使用[公开 prompt/skill/hook 三扩展示例](../examples/modular_rsi_claude_code.yaml)。数据准备、离线验证与真实模型 smoke 分别记录在 [Smoke 表](smoke-matrix.md)，旧缺来源拒绝和失败历史保留。
