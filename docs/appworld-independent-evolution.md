# AppWorld 独立演化数据

`benchmark.evolution_test_set` 显式选择主实验未使用的原生公开评估池：
主 `test_set: test_normal` 时可选择 `test_challenge`，反向亦可。
这属于 `external_evolution / published_evaluation`，不称官方训练集。
主实验已经使用的测试池不能再次作为演化来源。

加载器对主实验完整 train、dev、所选 test 池与完整外部池检查任务 ID、
scenario ID 和规范化原始 instruction 的重合，然后才按 seed 和
`evolution_limit` 取演化样本。只替换实验 train，原 dev/test 保持不变。
不删除重合记录；任一重合均拒绝整项配置。

任务仍使用原生目录、DB、ground_truth 和宿主 AppWorldVerifier；
pool_checksum 绑定完整外部池的任务及原生文件树校验和。来源中保留
native_split、published_evaluation 角色、池大小与校验和。

示例见 `examples/modular_rsi_appworld.yaml`。通过一键启动器运行时，默认自动
下载并缓存完整原生数据、准备运行镜像。复用已有数据时，显式设置
`benchmark.data_path` 为原生 `data/` 目录；直接使用 `flashrsi` CLI 时也需提供该路径。
离线来源/测试或入口准备成功不代表算法×Target 的真实实验通过。

## 历史 Snapshot 的连接兼容

历史 AppWorld 工具可能读取任务工作目录下的 `appworld-connection.json`，
并向其中 `socket` 指定的 Unix socket 发送逐行 JSON 的 `execute` 请求。
当前 AppWorld 集成在每个 Linux 任务容器内自动提供此兼容端点，将请求转发到
该题的原生 HTTP world；不需要改写历史 MiniAgent 工具或 Claude Code MCP 脚本。
新 shell 客户端和旧连接访问的是同一个持久任务会话。

连接文件和 socket 属于任务运行环境，不进入 Snapshot。端点只接受 `execute`
和非空 Python `code`，不提供评分、重置或生命周期控制。状态修改请求不会自动重试；
执行结束、异常或取消时清理连接，并等待已发出的请求结束后再交还评分流程。
已有同名任务文件或符号链接不会被覆盖，初始化会明确失败。

此兼容只恢复 AppWorld 的历史传输接口，不把 AppWorld API 转换成其他 benchmark
的工具，也不证明任一历史策略能完成全部任务。加载旧 JSON 仍需匹配的原始 root；
发布整理后的源码目录和重新捕获的 Snapshot 应成对使用，不能混用版本身份。
