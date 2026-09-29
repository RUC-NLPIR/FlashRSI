# OPRO 优化过程

优化对象：`CLAUDE.md`，附加在 Claude Code 原生系统提示词之后。候选按 400 道训练题的 hard 选择；测试集不参与选择。

共 5 轮、20 个候选。最后统一选择训练集最优版本；单条最终 decision 不是候选总数。

|候选|轮次|训练 hard|文本|
|---:|---:|---:|---|
|0|初始|74.25%|[00.md](prompts/00.md)|
|1|1|78.25%|[01.md](prompts/01.md)|
|2|1|79.00%|[02.md](prompts/02.md)|
|3|1|79.25%|[03.md](prompts/03.md)|
|4|1|77.75%|[04.md](prompts/04.md)|
|5|2|78.75%|[05.md](prompts/05.md)|
|6|2|78.25%|[06.md](prompts/06.md)|
|7|2|75.75%|[07.md](prompts/07.md)|
|8|2|77.00%|[08.md](prompts/08.md)|
|9|3|78.75%|[09.md](prompts/09.md)|
|10|3|78.25%|[10.md](prompts/10.md)|
|11|3|76.75%|[11.md](prompts/11.md)|
|12|3|75.25%|[12.md](prompts/12.md)|
|13|4|73.75%|[13.md](prompts/13.md)|
|14|4|79.25%|[14.md](prompts/14.md)|
|15|4|77.25%|[15.md](prompts/15.md)|
|16|4|78.75%|[16.md](prompts/16.md)|
|17|5|77.75%|[17.md](prompts/17.md)|
|18|5|73.00%|[18.md](prompts/18.md)|
|19|5|75.50%|[19.md](prompts/19.md)|
|20|5|80.25%|[20.md](prompts/20.md) **最终选中**|

完整 Worker 输入、输出、逐题评估和快照见 `logs.tar.gz` 中最终 attempt 的 `trajectories/` 与 `snapshots/`。本页从最终 decision 的 history 原样导出，没有重新运行模型。
