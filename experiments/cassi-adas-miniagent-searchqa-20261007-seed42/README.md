# adas + miniagent + searchqa

Test EM：76.71% → 84.86%；F1：86.63% → 90.97%。

- `logs.tar.gz`：完整实验记录，含配置、所有候选Snapshot、逐题轨迹、日志、固定数据划分及支持源码。
- `selected-snapshot.json`：最终实际选中的Snapshot，可用于核对候选内容及准备迁移实验。
- `result.json`：正式结果。
- `verification.json`：归档哈希、逐文件校验、test分数重新计算及逐题顺序核验。
- `file-manifest.json`：包内文件清单。

存在扩展、恢复或重新选优时，对应历史记录保留在归档的 `history/` 下。源码副本反映归档时的项目状态；候选内容以Snapshot为准。凭据已脱敏，依赖环境未打包。
