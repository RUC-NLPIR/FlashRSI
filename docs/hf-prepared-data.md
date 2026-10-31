# HF 数据源

当前适配 `RUC-NLPIR/FlashRSI` 的 `benchmark-directories.v1` 布局，固定 revision 为 `8e226b748e648d4e001cf247f255cfb9eb752292`。覆盖 **29 个 Benchmark、34 份实验配置**；**HLE 单独使用官方 HF `cais/hle` 的纯文本题目，不纳入本镜像**。原有原生默认来源保留，只有明确配置 `benchmark.dataset` 才使用本仓库数据。

## 选择数据

```yaml
benchmark:
  name: terminal_bench
  dataset:
    source: RUC-NLPIR/FlashRSI
    revision: 8e226b748e648d4e001cf247f255cfb9eb752292
    config: terminal_bench_2_0
  split: auto
  limit: 3  # 可选；省略时加载完整发布划分
```

`config` 使用下表中的新名称。目录由固定 revision 的 `metadata/catalog.json` 定位，再读取该目录下的 manifest。原生资源从 manifest 声明的 `native/` 路径获取，不重新访问旧的 `prepared/日期/` 目录。文件大小、SHA-256、划分 ID 的数量、重复、重叠和原生任务是否缺失都会检查。

这批数据使用已经发布的固定实验划分。请移除原示例中的 `split_counts`、比例划分、`data_path` 和 `evolution_*` 数据覆盖项，使用 `split: auto`。`limit` 只在各个角色内采样，不将 test 分配到 train。HF 中保留的 `native` 来源配置和完整上游归档属于来源资料，不会自动混入已选实验划分。

## 当前配置

| Benchmark 注册名 | HF config | 目录 | train / dev / test |
| --- | --- | --- | --- |
| `aime` | `aime` | `aime` | 20 / 10 / 30 |
| `alfworld` | `alfworld` | `alfworld` | 200 / 140 / 134 |
| `appworld` | `appworld` | `appworld` | 90 / 57 / 168 |
| `bbeh` | `bbeh` | `bbeh` | 345 / 115 / 460 |
| `bfcl` | `bfcl` | `bfcl` | 80 / 40 / 80 |
| `browsecomp` | `browsecomp` | `browsecomp` | 100 / 50 / 150 |
| `deepsearchqa` | `deepsearchqa` | `deepsearchqa` | 600 / 250 / 50 |
| `deepswe` | `deepswe` | `deepswe/v1.1` | 20 / 10 / 30 |
| `harvey_lab` | `harvey_lab` | `harvey_lab/v1.2.0` | 40 / 20 / 60 |
| `hotpotqa` | `hotpotqa` | `hotpotqa` | 150 / 300 / 300 |
| `jobbench` | `jobbench_easy` | `jobbench/easy` | 25 / 13 / 25 |
| `jobbench` | `jobbench_main` | `jobbench/main` | 26 / 13 / 26 |
| `livemathbench` | `livemathbench_202412_cn` | `livemathbench/202412/cn` | 60 / 24 / 35 |
| `livemathbench` | `livemathbench_202412_en` | `livemathbench/202412/en` | 60 / 24 / 35 |
| `livemathbench` | `livemathbench_202505_en` | `livemathbench/202505/en` | 40 / 18 / 40 |
| `math` | `math` | `math` | 500 / 250 / 500 |
| `musique` | `musique` | `musique` | 150 / 150 / 120 |
| `nq` | `nq` | `nq` | 150 / 150 / 300 |
| `officeqa_pro` | `officeqa_pro` | `officeqa_pro` | 53 / 27 / 53 |
| `searchqa` | `searchqa` | `searchqa` | 400 / 200 / 1400 |
| `spreadsheetbench2` | `spreadsheetbench2` | `spreadsheetbench/2` | 120 / 57 / 120 |
| `supergpqa` | `supergpqa` | `supergpqa` | 600 / 400 / 1000 |
| `swe_bench` | `swe_bench` | `swe_bench/verified` | 200 / 100 / 200 |
| `swe_bench_pro` | `swe_bench_pro` | `swe_bench_pro/v2` | 60 / 30 / 60 |
| `tau2` | `tau2_airline` | `tau2/airline` | 20 / 10 / 20 |
| `tau2` | `tau2_retail` | `tau2/retail` | 54 / 20 / 40 |
| `tau2` | `tau2_telecom` | `tau2/telecom` | 54 / 20 / 40 |
| `tau3_banking` | `tau3_banking` | `tau3/banking` | 39 / 19 / 39 |
| `terminal_bench` | `terminal_bench_2_0` | `terminal_bench/2.0` | 44 / 15 / 30 |
| `travelplanner` | `travelplanner` | `travelplanner` | 45 / 90 / 90 |
| `triviaqa` | `triviaqa` | `triviaqa` | 150 / 150 / 300 |
| `twowiki_multihopqa` | `twowiki_multihopqa` | `twowiki_multihopqa` | 150 / 300 / 300 |
| `widesearch` | `widesearch` | `widesearch` | 40 / 20 / 60 |
| `workbench` | `workbench` | `workbench` | 276 / 138 / 276 |

## 版本与评分边界

- **Terminal-Bench**：此 HF 包是 2.0，配置 `version: "2.0"`。2.1 继续使用现有原生入口。
- **τ²**：三个 config 分别对应 airline、retail、telecom；框架补全匹配的 `domain` 和 `task_split: base`，显式冲突会报错。原始 `split_tasks.json` 不改写，按发布的 split IDs 选择角色。仍需固定 tau2 v1.0.1 SDK、独立用户模拟器模型，任务需要时配置 Judge。
- **JobBench**：main/easy 分别对应 `collection`，不作为一份 `all` 数据混合。预渲染原生任务已带执行资源和独立 verifier；另存的 evaluator/source 归档用于保留来源。
- **LiveMathBench**：config 明确版本与语言，并补全原生数据子集。202412 中英对应题的角色保持发布约定；202505 保留 HF 包明确补充的 `question_type`，不把科目 `type` 当作题型。重复采样和独立 Judge 配置仍由现有 Adapter 处理。
- **AIME**：2025 的 20/10 题用于 train/dev，2026 的 30 题用于 test。各题保留年份和整数评分；请移除单一 `year` 和外部演化年份配置。
- **NQ / TriviaQA**：这批包是历史 MRQA v2 上下文与答案列表，使用 `text_em_f1`，与原生 NQ / rc.wikipedia 协议区分。
- **SearchQA**：保留原 SkillOpt 的 2,000 题子集与 400/200/1400 角色，不代表完整 SearchQA。
- **ALFWorld**：只下载约 8 MB 的精选原生 JSON + TW-PDDL 游戏包，不下载原始 ZIP 或视觉权重。仍需 Linux/WSL/macOS、Python 3.11/3.12 与对应运行依赖。
- **Harvey LAB**：当前包是 120 个自包含法律任务及其文档、原生 rubrics；不是完整 2,010 题镜像。独立双 Judge 配置保持现有约定。
- **SpreadsheetBench2**：只含 Debugging、Financial_Model、Template；`category: all` 不包含 Visualization。需 Docker + Harbor。
- **SWE-bench Pro / DeepSWE**：使用所选原生任务目录，保留 Harbor 的原生网络与 verifier 约束；SWE-bench Pro 此配置为 `subset: all`。

其他 benchmark 的运行条件和独立模型配置沿用[配置索引](benchmark-quickstart.md)。例如 WideSearch 仍需搜索/抓取服务和 Judge，TravelPlanner 仍需独立 postprocess。

HLE 使用官方 `cais/hle`，固定 revision 为 `5a81a4c7271a2a2a312b9a690f0c2fde837e4c29`。官方发布的是混合图文 test 集；加载器读取必要文本列，用 `image` 字段排除带图题，不加载或解码 `image_preview`、`rationale_image` 列。进入实验的题目只有文本，参考答案只交给宿主侧独立 Judge。首次需在官方 HF 页面获得访问权限并登录。示例 [hle_opro.yaml](../examples/hle_opro.yaml) 的 train/dev/test 是过滤后自定义的实验划分，不是官方隐藏测试协议；无需添加本仓库的 `dataset` 配置。

## 原生资源与缓存

仓库需要 HF 访问权限，先在运行机器执行 `hf auth login`，或配置 `HF_TOKEN`。一键启动器改变缓存位置时会保留原登录文件的路径，不读取或复制 token 到项目配置。

数据和原生资源在实验机器下载、校验并解包到缓存，不进入 harness Snapshot。只下载执行所需资源；归档在 HF 的完整上游历史、参考材料不会全部下载。OfficeQA-Pro 移除原 `corpus_path`，TravelPlanner 移除原 `database_path`，WideSearch 移除原 `gold_path`，由对应 HF 原生资源包提供。

**HF 任务包不包含 Docker 镜像层、模型服务或所有构建时依赖。**Harbor 与独立 Docker Adapter 仍需可用的 Linux daemon；SDK、本地模拟器和外部服务仍按各 benchmark 的约定准备。数据加载成功不代表真实执行或评分已经验证。

## 使用示例

复制 [hf_prepared_opro.yaml](../examples/hf_prepared_opro.yaml) 为同目录下的 `hf_prepared_opro.local.yaml`，分别填写 Target 与 Worker 的模型、凭据、端点后运行：

```bash
python scripts/run_experiment.py --config examples/hf_prepared_opro.local.yaml --plan
python scripts/run_experiment.py --config examples/hf_prepared_opro.local.yaml --check-only
python scripts/run_experiment.py --config examples/hf_prepared_opro.local.yaml
```

ALFWorld 的完整数据配置见 [hf_prepared_alfworld.yaml](../examples/hf_prepared_alfworld.yaml)。已有安装环境也可以使用 `flashrsi run --config ...` 和 `flashrsi evaluate --config ...`；它们共用数据加载路径，但普通 CLI 不替用户安装运行依赖。

流程沿用 runner：加载 HF 数据 → 绑定 Benchmark Adapter → 按算法配置演化 harness → 对最终 Snapshot 运行 test。不同算法的选优规则由算法实现决定。首次可以用小任务量验证流程，再扩大实验规模。`--check-only` 不调用模型，不能替代真实环境 rollout。

## 旧配置

固定旧 revision `1b976eec446eec4cb5354c07bc81b27f92b69c49` 或 `f950bd8dc40a9b498d9b1edbf5ca71720a38cd3d` 的旧 `_experiment_v1` 配置继续按对应的旧路径读取，不自动升级。更新到本页 revision 时，建议同时使用表中的新 config 名；已支持的旧别名也可映射到新 catalog。现有实验记录与 Snapshot 不改写。
