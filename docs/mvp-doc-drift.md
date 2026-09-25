# mvp_doc 与实现的接口差异清单

对应 [migration-plan.md](migration-plan.md) 步骤 0 中「列出设计文档和实现的接口差异，由开发者
决定规范更新」。基准：`mvp_doc.md`（320 行）对 `158074e`。本文只列差异和建议，不修改 mvp_doc。

**总体判断**：36 项差异中 32 项是实现比文档更成熟，建议回写文档；4 项需要决策（§H）。
没有发现实现违反 mvp_doc 意图的地方——分歧都来自文档停在第一版草稿。更强的说法是：多数分歧
里，实现比文档**更好地达成了 mvp_doc 自己声明的目标**（§1 的目标 1「算法开发者避免学太多抽象」
和目标 3「benchmark/harness 开发者尽可能简单」），理由逐条记在下面，不是「已经这么写了」。

标记：**文档** = 建议回写 mvp_doc ｜ **实现** = 建议改代码 ｜ **待定** = 需要你选一边

---

## A. Agent 接口

八项已逐条核对，结论：**七项按实现回写，一项（A3）拆成两半，其中 `observation_scope` 建议删。**

| # | 契约 | mvp_doc | 实现 | 建议 |
|---|---|---|---|---|
| A1 | `check_out()` / `commit()` 的归属 | L126-130 在 `Agent` 上；L172-186 整段按 Agent 叙述 | 在 `Snapshot` 上（[snapshot.py:216](../flashrsi/core/snapshot.py#L216)、[:270](../flashrsi/core/snapshot.py#L270)）；[test_agent.py:75](../tests/test_agent.py#L75) 断言 Agent **没有**这两个方法 | **文档**，理由见 A1 详述 |
| A2 | `edit()` 返回值 | L145-147 与 L158 表格明确「返回 `None`」 | 返回 `str`（[agent.py:157](../flashrsi/core/agent.py#L157)） | **文档**，理由见 A2 详述 |
| A3 | `set_scope` 签名与 `r` 级别 | L124 `set_scope(components: set[str])`；L153 表格「选择允许修改的 component」 | `set_scope(scope: Mapping[str, str])`，`rw`/`r`/`none` 三级（[agent.py:116](../flashrsi/core/agent.py#L116)） | 签名 **文档**；`r` 级别 **待定**，见 H4 |
| A4 | 谁调 `set_scope` | L240 算法自己调 `self.target.set_scope({"skill"})` | 算法只声明 `evolve_scope`/`observation_scope`，基类代调（[algorithm.py:55](../flashrsi/core/algorithm.py#L55)）；六个算法无一自己调用 | **文档**（声明式写法正是目标 1） |
| A5 | `run()` 签名 | L139-141 `run(task: Task, snapshot: Snapshot)` | `run(prompt: str, working_dir: Path \| None)`（[agent.py:132](../flashrsi/core/agent.py#L132)）；版本由 `rollout` 固定在执行上下文里 | **文档**，附带说明见 A5 详述 |
| A6 | 后端实现哪些方法 | L138「后端按支持的能力实现」下列 `run`/`ask`/`edit` 三个 | 后端只实现 `_run` 一个钩子；`run`/`ask`/`edit`/`rollout` 全是基类的 | **文档**（比文档自己的目标 3 更彻底） |
| A7 | `component_rules` | L118 类属性 `Mapping[str, tuple[str, ...]]` | 从 `components.yaml` 读、由 Snapshot 持有、Agent 转发的只读属性（[agent.py:100](../flashrsi/core/agent.py#L100)） | **文档**（结构上保证 worker 改不了规则，对应 L160「分类规则不能由 worker 修改」） |
| A8 | 初始 Snapshot 从哪来 | L152 表格「Agent 根据 **seed** 和自身分类规则建立」 | 从适配器所在目录 + `components.yaml` 自动 capture（[agent.py:270](../flashrsi/core/agent.py#L270)）；无 `seed` 概念，[test_agent.py:75](../tests/test_agent.py#L75) 断言没有 | **文档**：接入方零代码；且 "seed" 与 `benchmark.seed`、`algorithm.seed` 撞名，建议文档里换词 |
| A9 | `snapshot` 属性 | L115 普通字段 | 属性；纯 LLM Worker 无版本文件时访问会 raise（[agent.py:92](../flashrsi/core/agent.py#L92)） | **文档**（L114 注释已是对的，签名没跟上） |

### A1 详述：基线放在 Snapshot 上避免了一个文档写法做不到的事

mvp_doc L154 要求 `check_out()`「在框架内部记住 checkout 时的基线」——这是隐藏状态，且**每个
Agent 只能记住一个**。但实际用法里同时存在多个基线：

- [test_snapshot_files.py:64](../tests/test_snapshot_files.py#L64) 覆盖同一 snapshot 并发 checkout 两次；
- GEPA 和 EvoPrompt 是种群算法，手上同时握着多个候选版本（[gepa/_population.py](../flashrsi/algorithms/gepa/_population.py)）。

两个 checkout 同时存在时，Agent 记住的「那一个」基线就是错的。放在 Snapshot 上则基线天然显式：

```python
with current.check_out(working_dir=working) as directory:   # 基线就是 current
    reply = await self.worker.edit(directory, prompt)
    candidate = current.commit(directory)                   # 从哪个版本分叉，读一眼就知道
```

比 L178 的 `self.target.check_out()` → `self.target.commit(workdir)` 更能回答「这个候选是谁的
后代」。附带好处：`check_out(working_dir=)` 让临时目录落在实验目录的 `working/` 下，正好满足
AGENTS.md 的实验布局要求。

### A2 详述：返回 `str` 保住了文档想要的性质，还多给了一个机制

文档要 `None` 的意图是「不提交 target 的 Snapshot」（L158）——这一点实现完全守着，`edit()` 只
改目录，提交仍是调用方的事。而返回值让编辑变得可核对：[ahe:125-143](../flashrsi/algorithms/ahe/__init__.py#L125-L143)
用返回的文本解析 `<MANIFEST>`，再用 `changed_paths()` 把 Agent 的自述和真实改动对账。**「让
Agent 对自己的编辑负责」这个机制，返回 `None` 就不存在了。**

### A5 详述：一个附带的不对称，建议在文档里写明

`run` 只收到 `task.question`，Task 本身由 `rollout` 在 [agent.py:231](../flashrsi/core/agent.py#L231)
事后 `replace` 贴回去。于是：env 任务的后端能看到完整 Task（走 `env_runner`），**非 env 任务的
后端只看到一个字符串，读不到 `task.metadata`**。

今天不影响任何组件（QA benchmark 把 context 都烘进 prompt 了），但这是真实的能力边界，建议
写进文档，免得后来的接入者以为 `_run` 里能读 metadata。

## B. Snapshot

| # | 契约 | mvp_doc | 实现 | 建议 |
|---|---|---|---|---|
| B1 | `format_version` | L97 `= 1` | `= 2`；v1 明确拒绝加载并说明原因「no component rules; recapture the source」（[snapshot.py:389](../flashrsi/core/snapshot.py#L389)） | **文档**（v1 从未发布过数据，无需兼容） |
| B2 | 字段组成 | L89-97 七个字段 | 多 `component_rules`（**进哈希**，[snapshot.py:93](../flashrsi/core/snapshot.py#L93)）和 `_scope`（私有、`compare=False`、不参与身份） | **文档**，理由见 B2 详述 |
| B3 | 公共方法 | L99-102 只有 `save`/`load` | 另有 `check_out`/`commit`（见 A1）、`from_directory`、`changed_paths`（[ahe:143](../flashrsi/algorithms/ahe/__init__.py#L143)），模块函数 `discard_runtime_files`（[ahe:134](../flashrsi/algorithms/ahe/__init__.py#L134)） | **文档**；`from_directory` 见 H2 |

### B2 详述：`component_rules` 进哈希是对的，值得在文档里说明

规则进哈希意味着「同样的文件 + 不同的分类规则」是两个不同版本。这正是 mvp_doc L107「加载时检查
Agent 类型、格式和版本来源」想要的性质：改了 `components.yaml` 之后，旧候选无法再被 `update`
进来（[snapshot.py:338](../flashrsi/core/snapshot.py#L338) 检查 rules 相等）。而 `_scope` 反过来
**不能**进哈希——scope 是算法的临时视图，同一个版本在不同 scope 下必须仍是同一个版本，所以它
标了 `compare=False`。这一对取舍是 Snapshot 设计的核心，文档里现在一句都没有。

## C. Benchmark

| # | 契约 | mvp_doc | 实现 | 建议 |
|---|---|---|---|---|
| C1 | `primary_metric` | 未出现在类定义中（只在 L242 算法示例里被读） | 类属性，子类必须声明（`exact_match` / `reward`） | **文档**，另见 H3 |
| C2 | `train`/`dev`/`test` | 未出现在类定义中（L211、L243 被读） | 基类属性，`load()` 未调用时 raise（[benchmark.py:75](../flashrsi/core/benchmark.py#L75)） | **文档**（含「先 load 再取 split」的时序） |
| C3 | 构造签名 | 无 `__init__` | 基类 `__init__(self)`，但四个子类全是 `__init__(self, config)` | **实现**，见 H1 |
| C4 | `Benchmark.load_from_config(config)` | L209 | 不存在；runner 直接 `benchmark_type(config.benchmark)`（[runner.py:56](../flashrsi/runner.py#L56)） | **文档**（删；与 C3 一并解决） |
| C5 | `grade()` 的前置条件 | L75-76 只说填 metrics | 要求 `trajectory.task is not None`，否则报错要求改用 `rollout`（[_qa.py:56](../flashrsi/benchmarks/_qa.py#L56)） | **文档**（与 E1 相关：`ask()` 的轨迹不能送去 grade） |

## D. Algorithm

| # | 契约 | mvp_doc | 实现 | 建议 |
|---|---|---|---|---|
| D1 | 两份互斥草稿并存 | L203-228 `class Algorithms`（类名多了 s、`self.worker = Agent(config)` 自己造协作者）与 L229-279 并存 | 按后者：runner 注入三个协作者（[algorithm.py:39-41](../flashrsi/core/algorithm.py#L39-L41)） | **文档**（删前一段，它与实现完全相反） |
| D2 | `evolve()` 返回类型 | L210、L278 `-> Agent`；L239 `-> Snapshot`（文档自相矛盾） | 统一 `-> Snapshot`，六个算法一致；runner 直接拿它评 test（[runner.py:76-77](../flashrsi/runner.py#L76-L77)） | **文档**（统一为 Snapshot） |
| D3 | 算法作者的实际契约 | 完全缺失 | 声明：`evolve_scope`/`observation_scope`/`_defaults`/`_ranges`；钩子：`_check()`/`_normalize()`；基类动作：`_evaluate`/`_candidate`/`_read_text`/`_record`/`_promote`/`_instruction_path`/`_evidence`/`_trajectory_evidence` | **文档**（最大一块，见下） |
| D4 | `Results` 类型 | 不存在 | `_evaluate()` 的返回值，带 `.score`/`.per_task`（[trajectory.py:63](../flashrsi/core/trajectory.py#L63)） | **文档** |
| D5 | 算法是否读 `primary_metric` | — | AGENTS.md 说「算法不碰 `primary_metric`」，但 [skillopt:117](../flashrsi/algorithms/skillopt/__init__.py#L117) 和 [ace:148](../flashrsi/algorithms/ace/__init__.py#L148) 仍在读它判断单条轨迹成败 | **待定**，见 H3 |

D3 是心智负担最大的一项：算法作者要知道的东西，`mvp_doc` 一个都没写，实际契约只散落在
`AGENTS.md`「算法实现约定」和 84KB 的 README 里。**这直接违背 §1 目标 1**（「避免学习太多复杂
抽象和名词概念」）——规范本身没给这张表，作者只能靠读现有算法反推。建议至少补一张「基类提供的
动作」表。

## E. Trajectory / Task

| # | 契约 | mvp_doc | 实现 | 建议 |
|---|---|---|---|---|
| E1 | `task` 是否必填 | L192 `task: Task` 必填 | `task: Task \| None = None`——`ask()`/`edit()` 的轨迹确实没有 Task（[llm.py:58](../flashrsi/agents/llm.py#L58)、[:64](../flashrsi/agents/llm.py#L64)） | **文档**（Worker 问答不属于任何任务，这是实质差异不是笔误；与 C5 配套） |
| E2 | `metrics` 默认值 | L196 `= ()`，但类型标的是 `Mapping` | `field(default_factory=dict)` | **文档**（文档处是笔误） |
| E3 | 可变性 | L191 普通类 | `frozen=True, slots=True`，三个映射字段在 `__post_init__` 转 `MappingProxyType` | **文档**（与 L106「文件映射与文件条目均不可变」是同一类约定，文档只对 Snapshot 说了） |
| E4 | `Task` | L58-63 | 一致 ✓（字段、默认值、语义都对得上） | — |

## F. 文件清单（§4）与 MVP 计划（§6）

| # | 差异 | 建议 |
|---|---|---|
| F1 | 实际多出：`_records.py`、`_run_summary.py`、`algorithms/_replies.py`、`benchmarks/{_data,_qa,_archive,metrics}.py`、`integrations/{tau2,_container}.py`、`agents/llm.py` | **文档** |
| F2 | 算法多出 5 个（OPRO/GEPA/EvoPrompt/ACE/AHE），benchmark 多出 3 个（HotpotQA/Tau3Banking/TerminalBench） | **文档** |
| F3 | §6 的 0-7 步实现都在，只有第 7 步的真实容器验收未完成（本机无 Docker/Podman） | **文档**（标注状态，不标成未实现） |

---

## H. 需要决策的四项

### H1. `Benchmark` 基类补 `__init__(self, config)`

现在基类是 `__init__(self)`，而 `config` 契约只活在子类里，同一段样板抄了三份：

```python
# _qa.py:30 / terminal_bench:47 / tau3_banking:66 —— 三份逐字相同
super().__init__()
self.config = config["benchmark"] if "benchmark" in config else config
if self.config.get("name", self.name) != self.name:
    raise ValueError(...)
self._tasks_by_id: dict[str, Task] = {}
```

`load()` 里「算 split + 建 `_tasks_by_id` 索引」的四行同样抄了三份。按 AGENTS.md「同一个概念
出现第二遍时提到基类」，这已经是第三遍。

建议：基类接 `config`、做 name 校验、持有 `_tasks_by_id`；子类只留 `_iter_tasks()` 和自己的
额外参数（如 tau3 的 `variant`）。这同时把 C3 的契约缺口补上——benchmark 接入者不必靠读现有
子类来猜构造签名，对应 §1 目标 3。改动范围：`core/benchmark.py` + 三个子类 + `test_benchmark.py`。

### H2. `Snapshot.from_directory` 没有生产调用者

全仓库只有 `tests/test_snapshot_files.py` 在用（10 处），`flashrsi/`、`examples/`、`scripts/`
零调用。Agent 走 `_capture`，算法走 `commit`。

建议：删掉，或在 docstring 里写明它的定位（「curated 目录入口，供外部工具建初始版本」）并在
mvp_doc 挂号。按 AGENTS.md「不保留只能填一个值的配置项和从不被读取的字段」，我倾向删。

### H3. `primary_metric` 的约定不一致（需要你选）

AGENTS.md 写「`_evaluate` 返回的结果自带 `score` 和 `per_task`，所以算法不碰 `primary_metric`」，
但两个算法仍然要读它——因为它们问的是 `Results` 回答不了的问题：**这一条轨迹算不算成功**
（`trajectory.metrics[metric] > success_threshold`）。`Results` 只给聚合分和逐题分，给不了
「给我这条轨迹的主指标」。

两条路：

- **(a) 承认 `primary_metric` 是公共接口**：写进 mvp_doc 的 Benchmark 类定义，并在 AGENTS.md
  那条约定后面补一句「逐条轨迹的成功判定仍读 `primary_metric`」。零代码改动。
- **(b) 让数据自己回答**：`Results` 补一个逐条取主指标的办法，两个算法改为不碰 metric 名。
  更贴合 AGENTS.md 的原意，但给基类加了一条算法作者要记的规则。

我倾向 **(a)**：`primary_metric` 本来就是 Benchmark 的公开属性，算法读它判断成败是正当的；
(b) 为了守住一句约定而扩张基类，方向反了。

### H4. `observation_scope` 和 `r` 权限级别是死的（需要你选）

核对六个算法的实际声明：

| 算法 | `evolve_scope` | `observation_scope` | 仅可读部分 |
|---|---|---|---|
| ace | `{prompt}` | `{prompt}` | 空 |
| ahe | `{*}` | `{}` | 空 |
| gepa | `{prompt}` | `{prompt}` | 空 |
| opro | `{prompt}` | `{prompt}` | 空 |
| evoprompt | `{prompt}` | `{prompt}` | 空 |
| skillopt | `{skill}` | `{skill}` | 空 |

`observation_scope` 一次都没有超出 `evolve_scope`。于是 [algorithm.py:210](../flashrsi/core/algorithm.py#L210)
的 `self._observe | self._evolve` 恒等于 `_evolve`，[snapshot.py:255](../flashrsi/core/snapshot.py#L255)
里 `== "r"` 那行权限降级从未生效。

撞上 AGENTS.md 的两条：「新增一个共享方法等于给所有算法作者加一条要记的规则」＋「不保留只能
填一个值的配置项和从不被读取的字段」。**每个算法作者都得考虑它，而它一次都没起作用。**

两条路：

- **(a) 删**：算法作者少记一条规则，`_read_text` 少一次无意义的并集，`set_scope` 收成 `rw`/`none`
  两级。代价是将来真出现「让 Worker 读它不能改的代码」的算法时要加回来。
- **(b) 留**：那至少要有一个算法真的用上它（例如让 SkillOpt 观察 `prompt` 但只改 `skill`），
  否则它就是没有读者的字段。

我倾向 **(a)**，按你的原则等第二个用例出现再加。注意 `set_scope(Mapping)` 的签名本身建议保留
（见 A3）：它不是算法作者的接口，算法写的是两个 frozenset，Mapping 是基类现造的；`none` 与
`rw` 的区分是真在用的（隐藏组件不进 checkout）。

---

## 建议的执行顺序

1. **先定 H3 和 H4**（两句话决策），它们同时影响 mvp_doc 和 AGENTS.md 的措辞。
2. **回写 mvp_doc**：A/B/C/D/E/F 共 32 项。建议一次改完而不是分批——文档腐烂的成本就在于
   读者不知道哪部分可信。改完后 §5「严格要求」重新生效，后续改动才有基准。
3. **H1**（一个可独立 review 的小步骤），**H2** 和 H4(a) 可以顺带。

第 2 步我可以起草一份 mvp_doc 修订版给你逐段对照，你保留最终措辞权。
