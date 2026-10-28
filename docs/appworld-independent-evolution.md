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

示例见 `examples/modular_rsi_appworld.yaml`。需要已有完整原生数据目录，
环境镜像及连接仍使用现有 AppWorld 配置。离线来源/测试或入口准备成功
不代表算法×Target 的真实实验通过。
