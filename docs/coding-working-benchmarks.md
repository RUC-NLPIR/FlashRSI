# Coding 与 SpreadsheetBench 2 接入

2026-10-28：移除 CRUXEval-O 的当前适配器、注册与示例，保留历史验证记录。
SWE-bench Verified 与 SWE-bench Pro 已有适配，本轮补齐明确命名的运行示例；
新增 Terminal-Bench 2.1 版本选择与 SpreadsheetBench 2 的前三类。

| Benchmark | 配置 | 容器与评分 | 示例 |
| --- | --- | --- | --- |
| Terminal-Bench 2.1 | `name: terminal_bench`, `version: "2.1"` | Harbor，原生任务 verifier | [Terminal 2.1](../examples/terminal_bench21_opro.yaml) |
| SWE-bench Verified | `name: swe_bench` | 官方 SWE-bench harness + Docker，`resolved` | [Verified](../examples/swe_bench_verified_opro.yaml) |
| SWE-bench Pro V2 | `name: swe_bench_pro`, `subset: all` / `hard` | Harbor 执行，官方 fresh-sandbox 评分，`resolved` | [Pro](../examples/swe_bench_pro_opro.yaml) |
| DeepSWE v1.1 | `name: deepswe` | Harbor 原生 collect + 独立 verifier，`reward`；本轮仅离线接口验证 | [DeepSWE](../examples/deepswe_opro.yaml) |
| SpreadsheetBench 2 | `name: spreadsheetbench2`, `category: all` | Harbor 独立评分容器，官方 LibreOffice 重算与 workbook 评分 | [SpreadsheetBench 2](../examples/spreadsheetbench2_opro.yaml) |

不是所有 Docker 基准都由 Harbor 管理：Verified 保留官方 harness；AppWorld / BFCL 也保留各自 Docker 接入。
一键入口根据配置选择依赖和准备数据；Harbor 类基准的任务镜像由 Harbor 构建和管理。

## 一键运行

需要 Python ≥3.12、Git、Docker Linux daemon 和 Docker Compose。复制示例到项目根目录，
分别填写 `agent.llm` 与 `algorithm.worker.llm`，然后：

```powershell
Copy-Item examples/spreadsheetbench2_opro.yaml spreadsheet.local.yaml
python scripts/run_experiment.py --config spreadsheet.local.yaml --plan
python scripts/run_experiment.py --config spreadsheet.local.yaml --check-only
python scripts/run_experiment.py --config spreadsheet.local.yaml
```

`--check-only` 只完成前置条件、数据和组件初始化，不构建全部任务镜像、不调用模型，不能代替真实 smoke。
Windows 一键脚本自动启用 UTF-8；直接调用已安装的 `flashrsi` 时先设置 `$env:PYTHONUTF8='1'`，供原生 Harbor 读取非 ASCII 任务文本。
示例为 OPRO、一轮一个候选、train/dev/test 各 1 题，属于自定义实验划分。
没有把官方公开评测题池声称为独立训练集；ModularRSI 可以使用同源且互斥的实验划分。

## Terminal 2.1

固定[官方仓库](https://github.com/harbor-framework/terminal-bench-2-1/tree/7131e4375048a0e408a8fb404b5f499d726b695b)
commit `7131e4375048a0e408a8fb404b5f499d726b695b`，读取其 `tasks/`。
`version` 必须是字符串；现有默认值仍为 `"2.0"`，不改旧实验的来源或解释。
本地 `data_path` 应指向 `tasks/` 或一个原生任务目录。

## SpreadsheetBench 2

固定[官方代码](https://github.com/RUCKBReasoning/SpreadsheetBench-2/tree/a7bdc2d358e052d35a94768e1f487c0d9e9c0011)
commit `a7bdc2d358e052d35a94768e1f487c0d9e9c0011`，以及
[官方数据集](https://huggingface.co/datasets/KAKA22/SpreadsheetBench-v2/tree/5a2215ed4121945ab09d8723df2995602090b042)
revision `5a2215ed4121945ab09d8723df2995602090b042` 的 `spreadsheetbench-v2-09-10.zip`（134,232,213 字节）。

| `category` | 题数 |
| --- | ---: |
| `Debugging` | 100 |
| `Financial_Model` | 100 |
| `Template` | 97 |
| `all`（默认，仅上述三类） | 297 |

`Visualization` 明确报错，尚未接入 Windows、Excel/WPS、图表导出和视觉模型评分。
本地 `data_path` 可以指向解压后的 `spreadsheetbench-v2/`，其下保留各分类的 `dataset.json` 和 `spreadsheet/`；
路径按既有规则相对 YAML 文件解析。即使使用本地数据，仍从固定 Git commit 获取官方评分代码和 Dockerfile。

接入层把原始行及表格文件映射为 Harbor task：Agent 镜像只含当前输入表格 `/app/input.xlsx`；
交付文件写到 `/logs/artifacts/<原始id>_output.xlsx`。输入在镜像构建时重算。
Harbor 将交付物转交独立评分容器，评分容器重新计算原始输入、标准答案和交付物，调用官方
`evaluation.py` 的 `process_single_item`。两个官方 Python 文件原样复制，未重写评分规则；
Agent 与独立评分容器分别从 `environment/` 和 `tests/` 构建；两个目录均提供基于官方 recipe 的 Dockerfile。
保留 Debugging 文件名驱动的 Color / Embedded 模式和原生容差。
原生 LibreOffice helper 会吞掉部分错误，接入层通过保存时间检查检测未成功重算，明确报错。

主指标 `reward` 对应官方逐题 `accuracy`：regression accuracy 与 modification accuracy 均为 1 才通过；
官方 regression ≥0.998 归一为 1 的规则照常保留。细分指标保留在 Harbor verifier rewards，
原始逐题结果写入 verifier 的 `native-result.json`。缺失输出按官方逻辑计零；基础环境和重算失败不冒充正常评分。

原始数据、固定源码和生成任务使用缓存，不进入 Snapshot；生成任务内容指纹和 Harbor checksum
检测缓存变化，修改过的缓存会报错。`split_counts` 限制实际实验题数，首次仍下载完整归档并准备所选分类任务。

## 本轮验证边界

见本地记录 `validation-coding-working-20261028.json`和本地记录 `smoke-matrix.md`。
本轮机器缺少 Docker CLI，未执行新基准的容器或真实模型组合。真实数据加载、原生配置解析、
离线评分控制、单元测试和 wheel 入口核验均单独记录；旧 Terminal 2.0 smoke 不计为 2.1 通过。

开源流程复核发现并修复了独立评分容器缺少构建入口的问题，新增测试使用 Harbor 自身的
评分环境选择与构建前置检查，不能替代完整容器执行。当前 Harbor 接入将 rewards 和日志
写入 Trajectory 后清理临时 trial 目录，交付 `.xlsx` 和 `native-result.json` 尚未长期归档；
因此目前不能承诺实验结束后能从保存结果独立重算 workbook 评分。这仍是可复现交付的缺口。
