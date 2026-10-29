# Codex Snapshot 组件拆分：2026-10-29

本次 follow-up 把原来整个 `python_core/**` 都标成 `code` 的规则拆开，保留
Snapshot 的公共接口和完整执行闭包。变更只影响 `checkout()`、`commit()` 和算法
scope 的编辑面；运行时仍使用 `Snapshot._export(full=True)` 导出全部文件，模块之间
的 import 依赖不会因为 scope 而丢失。

## 当前分类

默认 Snapshot：`37eef409…`，141 个文件，内容 **1,835,309 bytes**。
`Snapshot.save()` 的 JSON 为 **2,466,080 bytes**，gzip 后为 **739,602 bytes**。
分类及内容大小如下：

| component | 文件数 | 内容字节 | 现在负责 |
| --- | ---: | ---: | --- |
| `code` | 11 | 187,873 | 主循环、请求、上下文、历史、压缩、模型协议 |
| `tool` | 26 | 698,148 | tools、shell、patch、Code Mode、MCP、搜索及工具资源 |
| `agent` | 6 | 89,753 | v1/v2 子代理与角色/模板资源 |
| `hook` | 11 | 29,812 | hook 运行时和 schema |
| `memory` | 2 | 31,743 | memory 运行时和初始资源 |
| `plugin` | 2 | 7,506 | plugin 运行时和 plugin 提示 |
| `prompt` | 3 | 21,728 | Codex 基础/压缩提示模板 |
| `skill` | 59 | 406,050 | 内置 system skills 和技能提示 |
| `config` | 21 | 362,696 | 配置、权限、模型目录、来源和许可证元数据 |

顶层 `AGENTS.md`、`skills/**`、`agents/**`、`hooks/**`、`servers/**`、
`plugins/cache/**`、`memories/**` 和 `config.toml` 继续使用原来的分类。

## Scope 行为

原有算法可以继续使用：OPRO/GEPA/ACE/EvoPrompt 的 `prompt` scope 现在还可以编辑
Codex 内置提示模板，SkillOpt/EvoHarness 的 `skill` scope 还可以编辑内置 system skills，
而 `code` scope 只打开主循环和协议上下文。需要演化工具、子代理、hook、memory 或
plugin 时，可以选择对应 component；`{"*": "rw"}` 保留原来的全量编辑行为。

`models.json` 仍整体归 `config`，因为它同时包含模型能力、预算、工具配置和 system
instructions；`tools.py` 仍整体归 `tool`，因为工具描述、schema 构造和执行逻辑混在一个
模块里。这两处若要继续细分，需要先提取文件并保持加载行为，不能只改 YAML。

组件规则参与 Snapshot ID，所以重新分类会产生新的根版本；旧分类规则生成的候选不能
直接 `update()` 到新基线，必须从新基线重新 checkout/commit。已验证完整执行仍读取所有
文件，scope checkout 只暴露选中组件，选中资源可提交，未选中的核心改动会被拒绝。

## 验证

- 组件分类、scope checkout/commit、隐藏核心拒绝：6 passed。
- Codex source、adapter、core parity/extensions：33 passed。
- 资源、工具、循环和子代理实际执行回归：74 passed。
- 新分类 wheel 的独立 macOS 安装验收：10 个 localhost/实际工具检查通过；
  wheel 为 `811,501 bytes`，SHA-256 为
  `0cdec62b89e8929557423f29f68ff19ef2e19bdb8a12071921fdfed8844e8f88`。
- 141 个文件均恰好匹配一个组件规则；没有修改 `mvp_doc.md`。

这次拆分没有声称模块之间已经没有依赖。此前 Linux/Docker 的 120 项证据对应拆分前的
wheel；当前新分类 wheel 已完成 macOS 安装验收，若要把它作为 Linux/Docker 发布基线，
仍需用这个新 hash 重跑对应平台。后续若继续拆 `models.json` 或 `tools.py`，需要单独
提取文件并重新做行为对照。
