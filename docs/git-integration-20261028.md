# 正式 Git 工作区整合记录

基于 main `a31ec3c44d9240640d7f18a225d69f297be32572` 创建
`integration/local-benchmarks` 分支，迁入此前已整合的本地源码、文档、示例和验证记录。
保留 main 新增的封面更新，并对两份 README 做三方合并。原来的非 Git 源码目录未修改。

当前注册 30 个 benchmark、12 个算法和 3 个 Target Agent。57 个 main 文件在本地及原
`integration/flashrsi-smoke` 中都已删除，因此沿用既有删除记录；不把它们作为缺失文件恢复。
原生 Codex 的 3,470 个 runtime / bridge 文件保持上游内容和 Git 模式，包括 7 个可执行文件。
`.gitattributes` 保留 main 的实验 LFS 规则，并防止原生源码发生换行转换。

## 数据与仓库体积

仓库采用 `blob:none` 部分克隆、两层浅历史以及 cone 模式稀疏检出；展开目录仅为
`flashrsi`、`docs`、`examples`、`scripts`、`tests`、`assets` 和根文件。
`experiments/` 的 1,576 个文件树条目保持与 main 一致，未作为新增、修改或删除提交。

检查旧索引时，Git 曾自动补取一个 44,912,943 字节的 pack，包含 1,125 个实验专属普通
文件对象。该 pack 已移出正式仓库，保存在原目录的 `.cache/main-git-integration/excluded-pack/`。
最终对象库中不存在这 1,125 个实验专属 blob；工作区没有 `experiments/` 目录，未下载 LFS 大文件。
这不能表述为整个操作过程中从未下载过实验普通文件。

检查与提交阶段限制 Git 网络协议，避免再次惰性拉取。后续不要执行
`git sparse-checkout disable` 或展开实验目录；这些操作可能请求被省略的文件。
正常修改已展开的代码后可以提交、推送分支，远端原有实验目录仍被提交树保留。

## 验证与边界

- 在新工作区运行全量测试：868 passed、140 skipped、3 subtests passed。
- 跳过项包括未安装的原生可选环境和平台条件，不代表真实 benchmark 或 Codex Rust 构建已验证。
- 配置及原生资源的既有 wheel 验证见 [main 同步记录](main-sync-20261028.md)。
- 迁移前扫描公开文件，未发现与本地配置中的已知凭据相同的内容；不等同于完整安全审计。
- 保留第三方官方源码和许可证原有空白，不为 `git diff --check` 修改其原始内容。

本轮只创建本地提交，未推送远端或合并远端 main。
