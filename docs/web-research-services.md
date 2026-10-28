# DeepSearchQA 与 OfficeQA 配置

DeepSearchQA 可使用 `examples/deepsearchqa_serper_jina.yaml`：
`benchmark.retrieval.provider: serper`，搜索密钥放在其 `api_key`；
`benchmark.retrieval.reader.provider: jina`，阅读密钥放在 reader 的 `api_key`。
两项凭据分别发送给 Serper 与 Jina，保存在主机配置中，不发给答题模型。

Judge 配置独立于 Target 和 Worker。默认 `benchmark.judge.provider: google`
使用原生 `gemini-2.5-flash`；显式选择 `openai` 可使用 DeepSeek 等兼容服务。
后者沿用固定评分提示、解析和指标公式，记录实际 Judge 模型及 `custom` 身份，
**不等同官方 Gemini 分数**。如需与 Target 使用同一模型，应显式填写相同连接配置。

复制示例为 `*.local.yaml`，填好凭据后依次执行：

```bash
python scripts/run_experiment.py --config deepsearchqa.local.yaml --plan
python scripts/run_experiment.py --config deepsearchqa.local.yaml --check-only
python scripts/run_experiment.py --config deepsearchqa.local.yaml
```

OfficeQA-Pro 使用 `examples/officeqa_pro_opro.yaml`。
`benchmark.corpus_path` 指向完整公开文档目录，题目与答案 CSV 不放在该目录中。
默认从固定版本的 `databricks/officeqa` 获取题目，HF 访问授权通过环境中的
`HF_TOKEN` 提供；已有完整原生 CSV 可显式设置 `benchmark.data_path` 复用。
示例的 1/1/1 是自定义实验划分，不是上游官方 train/dev/test。

服务协议参考：[Serper](https://serper.dev/)、[Jina Reader](https://github.com/jina-ai/reader)。
