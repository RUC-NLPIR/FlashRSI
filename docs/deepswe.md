# DeepSWE 接口

注册名为 `deepswe`，对应 Datacurve DeepSWE v1.1，主指标为 `reward`。
固定[官方仓库](https://github.com/datacurve-ai/deep-swe/tree/0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea)
commit `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`。

本轮按用户要求只接接口：未克隆 benchmark、未下载数据集或镜像、未调用模型、未运行实验。
只查询官方文档、版本及任务格式，使用手写合成任务做离线接口测试。

## 配置

完整配置见 [OPRO 示例](../examples/deepswe_opro.yaml)。

```yaml
benchmark:
  name: deepswe
  # 可选：已有原生仓库根目录、tasks/，或单个任务目录。
  # data_path: ./data/deep-swe
  seed: 42
  split_counts: {train: 1, dev: 1, test: 1}
```

实例化和查看依赖计划不会获取任务。将来调用 `load()` 或真正启动实验时，未指定 `data_path`
才会下载固定 Git revision 下的 `tasks/`；本地路径按现有配置规则相对 YAML 文件解析。
默认 `split: auto` 将公开集合保留为 test；演化需要显式设置同源互斥的实验划分。
不支持把原生任务当成普通 QA JSON 输入。

一键脚本识别 `deepswe` 并选择已有 `harbor` extra，执行环境要求 Python ≥3.12、
Docker Linux daemon 和 Compose；自动获取数据需要 Git。`--plan` 只显示规划，
`--check-only` 会加载数据，因此本轮不运行后者。Windows 直接使用 SDK/CLI 时启用
`PYTHONUTF8=1`；一键脚本已自动设置。

## 执行与评分映射

- 使用当前 Harbor 0.23.0 桥接 MiniAgent / Claude Code；未安装或切换到官方榜单使用的 Pier。
- 保留原始 instruction、镜像、资源定义、artifacts、`verifier.collect` 和 verifier 脚本。
  Agent 按原始任务要求提交代码；适配器不自动提交。官方 hook 从已提交的 HEAD 提取补丁，
  Harbor 在独立 verifier 环境应用补丁并评分。
- 仅接受单阶段 Linux 任务，要求 v1.1 的独立 verifier、collect hook，以及 Agent/verifier
  原生 `network_mode: no-network`。不兼容的任务明确报错。
- 必须配置 `agent.llm.base_url`。由它和可选的 `side_base_url` 提取主机名，传入 Harbor
  的 **Agent 阶段**网络白名单；不继承 Worker 连接，不开放任意网络，verifier 仍禁网。
  每次执行读取该次固定配置，后续调整模型连接会更新白名单。自定义网关需可从容器访问；
  代理或额外重定向域名没有在本轮验证。
- 评分只读取宿主追加且与加载 Task/checksum 对齐的 `HarborVerifier` 事件，映射原生
  `rewards.reward`；其他原生分项保留在该事件。执行失败计零，不采信 Agent 自报分数。

这是接入现有 Agent 的评测接口，不声称复现官方榜单的模型、预算或 harness 配置。
原生任务、镜像和真实容器行为尚未验证；离线测试仅确认格式解析、划分、网络策略参数传递和结果映射。

验证记录：本地记录 `validation-deepswe-interface-20261028.json`。
