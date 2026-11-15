# WebShop

注册名 `webshop`。使用原生文字环境 `WebAgentTextEnv`，提供 `search[...]` 和
`click[...]`，保留官方搜索、商品选项和购买评分。上游固定为
[princeton-nlp/WebShop@64fa2a5](https://github.com/princeton-nlp/WebShop/tree/64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd)。

## 数据与运行环境

[FlashRSI HF 版本](https://huggingface.co/datasets/RUC-NLPIR/FlashRSI/tree/3d89e1589deeb3215c468849ba1b268beb9b0eba/webshop)
提供 150 / 75 / 150 的 train/dev/test 任务 ID，与原生划分对应；抽样只减少任务数量，
商品库仍使用全量。该 HF 版本状态为 `task_ids_only`，不包含商品库、Lucene 索引或运行依赖。
选择示例中的 `dataset` 后，框架自动下载并校验这些 ID 和选择清单。

需要另外准备：

- `benchmark.native_root`：上述 commit 的原生 checkout，包含
  `data/items_shuffle.json`、`data/items_ins_v2.json`、`data/items_human_ins.json`
  和 `search_engine/indexes/` 的完整 Lucene 索引。不能使用默认的 1,000 商品预览库。
- `benchmark.native_python`：已安装原生依赖的独立 Python 可执行文件。
  官方安装基于 Python 3.8.13、Java 和原生 requirements；不要把这些旧依赖装进
  FlashRSI 的 Python >=3.11 环境。安装说明见
  [官方 README](https://github.com/princeton-nlp/WebShop/blob/64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd/README.md)。
  固定版本的评分代码还需要 `en_core_web_sm`，即使 setup 脚本下载了 `en_core_web_lg`，
  仍需在原生环境执行 `python -m spacy download en_core_web_sm`。
- Docker Linux daemon，用于运行目标 harness；目标模型需显式设置 `agent.llm.base_url`。

`native_root`、`native_python` 是 WebShop 专有路径，相对启动命令的当前工作目录解析；
推荐填写绝对路径。无需修改原生 `utils.py`：接入层在独立进程内选用完整商品和属性文件。
原生 `web_agent_site` 源码若有本地改动会拒绝执行。

## 运行

填写 [webshop_opro.yaml](../examples/quickstarts/webshop_opro.yaml) 中的原生路径和两套独立模型配置：

```bash
python scripts/run_experiment.py --config examples/quickstarts/webshop_opro.yaml --plan
python scripts/run_experiment.py --config examples/quickstarts/webshop_opro.yaml --check-only
python scripts/run_experiment.py --config examples/quickstarts/webshop_opro.yaml
```

示例 `limit: 3` 在已发布划分内保留每个角色各一题；移除后使用完整 150 / 75 / 150。
`max_steps` 限制环境动作数，`agent.max_turns` 限制模型轮数。`seed` 同时固定商品价格和
目标价格条件的生成，必须在对比实验中保持一致。

也可先运行 `uv run python scripts/prepare_webshop.py`，再用 `benchmark.data_path`
指向生成的划分目录并移除 `dataset`。本地加载与 HF 加载共用划分校验。
当前不自动安装旧版原生环境，也不自动下载完整商品资源。
`--check-only` 检查接入和资源布局；真实目标顺序、搜索与评分还需要执行任务验证。

## 评分与隔离

主指标 `reward` 是原生购买 reward（0–1），同时记录 `success`（reward 等于 1）。
未购买、达到动作上限或执行失败记 0；不使用模型最终文本或模型自报的分数评分。
`WebShopVerifier` 由宿主追加，记录任务校验和、上游版本、seed、步数、目标校验和及评分。

每题原生进程独立，所有模型调用仍由用户选择的 harness 执行。环境只给它页面文字、
可点击项和动作客户端；不替换 prompt、tool、skill、agent loop 或 Snapshot。
模型不能经客户端访问评分、reset、其他任务或原生 Python；解题容器没有商品库、
目标文件、原生源码的宿主挂载，网络只允许配置的模型端点。购买结束页的评分调试内容
不返回给模型，购买后禁止再次操作。

加载完整原生目标后，会用官方 baseline 的文本规范化方式逐项核对 12,087 条目标的顺序，
与 HF 任务编号不符即报错，不用相似文本猜测对应题。每题重新初始化完整原生资源，
因此启动和内存开销较大；批量实验应先以低并发验证资源需求。

已在原生 1,000 商品预览库上完成初始 MiniAgent 的 3 题真实模型交互，搜索、商品选项、
购买和原生评分均已执行；24 个动作经独立重放，页面反馈及评分一致。预览运行使用本地
验证脚本和独立原生容器，不通过正式 HF 全量商品库加载路径，也未运行算法演化。
其结果不能当作 HF 划分的正式成绩；完整商品库和完整实验流程仍待验证。
