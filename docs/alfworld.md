# ALFWorld 纯文本接入

注册名 `alfworld`，领域为 Interactive Planning。首版提供原生文本环境接口；不含
视觉 THOR、混合环境或 BUTLER 训练。上游为 [ALFWorld](https://github.com/alfworld/alfworld)，
固定运行依赖 `alfworld==0.4.2`、`textworld[pddl]==1.7.0`。

## 数据与环境

- Linux/WSL/macOS、Python 3.11 或 3.12；Windows 原生启动明确报错。
- 使用原生 Python 文本环境，无需 Docker、Harbor、GPU 或独立 Judge。
  TextWorld 编译依赖按[官方说明](https://github.com/microsoft/TextWorld#installation)准备。
- `benchmark.data_path` 必填，指向原始 `json_2.1.1` 或其父目录。
  YAML 路径相对配置文件，CLI 路径相对当前目录。不自动下载任何任务或视觉模型。
- 数据来自官方 release 的 JSON 和 TW-PDDL 游戏包（官方下载脚本中的
  `json_2.1.1_json.zip` 与 `json_2.1.3_tw-pddl.zip`），按其原始路径合并。
  每道任务目录包含 `traj_data.json` 和自包含的 `game.tw-pddl`。
  本适配直接加载现有游戏，不调用生成脚本，不要求视觉检测权重。
  官方 `alfworld-download` 默认还下载 MaskRCNN；本接口不自动调用它。

默认采用框架角色映射：原生 `train → train`、`valid_seen → dev`、
`valid_unseen → test`。后两者仍是官方的 seen/unseen 验证集，并非声称拥有官方隐藏测试集。
`limit` 在保持来源归属的前提下确定性取样；显式 `split_counts` / `split` 会重新划分，
应作为自定义实验协议报告。允许只提供部分原生划分，缺失角色保持为空。

按 `AlfredTWEnv` 的规则排除 movable/Sliced、缺失游戏和未标记可解的游戏。
默认支持全部六类；`task_types` 可指定以下名称的非空子集：

```yaml
task_types:
  - pick_and_place_simple
  - look_at_obj_in_light
  - pick_clean_then_place_in_recep
  - pick_heat_then_place_in_recep
  - pick_cool_then_place_in_recep
  - pick_two_obj_and_place
```

## 执行与评分

每次 rollout 创建独立子进程，通过原生 `textworld.gym.register_game` 与
`AlfredDemangler(shuffle=False)` 加载指定游戏；沿用上游的观察、命令解释及状态转移。
Agent 在自己的工作目录中通过 shell 客户端提交动作。支持 MiniAgent 与启用 Bash
的 Claude Code；不改动两者的原生 system prompt。该本机会话桥接沿用 WorkBench
的受信任本机执行模型，不提供容器级隔离。

- `max_steps` 默认 50，是本适配的可配置预算，不宣称复现特定论文设置。
  环境动作预算与 `agent.max_turns`、`agent.timeout` 分别生效。
- `seed` 固定环境随机源与取样；关闭 domain randomization。
- `admissible_commands: false` 默认只给观察；设为 true 时额外返回原生合法动作列表。
  此选项改变可见信息，记录在 metadata 与评分事件中，比较成绩时需保持一致。
- 不启用 expert wrapper；不暴露专家计划、完整 facts、轨迹注释或私有评分接口。
- 主指标 `success` 由宿主侧 `infos["won"]` 映射为 0/1，再由框架求均值。
  `done`、累计奖励或模型文字声明均不能替代成功判定。达到步数上限后停止执行动作。
- 原生执行异常记录为 error，不能伪装成正常的任务失败；Agent 执行错误按框架惯例计零。
  游戏内容校验和写入任务，执行前核验并复制固定内容，结束后释放进程及临时目录。

## 使用与验证范围

示例：[alfworld_opro.yaml](../examples/alfworld_opro.yaml)。先填模型与本地数据路径：

```bash
python scripts/run_experiment.py --config examples/alfworld_opro.yaml --plan
python scripts/run_experiment.py --config examples/alfworld_opro.yaml --check-only
python scripts/run_experiment.py --config examples/alfworld_opro.yaml
```

`--plan` 只输出依赖计划。`--check-only` 安装选定依赖并检查本地任务与配置，不调用模型，
也不能替代真实环境 rollout。缺少数据时明确报错。

本轮仅使用合成游戏记录和模拟环境验证加载、划分、交互协议、失败传播、成功判定、
HTTP 客户端与进程清理。未下载官方任务、未安装/运行 ALFWorld 模拟器、未调用模型，
不计入真实算法 × Target × Benchmark smoke 通过数。
