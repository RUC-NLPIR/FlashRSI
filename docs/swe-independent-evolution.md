# SWE-bench 独立演化来源

`benchmark.evolution_data_path` 读取完整、真实的 SWE 原生执行记录，只替换
实验 train，保留原 dev/test。原生问题、镜像、patch/test_patch、eval_script、
log_parser 和官方评分保持不变；Harbor 任务目录不是这种执行记录。

加载器检查两个**完整来源**的 ID、规范化原始问题、任务 checksum 和镜像
是否重合，而不是只检查 tiny smoke 抽中的任务。全部记录须满足原生执行
数据契约，检查后才返回 `evolution_limit` 限制的演化任务。来源元数据记录
实际本地路径、全池数量和 checksum；上游仓库、固定 revision、原文件
SHA 和原生镜像验证另保存在准备报告，不伪造成本地数据自带的元数据。

一个已确认具备原生执行字段的候选是官方
[`SWE-bench/SWE-bench_Lite`](https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite)
revision `b0dde1093fe417d83b7184254edf8199c1f0dff5` 的完整
`data/dev-00000-of-00001.parquet`（23题）。它本身提供 image、eval_script、
log_parser 等字段，无需自行编写镜像或评分脚本。完整23题与此前固定的
Verified 500题没有 ID、原始问题或镜像交集。这里把公开 dev 用作显式的
外部演化实验来源，不称为官方 train，也不是官方独立 test 榜单评测。

保留下载的原始 Parquet 字节，将它的真实路径填入
[公开示例](../examples/modular_rsi_swe_bench.yaml)。所有 native task images、
Docker 连接和固定官方评估器仍须可用；原生字段和零模型启动检查通过，
不能替代真实模型、工具执行与官方评分。按种子和固定 limit 选定任务后，
不得因为镜像可用性或得分重新选题。

此前完整 SWE-bench train 19,008题的 image/eval_script/log_parser 全为空，
原拒绝证据继续保留。不能为使旧集合通过而伪造字段、删除问题，或把
Verified heldout 挪作演化数据。每批次独立保存来源和配置；真实结果维护在
[Smoke 表](smoke-matrix.md)。
