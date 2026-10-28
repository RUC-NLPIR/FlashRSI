# Smoke 验证表

2026-10-28：新增 ALFWorld 纯文本接口（`alfworld`），仅完成合成记录、模拟环境与本地桥接的离线验证；未下载官方任务、未调用模型或运行原生模拟器，不计入真实 smoke 通过数。范围见 [接入说明](alfworld.md)，证据见 [离线验证报告](validation-alfworld-interface-20261028.json)。

## 当前验收结论

2026-10-28 21:00：BFCL新Target16已完成10条原生Target对话，最终Worker真8192输出上限失败，9Worker usage齐；仅Worker输出16384的下一独立配置已登记，Target16/Worker120保持。Browse同源Mini8Target8Worker usage/native/source265齐，真实Worker60上限失败，旧⊘改为failed；新Mini Worker120/1200并显式输出16384（依据同SDK/模型跨BFCL和Travel真实输出截断，不声称Browse旧错为输出上限）。其后CC240/7200保持原Worker60/输出，旧未paid条目已禁派迁移。新两控制均强制22:30CST后不新增付费。总552/26/13/9/24、主472/480、Travel21/24、重点余35，无新增通过或Benchmark。[本轮证据](smoke-budget-recoveries-20261028-2100.json)。

2026-10-28 20:50：Travel同源Modular/CC结束失败，真实00016-worker SDK回复超过8192输出上限；6Target6Worker usage齐、native重算/source266/23files0hits，无result/test，旧⊘更新为实际失败。已唯一登记仅Worker max_tokens16384的新配置，SDK环境映射断言通过，TargetCC40/1200及Worker60/600保持；Mini既有通过不重跑。总552/26/12/10/24、主472/480、Travel21/24、重点余35，无新增通过或Benchmark。[本轮证据](smoke-heartbeat-20261028-2050.json)。

2026-10-28 20:30：新增Travel同源Modular/Mini Worker120/输出16384完整通过：18Target19Worker全部finished/usage齐，native重算/source266/72files0hits/test0有效；旧60轮、8192输出失败保留。CC原预算已由同controller自动真实paid接续。总552/26/11/11/24，主472/480、Travel21/24、重点剩35，无新增Benchmark。Spreadsheet先前失败的同版本原生包在Windows native curl官方archive HTTPS完整下载/原SHA校验成功，现仅做签名APT依赖缓存，不计镜像或模型通过。[本轮证据](smoke-heartbeat-20261028-2030.json)。

2026-10-28 20:10：用户要求继续解决失败。BFCL同源ModMini结束失败：11Target11Worker usage齐/native重算/source230，多个Target真实8轮耗尽导致conversation incomplete，最终Worker60上限；独立Target16/Worker120新配置已登记。Browse同源ModCC结束：11Target9Worker，3Target错误（160轮、4800秒timeout缺usage、test160轮），native重算/source265/41files0hits；缺usage保留未知，改为partial。新队列先原定未付费Mini8，再有界CC240/7200，Worker60保持。无新增通过/Benchmark，总551/26/12/11/24、主472/480、Travel20/24、重点剩36。[失败与恢复证据](smoke-fixes-20261028-2010.json)。

2026-10-28 19:35：无新增通过，总551/25/11/13/24保持。Travel同源ModMini Worker120尝试真实错误为Claude SDK回复超过8192输出上限，落盘13Target finished/13Worker finished及1Worker error均有usage；完整原生失败重算仍待完成，不计通过。按用户输出预算授权仅Worker max_tokens=16384新配置已真实paid（Worker120/1200保持），旧CC无paid已迁入新控制顺序等待；BFCL Mini与Browse CC仍在途，已有错误不能视为通过。[状态证据](smoke-status-20261028-1935.json)。

2026-10-28 18:50：本轮无新增通过或Benchmark。Travel同源Modular/Mini真实Worker60轮失败，9Target/11Worker usage齐、native重算/source266/38files0hits，无result/test；旧独立来源拒绝格更新为实际失败。按已授权只Worker120/1200新配置真实paid，CC原预算迁入未paid等待。BFCL/Mini原生容器安装、pipcheck、导入/工具及公开预检完成后唯一paid；CC安装超时仍0paid。Spreadsheet同版本官方归档包及签名校验成功，原recipe构建触900秒上限，仍无镜像/模型验收。总551/25/11/13/24，主472/480、Travel20/24、重点剩36不变。[本轮证据](smoke-heartbeat-20261028-1850.json)。

2026-10-28 17:30：新增Travel Mini余项2格完整通过（AHE/MiniAgent,EvoHarness/MiniAgent），usage/native约束重算/source266/凭据/真实test齐；原配置仅输出目录变化，评分和任务保持。总551通过，主472/480，Travel累计20/24，重点剩36。

2026-10-28 17:20：新增Travel SDK组4格完整通过（DarwinX/MiniAgent,DarwinX/Claude Code,MetaHarness/Claude Code,EvoHarness/Claude Code），usage/native约束重算/source266/凭据/真实test齐；预算按旧实际错误有界调整，评分和任务保持。总549通过，主472/480，Travel累计18/24，重点剩38。

2026-10-28 开源流程复核（不新增模型通过）：修复 SpreadsheetBench2 独立评分容器缺少 tests/Dockerfile 的确定性启动错误；Harbor原生构建前置回归与相关31项通过。当前源码全量801通过/44跳过/3 subtests通过；新wheel225个包文件逐字节一致，安装后公开CLI以本地模拟API连续跑完两次独立OPRO/Mini/HotpotQA流程（0付费模型），评分、test、轨迹、usage和脱敏齐。完整Spreadsheet容器实跑及交付物长期归档仍未验收；Windows长路径限制已记录。历史总账与当前代码能力分开。[详细复核](validation-open-source-flow-review-20261028.json)。

2026-10-28 DeepSWE 接口更新：新增 `deepswe`（Datacurve v1.1，固定 commit `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`），复用 Harbor 原生 collect 与独立 verifier；注册总数 29。按用户要求只接接口，不下载 benchmark、不拉镜像、不做实验。46 项受影响离线测试、安装 wheel 后的 15 项 DeepSWE 合成任务测试及 lint/格式检查通过。未运行真实 DeepSWE 任务或模型，不计新增 smoke 通过，不更改既有总账。[接口说明](deepswe.md) · [验证报告](validation-deepswe-interface-20261028.json)。

2026-10-28 16:55：新增Travel SDK组3格完整通过（MetaHarness/MiniAgent,AHE/Claude Code,ADAS/Claude Code），usage/native约束重算/source266/凭据/真实test齐；预算按旧实际错误有界调整，评分和任务保持。总545通过，主472/480，Travel累计14/24，重点剩42。

2026-10-28 开发接入更新（不计新增 smoke 通过）：移除当前 CRUXEval-O 适配器、注册和示例，旧记录仅作历史证据；新增 Terminal-Bench `version: "2.1"`（89 个原生任务解析通过，默认仍为 2.0）及 SpreadsheetBench 2 的 Debugging 100 / Financial_Model 100 / Template 97，共 297 题。SpreadsheetBench 2 接到 Harbor 独立评分容器，复制固定版本官方评分与 LibreOffice helper；Visualization 未接入。SWE-bench Verified / Pro 保留已有执行后端并补齐示例。专项 66 项通过，全量 800 项通过、29 项跳过、3 subtests 通过，最新 wheel 核验通过；12 项原生评分控制仅为离线合成表格检查。本轮 Windows 主机无 Docker CLI，未运行容器或模型组合，不提升历史 624 格总账、不把 Terminal 2.0 结果算为 2.1；CRUX 历史总账也不表示当前仍可运行。[接入与验证报告](validation-coding-working-20261028.json) · [运行说明](coding-working-benchmarks.md)。

2026-10-28 16:40：新增Travel SDK组1格完整通过（ADAS/MiniAgent），usage/native约束重算/source266/凭据/真实test齐；预算按旧实际错误有界调整，评分和任务保持。总542通过，主472/480，Travel累计11/24，重点剩45。

2026-10-28 16:25：新增TravelPlanner 4格完整审计通过（SkillOpt/Claude Code,ACE/Claude Code,EvoPrompt/Claude Code,GEPA/Claude Code），Target/Worker usage、原生约束函数离线重算、source266/凭据/真实test齐；test0为有效评分。总541通过，主清单472/480不变，Travel累计10/24；重点剩46。两个五项短组全完成，继续按真实旧错误准备后续，旧失败保留。

2026-10-28 16:00：新增TravelPlanner 4格完整审计通过（OPRO/Claude Code,ACE/MiniAgent,EvoPrompt/MiniAgent,GEPA/MiniAgent），Target/Worker usage、原生约束函数离线重算、source266/凭据/真实test齐；test0为有效评分。总537通过，主清单472/480不变，Travel累计6/24；重点剩50。原Mini短组全完成，CC队列继续，旧失败保留。

2026-10-28 15:30：Airline同源Modular/Mini Worker输出16384配置完整通过：19Target19Worker finished/usage齐，native业务评分重算/source230/75files0hits/test0有效。仅输出上限8192→16384的新配置通过，旧失败保留。Airline成为第15个24格全通范围。连同Travel SkillOpt/Mini，本轮新增2格，总533通过，主清单472/480剩8，Travel累计2/24，重点剩54。Travel ACE自动真实paid接续。

2026-10-28 15:25：TravelPlanner JSON兼容修复后新增1格完整审计通过（SkillOpt/Mini），Target/Worker usage、原生约束函数离线重算、source266/凭据/真实test齐；test0为有效业务评分，未改题或评分。总532通过，主清单471/480不变，Travel累计2/24；重点剩55。其余已登记Mini顺序接续，旧失败和原始报告保留。

2026-10-28 15:25：TravelPlanner JSON兼容修复后新增1格完整审计通过（OPRO/Mini），Target/Worker usage、原生约束函数离线重算、source266/凭据/真实test齐；test0为有效业务评分，未改题或评分。总531通过，主清单471/480不变，Travel累计1/24；重点剩56。其余已登记Mini顺序接续，旧失败和原始报告保留。

2026-10-28 15:20：用户授权调整TravelPlanner转换接入；新增完整裸JSON数组兼容，保留原围栏解析、每日字段校验、原生prompt/scorer和预算。源码59项、Windows安装wheel15项、Linux冻结安装wheel15项/CLI通过，3条旧真实回复逐内容不变离线复现；独立新root266，OPRO/Mini已paid运行，后4Mini未paid顺序等待，尚无新增通过。SWE协议诊断确认最后analysis为单finding对象而非列表，未修改其parser/gates。已审计Airline旧16项raw无proc/未来引用后清205557760bytes保留报告与paid；其raw已不可重审。[修复及验证](validation-travelplanner-json-compatibility-20261028.json) · [协议分类](smoke-protocol-review-20261028.json)。

2026-10-28 14:30：用户新授权提高实际耗尽的输出上限。Airline同源Modular/Mini登记独立Worker llm.max_tokens=16384（旧实际默认8192）；Worker120/1200、Target8/600、native会话100、111/seed和评分不变。公开plan/check-only/native预算映射预检通过后已真实paid运行。旧8192失败保留，未新增通过或修改产品；后续正式实验由实验者显式配置/记录角色预算，横向比较固定或披露差异。

2026-10-28 14:05：新增NQ同源Modular Mini/CC两格通过，原3条完整Wikipedia上下文、原始JSON文件SHA及Task/question/answer逐项一致；两个角色usage/native/source230/凭据/test齐，NQ成为第14个24格通过范围。无新数据研究/整池下载。总530/42/14/14/24，主清单471/480、剩9，加Travel和Spreadsheet重点剩57。Airline Mini Worker120触8192输出上限，2Target2Worker usage/native/source230/11files0hits齐但无test，保留失败并停止本组；BrowseCC在途。BFCL固定源码/Base200/原41/61/29已恢复并校验，镜像构建免费失败，未模型。Spreadsheet immutable manifest经HTTP1.1完整验证，但skopeo基础层拷贝失败，仍0模型。无新增Benchmark/产品修改。[本轮证据](smoke-heartbeat-20261028-1405.json)。

2026-10-28 13:25：Airline同源Modular/Mini已终结，12Target14Worker usage齐、native重算/source230/49files0hits，末端Worker60轮失败，无result/test，不能通过。按真实上限授权登记唯一Worker120/1200新配置，Target8/600/native100/111/评分不改；不再自动升级。本轮总新增通过仍4格，当前528/42/14/16/24，主清单469/480、剩11。Browse同源CC已真实paid，Mini顺序待接。无新增Benchmark。

2026-10-28 13:05：新增4格通过：WorkBench同源Modular Mini/CC、Airline同源Modular/CC、Terminal AHE/CC80；Target/Worker usage、native重算、source和凭据审计齐。WorkBench成为第13个24格通过范围。Banking同源Mini的候选runtime重复kind参数报错被gate拒绝，完整回退/test1，但一条execution_gate usage未知，保留partial、不重派。总528/42/13/17/24，主清单469/480通过、剩11；加Travel和Spreadsheet重点剩59。Airline/Mini真实paid继续；Spreadsheet官方321条数据SHA齐、3类数值原生评分控制通过，0模型，Docker基础镜像拉取受网络阻塞。无新增Benchmark通过、无产品修改。[本轮证据](smoke-heartbeat-20261028-1305.json)。

2026-10-28 12:05：CRUX同源Modular/CC再新增完整通过，11Target5Worker finished/usage齐、native重算/source230、32files0hits、test1。连同本轮Banking/CC与CRUX/Mini共新增3格；CRUX成为第12个24格通过范围。总524/42/13/21/24，重点465/480通过、剩15，加Travel和新Spreadsheet共剩63。Banking/Mini已paid在途；WorkBench两项注册后免费预检，0paid；原生数据缓存/Task与旧主实验一致。smoke2按完整引用审计清2个已结束可重建环境，释放约1.57GB、free3.05GB，保留版本/指纹/pyvenv清单，无源码/数据/raw删除。无新增Benchmark或产品代码修改。

2026-10-28 11:45：新增同源Modular两格完整通过：Banking/CC（11Target5Worker、source230、32files0hits、test1）及CRUX/Mini（16Target8Worker、source230、45files0hits、test1）；usage及native重算齐。总523/42/13/22/24，重点464/480通过、剩16，加Travel与新Spreadsheet共剩64。CRUX/CC已自动接续paid，Banking/Mini唯一新项免费准备；TerminalAHE80仍在途，smoke2有界免费核WorkBench原生缓存。无新增Benchmark通过或产品代码修改。[本轮审计](smoke-heartbeat-20261028-1145.json)。

2026-10-28 11:30：新机smoke5:36791已接入（8GB、初始29.9GB可用、Docker正常），原生CRUX800缓存与原sample223/559/113校验一致。冻结230文件同源Modular实现，两角色公共plan/check-only通过、免费models200；Mini真实paid运行、CC唯一待接，非通过停止后续。SpreadsheetBench2仅LibreOffice依赖准备，不计模型/通过。总521/42/13/24/24不变，无新增Benchmark通过/产品代码修改。[新机记录](smoke-newhost36791-20261028.json)。

2026-10-28 新验收范围与截止：用户已确认今天23:59。主清单19类（AIME两年分别计，20范围）当前462/480通过、剩18；加TravelPlanner24及新SpreadsheetBench2计划24，重点范围仍需验证66格。新Spreadsheet尚未接入/实跑，不改原624格分母。LiveMath按用户要求列访问条件例外，不挡本次项目交付，保留24格未实跑记录；不能作为模型通过。Office/Deep/Wide/Retail降为非重点，历史总521/42/13/24/24不变。[今日重点计划](smoke-focus-20261028.json)。

2026-10-28 11:00：按用户新版ModularRSI验证，源码及Windows/Linux独立wheel三轮各84项测试通过，CLI与公开plan/check-only通过；原生Banking普通train008/dev019/test004（实际ID为task_前缀）共享policy/环境且不设evolution_source，初始化成功。smoke4已真实启动唯一ModularRSI/Claude Code，Target40/1200、Worker60/600、会话100、111/seed42，使用公开Claude扩展示例初始资源。模型在途尚未通过；总521/42/13/24/24保持，24格旧独立来源拒绝仅为历史状态，不能继续视为当前同源前置阻塞。TerminalAHE80原3项免费setup已全部成功并由原followup唯一派发在途。无新增Benchmark，无本轮产品代码修改。[验证证据](validation-modular-same-source-model-20261028.json)。

2026-10-28 10:05：Wide MetaJudge8192/Worker120结束needs_attention，baseline/test和Worker完成，唯一candidate达到Target80；3Target1Worker usage/native/source267/14files0hits/test0齐，不升级通过、不继续自动加预算。当前原付费队列均终结。TerminalAHE80仍0paid：公共plan/check-only0与原3Task parity齐；Native3后端engine从88f71变化为389a2，未执行reset，旧镜像消失，已从现存smoke2缓存流式恢复3个原image并逐完整ID/RootFS layers核对。恢复原有Docker loopback桥（完整JSON转发，未改产品），并把失效的原10.239.91.9:45539容器私网代理接到当前loopback33616；仅绑定同一私网IP，Ubuntu与官方uv HEAD均200，无凭据写入容器/网关。真实Harbor官方install_only模式无Agent.run/Verifier/model调用，train安装已成功，dev/test继续；三项全部成功、image/engine/source/disk/hostlock核验后才由唯一followup派AHE80一次。最初两免费探针省略原生Trial结果初始化，保留错误并改用官方install_only，不把工具错误归产品/基础设施。总521/42/13/24/24未变，无新增Benchmark/产品修改/清理。

2026-10-28 ModularRSI 适配规则更新：按用户要求，允许使用同一来源数据集的常规
train 演化，不再强制 `metadata.evolution_source` 或外部演化数据。仍要求 train
非空、任务 ID 唯一且与 dev/test 不重合；相同 policy/环境目录不再构成拒绝条件。
下表 `⊘` 保留旧协议下的实际前置拒绝证据，不能再据此认定同来源配置不适配；
须用新配置检查与真实 smoke 验证。此次代码与离线验证不增加任何真实通过格数，
先前回复协议失败也不自动升级。详情见 [适配验证](validation-modular-shared-train-20261028.json)。

2026-10-28 08:52：新增Retail RRSI Mini/CC与SWE RRSI/CC Worker120三格原生审计通过，总521/42/13/24/24，剩103。SWE6Target6Worker finished/usage、native重算/source273/27files0hits/test1齐；原外部审计错误要求非Modular RRSI的evolution_source触KeyError，保留原audit.log，仅外部审计改记录实际native benchmark metadata后完成，不伪造演化来源或改产品。Retail9项组全通过并终结，当前累计19格。现存smoke2与smoke3均发现完整Terminal89任务与三原选镜像，smoke3另有原Harborenv及AHE03配置；旧“无现成Terminal依赖”表述已纠正。只准备AHE/CC Target80/2400（旧真实40轮上限），Worker60/600、111/seed/评分/原任务保持，冻结source273新根，免费公开预检中，未paid且dispatcher disabled直到原生Harbor setup充分证明。旧RRSICC80已paid且历史未知不重复派。无新增Benchmark/产品修改/清理。

2026-10-28 08:09：新增Retail MetaHarness/Mini100、EvoHarness/Mini100与CC100三格原生审计通过。Meta3Target1Worker、14files0hits、test1；Evo各2Target0Worker、9files0hits、test0，原生合法跳过反思，未覆盖Worker分支。全部已发生阶段finished/usage齐、native重算/source265不变。总518/44/14/24/24，剩106。Retail累计17通过，RRSIMini public52736真实paid，RRSICC唯一待运行；SWE RRSICC public705、Wide Meta public42125仍真实paid在途。三机proxy正常、源hash均不变，无清理/产品修改/新增Benchmark。

2026-10-28 07:48：Retail ADAS/CC与DarwinX/CC又新增2格原生审计通过；本轮累计5格，总515/47/14/24/24，剩109。Airline22非Modular已全通过，Retail累计14格，MetaMini自动接续。SWE RRSICC原Verified三选中任务native setup/pipcheck/ClaudeCode导入全pass、镜像及engine未变、原split parity与公共plan/check-only0，controller565/public705真实experiment且paid。Wide MetaHarness旧保留原始轨迹证明Judge4096真实finish_reason length及Worker60上限，已登记唯一Judge8192+Worker120/1200新配置，Target80/2400、原111与七指标评分/Judge超时和retry不变，controller42045/public42125真实experiment paid；不以已删除的OPRO8192 raw反推旧错，不扩整组或自动继续加预算。无新增Benchmark/产品修改/清理。

2026-10-28 07:43：本轮进一步新增Airline AHE/CC Worker120与Retail AHE/CC100两格，各3Target1Worker finished/usage、native/source265/12files0hits/test1齐。连同Retail DarwinXMini，本轮累计新增3格，总513/49/14/24/24，剩111。Airline22个非Modular已全部通过，旧失败保留；Retail接ADASCC，余6待付费。SWE RRSICC原任务free native setup仍在验证，不能当模型运行。无新增Benchmark、无产品修改。

2026-10-28 07:42：新增Retail DarwinX/Mini100通过，4Target2Worker finished/usage、native重算/source265、16files0hits/test1齐。总511/50/15/24/24，剩113。SWE ModularMini16/Worker120付费新尝试失败：ModularRSI analysis must return a list of findings；5Target4Worker全finished有usage，5个原生SWEBenchVerifier，已对现有评分离线重算/source273/21files0hits，但缺result/test，不能通过；不是新上限或网络故障，不重派或松parser。最初失败审计沿用完整result目录选择触assert，保留attempt01，外部失败审计按唯一trajectories目录与missing_result补齐，未改产品。SWE RRSICC另有旧原报告明确Worker60轮错误，登记Worker120/1200一次，CC40/1200和111/seed/原Verified任务不改，公共plan/check-only均0，当前原任务native setup免费验证中，充分证明后才自动付费。Airline AHECC及Retail AHECC真实在途，无新增Benchmark、无产品修改、无清理。

2026-10-28 07:29：新增11格原生审计通过：Retail SkillOpt/ACE/EvoPrompt/GEPA CC；Airline MetaCC、EvoHarness Mini/CC、RRSI Mini/CC；Banking RRSI Mini/CC。Target/Worker usage、原生重算、sourcehash、凭据扫描齐，test有效。总510/51/15/24/24，剩114。Banking22个非Modular与Airline100现有组完成；SWE三选中任务独立免费原生setup/pipcheck/适配器导入通过、镜像与engine不变，启动一次Mini16/Worker120新预算配置。Retail剩9项准备迁smoke4：以旧原始报告纠正，MetaCC为真实失败不纳入，RRSICC旧premature纳入；无产品修改、无新增Benchmark。

2026-10-28 06:48：新增12格原生审计通过：τ² Retail/SkillOpt/MiniAgent、τ² Retail/ACE/MiniAgent、τ² Retail/EvoPrompt/MiniAgent、τ² Retail/GEPA/MiniAgent、τ² Retail/OPRO/Claude Code、τ² Airline/DarwinX/MiniAgent、τ² Airline/DarwinX/Claude Code、τ² Airline/MetaHarness/MiniAgent、τ³ Banking/MetaHarness/MiniAgent、τ³ Banking/MetaHarness/Claude Code、τ³ Banking/EvoHarness/MiniAgent、τ³ Banking/EvoHarness/Claude Code。全部Target/Worker usage、原生重算、source与凭据审计齐，test有效。总499/60/17/24/24，剩125。Airline100首4项完成后按旧MAX_STEPS8完整证据登记剩16项；只改会话步数100与独立输出，原111/Worker/LLM/超时/评分不改，非通过即停。Banking MetaMini Worker120/1200已通过，旧Worker60失败保留，原5项已自动接续。smoke2清已结束且审计/usage齐并无进程/未来引用的原始输出约842MB，保留最小report/paid/config/source/data；随后迁入真实19d2 SDK环境，SHA/pipcheck/原生指纹不变及公开plan/check-only均通过，非cold安装，不伪造marker。SDK准备完成后的排队门槛改1.1GB，controller仍安装后900MBguard；OPRO/CC实际通过，4个CC后续按旧MAX_STEPS8证据登记，非通过即停。SWE旧16384输出预算运行已核实为Worker60轮失败，之前代码问题判断不准确；只登记新Worker120/1200、保留输出16384，其余不变，等待原生Docker/镜像/任务setup充分证明后才派模型。无新增Benchmark、无产品源码修改。无新增Benchmark、无产品修改。

2026-10-28 06:27：新增12格原生审计通过：BrowseComp/RRSI/Claude Code、τ² Retail/OPRO/MiniAgent、τ² Airline/SkillOpt/Claude Code、τ² Airline/AHE/MiniAgent、τ² Airline/ACE/Claude Code、τ² Airline/EvoPrompt/Claude Code、τ² Airline/GEPA/Claude Code、τ² Airline/ADAS/MiniAgent、τ² Airline/ADAS/Claude Code、τ³ Banking/ADAS/Claude Code、τ³ Banking/DarwinX/MiniAgent、τ³ Banking/DarwinX/Claude Code。全部Target/Worker usage、原生重算、source与凭据审计齐，test有效。总487/71/18/24/24，剩137。Airline100首4项完成后按旧MAX_STEPS8完整证据登记剩16项；只改会话步数100与独立输出，原111/Worker/LLM/超时/评分不改，非通过即停。本轮smoke3再清3个无引用旧环境，保留依赖与指纹后恢复2.77GB；DarwinX/Mini旧磁盘预检paid0，保存旧状态后恢复同未付费项。smoke2迁入原生CF环境和固定fc0055dc缓存，源265/pipcheck/commit/压缩流SHA验证齐，属warm迁移；经引用审计清8个已结束raw目录后free1.54GB。Retail OPRO/Mini100已含真实DB/NL业务评分，现接四项Mini组。Banking MetaMini100因Worker60轮失败，1Target1Worker usage/native/source/9files0hits齐但无result/test，保留失败；独立Worker120/1200代表已实际启动，余5未paid原100配置迁入该组待代表通过，不重启旧SDK控制。无新增Benchmark、无产品修改。

2026-10-28 05:30：新增2格原生审计通过：τ² Airline/OPRO/Claude Code、τ³ Banking/ADAS/MiniAgent。全部Target/Worker usage、原生重算、source与凭据审计齐，test有效。总475/81/20/24/24，剩149。Airline100首4项完成后按旧MAX_STEPS8完整证据登记剩16项；只改会话步数100与独立输出，原111/Worker/LLM/超时/评分不改，非通过即停。smoke3新CC环境安装后磁盘曾降至166MB；完整本地运行时/proc/pth/未来配置审计后清5个旧环境并保留NameVersion/pyvenv/指纹，恢复约3.47GB。首OPRO/CC通过后下一项仅未付费磁盘预检阻塞，保存旧状态后恢复同控制，未重派已paid。无新增Benchmark、无产品修改。

2026-10-28 05:20：新增9格原生审计通过：BrowseComp/EvoHarness/Claude Code、τ² Airline/SkillOpt/MiniAgent、τ² Airline/ACE/MiniAgent、τ² Airline/EvoPrompt/MiniAgent、τ² Airline/GEPA/MiniAgent、τ³ Banking/AHE/Claude Code、τ³ Banking/ACE/Claude Code、τ³ Banking/EvoPrompt/Claude Code、τ³ Banking/GEPA/Claude Code。全部Target/Worker usage、原生重算、source与凭据审计齐，test有效。总473/82/21/24/24，剩151。Airline100首4项完成后按旧MAX_STEPS8完整证据登记剩16项；只改会话步数100与独立输出，原111/Worker/LLM/超时/评分不改，非通过即停。smoke3新CC环境预检消耗空间后磁盘紧张，引用审计与处理见本轮heartbeat；不热改在途源，不因磁盘盲派。无新增Benchmark、无产品修改。

2026-10-28 04:15：新增6格通过：Browse/DarwinX CC160；Banking100 EvoPrompt/Mini、GEPA/Mini、OPRO/CC、SkillOpt/CC、AHE/Mini。全部Target/Worker usage、原生重算、源hash、凭据审计齐，test为有效原生评分。总464/91/21/24/24，剩160。Airline/SkillOpt30只有test达到MAX_STEPS，4Target1Worker usage/source265/native审计齐但仍partial；独立100步代表实际启动，原3项未paid30步配置暂停并转新100步组，先代表通过再接续，非通过停止且不再自动扩步数。三机代理正常，源271/265/193均未变；无清理、无产品修改、无新增Benchmark。

2026-10-28 03:32：新增5格通过：Browse/OPRO CC160（3Target1Worker/source271/test1），Banking/BM25 OPRO、SkillOpt、ACE Mini原生100步（分别3/4/4Target与1/1/2Worker，source193/test0），Airline/OPRO Mini原生30步（3Target1Worker/source265/test0）。全部usage/native重算/源hash/凭据审计通过；Banking OPRO与Airline三阶段另核USER_STOP和原生业务检查，零分为有效评分。总458/97/21/24/24，剩166。Banking100是明确预算配置，上游辅助入口100与配置类默认200分开记录，不称统一默认。DeepEvoPrompt160候选仍达上限，保留partial；无新增Benchmark，无产品修改。

2026-10-28 02:10：Banking/BM25 OPRO/Mini结束needs_attention，3Target1Worker均finished且usage/native/source193齐、11文件0hits；baseline和candidate为原生8步MAX_STEPS缺业务Verifier，test为USER_STOP有真实业务评分0。不计通过；新独立native max_steps30代表项已实际运行，原21格暂停。总453/102/21/24/24不变，无新增Benchmark。

2026-10-28本轮：DeepSearchQA/MetaHarness/CC160轮4800秒通过，3Target1Worker finished/usage齐/native重算/source229未变/凭据14文件0hits/test2/3。总453通过102部分21失败24前置24待，无新增Benchmark。DeepEvoPrompt2230已自动实际运行，Banking/BM25下一项。用户指出速度偏慢，排期标记DDL风险，后续优先共享阻塞与可推进组合数量，不能仅追单格预算。

2026-10-28 01:10：BrowseComp/ACE/CC160轮4800秒通过，4Target2Worker finished/usage齐/native重算/source271未变/凭据12文件0hits/test1。总452通过103部分21失败24前置24待，无新增Benchmark。OPRO160已自动实际运行，DarwinX→EvoHarness→RRSI160顺序后续均未paid；DeepMetaHarness160仍运行。

2026-10-28 00:40：BrowseComp/GEPA/CC160轮4800秒通过，4Target1Worker finished、usage齐/native重算/source271未变/凭据13文件0hits/test1，custom Judge范围保留。总451通过104部分21失败24前置24待，无新增Benchmark。BrowseACE160和DeepMetaHarness160真实运行；BrowseOPRO160→DarwinX160新顺序后续已登记，未付费。

2026-10-27 23:50补充：OfficeQA/EvoHarness/CC160和ADAS/Mini Worker120均通过。前者2Target0Worker（原生合法跳过反思，未覆盖Worker分支）/usage/native/source229/9文件0hits/test1；后者3Target1Worker/usage/native/source229/13文件0hits/test0。连同本轮MetaHarness共新增3格，总450通过105部分21失败24前置24待；无新增Benchmark。BrowseGEPA160已自动运行，ACE160唯一后续已登记。

2026-10-27 23:30：OfficeQA/MetaHarness/CC160轮4800秒通过，3Target1Worker finished、usage齐/native重算/source229未变/凭据14文件0hits/test1。总448通过106部分22失败24前置24待，无新增Benchmark。OfficeEvoHarness已自动接续运行；DeepADAS候选仍在原4800秒有界执行中，未结束不计通过。

2026-10-27 23:03用户确认：原机/smokedoc已由用户删除。后续只使用smoke2、smoke3，停止31447探测与恢复；不再作为故障阻塞上报。历史结果保留，组合总数447/107/22/24/24不变。

2026-10-27 23:00复核：OfficeQA/RRSI/CC160轮4800秒通过，6Target8Worker finished，usage齐/native重算/source229未变/凭据29文件0hits，test0为有效流程通过。总账447通过107部分22失败24前置24待，无新增Benchmark。OfficeMetaHarness与DeepADAS真实运行；后续及Banking/BM25排队按deadline计划推进。

2026-10-27 22:45：按用户授权，Banking新配置切原生BM25；免费检索初始化与查询通过，22个非Modular组合登记顺序队列，首项OPRO/Mini，尚无新模型执行或通过。旧alltools缺embedding结论保留，BM25不依赖该服务，Modular两格独立数据前置仍保留。总账446/108/22/24/24不变。

2026-10-27 22:25复核：OfficeQA/SkillOpt/CC160轮4800秒通过，4Target1Worker finished、usage齐/native重算/source229未变/凭据12文件0hits/test1。总账446通过108部分22失败24前置24待。截止时间为北京时间2026-10-29 20:00，逐格排期见[截止前计划](smoke-deadline-plan-20261029.md)。当前OfficeRRSI与DeepSearchADAS真实运行，OfficeMetaHarness→EvoHarness、DeepSearchMetaHarness顺序等待；准备不计模型运行。无新增Benchmark。

2026-10-27 21:24复核：OfficeQA/OPRO/CC160轮4800秒通过，3Target1Worker finished、usage齐/native重算/source229未变/凭据11文件0hits/test1。总账445通过109部分22失败24前置24待；本轮无新增Benchmark。DeepSearchRRSI Target160/Worker120仍真实运行，已12finished。

2026-10-27 19:56复核：OfficeQA/GEPA/CC160轮4800秒通过，4Target1Worker全finished、usage齐/native重算/source229未变/凭据13文件0hits，test1。总账444通过110部分22失败24前置24待，无新增Benchmark。DeepSearchRRSI Worker120仍running。OPRO160唯一followup33419等待ADAS1926。ADAS当前状态读取因本机磁盘不足失败，不能宣称实时运行。本机C盘约40MB，失败uv临时环境删除被自动审批拒绝。

2026-10-27 18:22复核：OfficeQA/ACE/CC在Target160轮/4800秒限定下通过，4Target及2Worker全finished、usage齐、原生评分重算、229源文件未变、凭据14文件0命中，test=0为有效流程通过。旧80轮失败保留。总账443通过111部分22失败24前置24待，本轮无新增Benchmark。EvoPrompt160轮已自动接续experiment；GEPA160轮唯一followup30556已登记等待，尚未paid。原机SSH仍拒绝；smoke3磁盘416829440bytes，引用检查尚不完整，未删除环境。

2026-10-27 17:53复核：OfficeQA/DarwinX/CC在Target160轮/4800秒限定下通过，4Target及2Worker全finished、usage齐、原生评分重算、229源文件未变、凭据16文件0命中，test=1。旧80轮失败保留。总账442通过112部分22失败24前置24待，本轮无新增Benchmark。OfficeACE160轮已实际experiment，EvoPrompt160轮唯一后续已登记。

2026-10-27 16:47实查：无新增通过/Benchmark，总账441/113/22/24/24。OfficeADAS1615 needs_attention（1Targeterror2finished1Workerfinished，usage齐source未变）；DarwinX1615 public25297真实running已3Target2Workerfinished，SkillOpt1615仍pending未paid，顺序followup保留。WideMetaHarness1618已execution_failed，1Target JudgeError+1Worker60轮error，usage齐source267未变，paidmarker保留不重派；磁盘416837632bytes，暂不派新模型。已启动env-cleanup-review-1645旧searchqa环境proc/pth引用只读核查，但SSH读通道超时，未确认完整结果，未删任何env；下轮先查references.json及真实进程，确认已完成可重建、全部引用和未来配置保护后才清。原机SSH31447仍连接拒绝，状态未知。OfficeADAS及WideMetaHarness终结报告已SFTP保存，无产品修改/无清理。

2026-10-27 16:18实查：OfficeGEPA1515 needs_attention，3Targetfinished1error、1Workerfinished，usage齐source不变，无新增通过/Benchmark，总账441/113/22/24/24保持。smoke2唯一OfficeADAS1615 controller24188/public24196真实experiment paid存在；DarwinX1615 followup24189与SkillOpt1615 followup24190依次等待，均未paid且pending纳入等待，旧Target40轮均核，三配置只Target80/2400、原111/Worker/评分不改。smoke3 loopback33616仍可用、旧最小后台存活验证完成；新WideMetaHarness1618 controller193/checkonly196在公开check-only、尚未paid，旧两Target40错误已核，只Target80/2400，沿用evidence267原Judge4096；report smoke-widesearch-metaharness-budget-retry-20261027.json。当前smoke3磁盘966856704bytes接近900MBguard，先查预检/磁盘不得盲清env。原机31447仍拒绝连接，当前状态未知。WideEvoPrompt1418中断paid/usage未知原样保留未重派。无产品修改无清理。

2026-10-27 15:48实查：无新增通过/无新增Benchmark，总账441/113/22/24/24保持。OfficeEvoPrompt1515已needs_attention，2Targetfinished3Target80轮error、3Workerfinished，usage齐source未变。OfficeGEPA1515原followup因前项短暂pending误记blocked_previous_status，已保存attempt01-pending-race，外部调度脚本仅把pending纳入等待（非产品改动），确认无paid/dispatch后恢复；现controller由followup23068派发、public23075真实experiment且唯一paid。原机31447仍SSH连接拒绝，当前模型状态未知。smoke3无队列，pidnamespace与bootid保持；查到loopback33616不在，已重建唯一SSH reverse转本地7897（本地session70690），免费models200通过、0模型，proof process-survival-1516/network-recovery.json。Wide1418仍interrupted_unknown/usage未知，不自动重派；网络恢复不能反推旧中断原因。无环境清理/无产品改动。

2026-10-27 15:16实查：OfficeACE1445已needs_attention，2Targetfinished2validation80轮error、2Workerfinished，usage齐/source未变，不加该格预算。无新增通过/无新增Benchmark，总账441pass113partial22fail24前置24待不变。smoke2唯一OfficeEvoPrompt1515 controller21043/public21050真实experiment paid存在；唯一OfficeGEPA1515 followup21044等待、未paid，原40轮错误均已核，仅Target80/2400，111其他角色评分不改。原机SSH31447连接失败，状态不可新核，不称无模型。smoke3无queueprocess，Wide1418中断usage未知仍保留；新零模型process-survival-1516后台15秒存活完成（pid121），pid namespace4026538823/boot68152de2-51ee-4fc6-9c52-cd352fd55869，说明当前短时后台存活正常，不足证明旧中断原因或可重试原paid。未再派Wide1418，未改产品未清理。

2026-10-27 14:47实查：新增OfficeQA/AHE/CC flow_passed，3Target1Worker全finished、usage齐/native重算/source229未变/凭据12文件0hits，test0有效，Target80/2400限定。总账441通过113部分22失败24前置24待/624，11范围全通，本轮无新增Benchmark。OfficeOPRO1407 needs_attention，1Targeterror2finished1Workerfinished，usage齐，不再加预算。smoke2唯一OfficeACE1445 controller19655/public19661真实experiment paid存在，旧Target40错误已核，只Target80/2400。smoke3 WideEvoPrompt1418原controller28509/public28588均不在，轨迹0、usage未知，计划已改interrupted_unknown，interruption-review.json保留，无OOM证据不推定原因，不重派；一次分类看到claude71随后消失，不能称仍有模型。原机此前Compose零模型也reset，Terminal不重派。本轮无产品改动无清理。下一轮先核主机/SSH执行环境稳定和真实队列，保留paidmarker，不把失联或中断当完成。

2026-10-27 14:18实查：本轮无新增通过/无新增Benchmark，440通过114部分22失败24前置24待/624保持。DeepSearchRRSI1352已execution_failed：2Target finished、1Worker finished、1Worker60轮error，usage齐source未变，保留原partial及本次失败，不循环扩大。smoke3已接唯一/root/.cache/wide-evoprompt-budget-1418 controller28509/public28588真实experiment/paidmarker；旧EvoPrompt全部错误为Target40轮或1200秒，沿用已验证Wide证据source267，只Target80/2400，原Judge4096及111/Worker不改，report smoke-widesearch-evoprompt-budget-retry-20261027.json。smoke2 OfficeOPRO1407 public16400真实experiment，唯一OfficeAHE1415 followup16819等待，未paid，原test40轮已核，只Target80/2400。原机publicrunner0、1.702GB，无模型；最小Compose连接reset证据保持，未重派Terminal。smoke3可用1.237GB，未清理/未改产品。

2026-10-27 14:04实查：新增DeepSearchQA/EvoHarness/CC限定flow_passed：2Target finished、usage齐、native重算/source229未变、凭据9文件0hits，train1触发原生跳过反思，Worker0为合法无更新，明确未覆盖Worker分支，test F1=2/3；customJudge/Target80轮2400秒限定。总账440通过114部分22失败24前置24待/624，11范围全通，本轮无新增Benchmark。smoke2 BrowseRRSICC1315 public14824真实experiment；smoke3 DeepRRSICC1352 controller28069/public28075真实experiment，已2Target1Worker finished，唯一新80/2400尝试。原机1355原生容器apt/curl/uv0.11.4免费安装证明通过，官方GitHub installer与SHA校验缓存镜像供下载，随后自动恢复真实experiment在Docker compose创建容器时再次socket reset，2Target error且usage未知，无Worker，不计通过。engine由c70c50d1变334d5078，未主动reset。已启动terminal-engine-diagnosis-1402零模型校验重导入及compose复现，不重复派1355。无产品修改/无清理。

2026-10-27 13:17实查：无新增通过/无新增Benchmark，总账439pass115partial22fail24前置24待/624保持。smoke2 BrowseEvoHarnessCC唯一1249真实experiment13938，1Targeterror3Workerfinished usage齐；smoke3 DeepMetaHarnessCC唯一1249真实experiment25415，1Targeterror1Workerfinished usage齐；均source未变未结束。已核原40轮错误并登记唯一后续：smoke2/root/.cache/browse-rrsi-budget-1315 followup14589等待前项，smoke3/root/.cache/deepsearch-evoharness-budget-1315 followup26839等待前项，均未paid，只Target80/2400，原111/其他角色/评分不变，原RRSI failed保留。原机1250免费setup600秒超时0模型，已完整下载33.6MB apt索引后在packages下载阶段超时。1315恢复复用1250官方完整HTTP缓存与存活代理8253，/root/.cache/terminal-https-recovery-1315/recover.py supervisor8375真实零模型setup中，已进入包下载；成功后自动且一次派terminal-rrsi-https-recovery-1315，不重复派、不启动1110/1250旧控制。没有产品修改/环境清理。

2026-10-27 12:50实查：新增BrowseComp/MetaHarness/CC与DeepSearchQA/DarwinX/CC完整通过，分别3Target1Worker与4Target2Worker全finished/usage齐/native重算/source未变/凭据14和16文件0hits；test分别1与2/3，customJudge、Target80/2400限定保留。总账439通过115部分22失败24前置24待/624，11范围全通。本轮无新增Benchmark。smoke2唯一browse-evoharness-budget-1249 controller13932/public13938真实experiment；smoke3唯一deepsearch-metaharness-budget-1249 controller25409/public25415真实experiment；旧Target40轮错误已逐条核实，本次只Target80/2400，原111/Worker/评分不变。原机1110免费setup失败0模型，已保存；新terminal-https-recovery-1250 proxy8253/supervisor8255正在零模型完整依赖安装验证，官方同源HTTPS传输先完整缓存校验，有限传输重试且apt索引任一失败即拒绝，不以部分索引派付费；成功后唯一terminal-rrsi-https-recovery-1250独立恢复，不能重复派。无产品修改无清理。


2026-10-27 11:01实查：本轮无新增通过、无新增Benchmark，总账437通过117部分22失败24前置24待/624不变。原机Terminal/RRSI/CC新engine授权尝试已execution_failed：两个baseline在容器依赖安装时连接旧代理10.236.152.161:47795超时，usage未知，无Worker；engine c70c50d1保持。零模型检查现有私有代理10.236.152.237:38161，apt HTTP源返回502；直接经现有loopback代理检查Ubuntu InRelease，HTTP失败而HTTPS200，下一步机器侧解决软件源传输后免费完整setup验证，未再付费。readiness /root/.cache/terminal-proxy-readiness-1058保留。smoke2 BrowseDarwinX仍真实运行（2Targetfinished1error1Workerfinished，usage齐），MetaHarness唯一followup等待；smoke3 DeepADAS已needs_attention（2Targeterror1finished1Workerfinished，usage齐source未变），DarwinX followup已自动派发controller24548/public24554真实experiment。检查频率确认ACTIVE每30分钟，无产品修改无清理。


最新10:16CST用户明确新授权“更换了就重新传，别停”。已重新把本地远端现有校验tar导入原机c70c50d1-b854-45a5-a1ff-ee417de50a92新engine，三任务imageID/RootFSlayers匹配，taskimage以原1CPU/2Gmemory启动零网络shell成功、engine前后不变；不是完整Harbor评分。proof /root/.cache/terminal-image-transfer-0952/new-engine-proof.json。按本次新授权仅一次新根控制/root/.cache/terminal-rrsi-newengine-authorized-1020 controller5958/public6140已真实experiment/paidmarker，TerminalRRSICC同80/2400原111与评分预算不变，原root source228controlmanifest未变，output独立；report smoke-terminal-rrsi-newengine-authorized-20261027.json。授权authorization.json保存，旧0906镜像超时与0952engine连接reset/usage未知全部保留，不重启旧controller。当前1.740GB可用。自动audit仍为completed_pending_native_audit占位，必须人工原生Verifier/usage/source审计才能通过，不能凭finished升级。本地1016start/proof/report已同步，matrix437pass不变，本轮无新增Benchmark。两其他机在途与1010唯一followup照常检查，不重复派。若新engine再变化不要伪称恢复成功，保存真实故障并机器侧诊断。

2026-10-27 10:12实查：本轮无新增通过、无新增Benchmark，总账437通过117部分22失败24前置24待/624，11范围全通。smoke2 BrowseComp/DarwinX/CC仍真实运行，已1Target+1Worker finished/usage齐；smoke3 DeepSearchQA/ADAS/CC仍真实运行，已1Target error+1Worker finished/usage齐，未结束不升级。已分别登记唯一顺序后续BrowseComp/MetaHarness/CC及DeepSearchQA/DarwinX/CC，旧test40轮错误核实，Target80/2400，其余111及角色参数不变；followup等待当前队列终结/锁释放，非预算错误则阻塞，不重复派。原机无模型，Docker新engine c70c50d1...可达但镜像/容器均空；只读资源记录memory.max2147483648/current1989050368、oom_kill0，不能据此断言重启根因。原机缓存导入证明/恢复失败保留，不继续盲付费。未改产品、未清理。

2026-10-27 09:59实查：新增BrowseComp/ADAS/CC（2Target+1Worker）与DeepSearchQA/GEPA/CC（4Target+1Worker）完整审计通过，usage/native重算/source/凭据齐、test1，customJudge80轮限定。总账437通过117部分22失败24前置24待，11范围全通。本轮无新增Benchmark。smoke2已接DarwinX/CC，smoke3已接ADAS/CC，旧40轮错误确认后仅Target80/2400，真实experiment。原机已从smoke2导入三个现有原生任务镜像，341206918bytes SHA256 0a88d1e6427c49b4d10232d07b6dd25edd8e1144bf14b6212021e467513c7024，逐imageID/RootFS层一致且三个零网络容器启动通过。Terminal/RRSI/CC一次基础设施恢复已实际执行，但创建任务容器时Docker socket连接reset，随后daemon不可达，两baseline无usage未知。之后docker info返回engine c70c50d1-b854-45a5-a1ff-ee417de50a92，与之前03f20045不同；本任务没有reset engine，不能归因产品或继续盲付费。缓存原包/失败/证明保留。


2026-10-27 09:10实查：BrowseComp/SkillOpt/CC新增完整通过（4Target+1Worker，usage/native重算/source/凭据12文件0命中，test1，customJudge80轮限定）。DeepSearch/EvoPrompt80轮结束仍3Target预算error、2finished、3Workerfinished，保留partial。smoke2已接ADAS/CC、smoke3已接GEPA/CC，均旧40轮错误确认后仅Target80/2400，真实experiment。原机清理2个已结束无proc/pth引用Search环境释放1781121024bytes，清单保存；Terminal/RRSI/CC80轮尝试已结束，两baseline均DockerHub拉取alexgshaw/adaptive-rejection-sampler:20251031超时，usage缺失未知，未评分不通过。原生daemon只有AppWorld及Python镜像，先准备网络/官方镜像再考虑有界恢复，不能盲重跑。该新run控制目录冻结228文件并保留旧Modular/README差异，未改产品。无新增Benchmark。

2026-10-27 08:07实查：本轮无新增通过、无新增Benchmark。BrowseComp/GEPA/CC80轮已结束，4Target finished、1parent80轮error、1Worker finished，usage齐/source未变，保留partial不循环加预算。smoke2已真实接SkillOpt/CC80轮2400秒，旧train/test40轮已核；smoke3 DeepSearchQA/EvoPrompt/CC仍真实运行，已有3Target error/1finished及3Worker finished，未提前判终结。原机Terminal/RRSI/CC依赖完成后旧Docker端点不可达，原日志保存；原生UDS免费docker info成功后只改DOCKER_HOST进行零模型预检，已Ready111。原机仅302923776bytes可用，未付费派发，待安全空间准备；原根既有两处源码差异仍保留。无产品改动、无环境清理。

2026-10-27 07:07实查：BrowseComp/EvoPrompt/CC（5Target+3Worker）与DeepSearchQA/ACE/CC（4Target+2Worker）新增完整通过，usage齐、native重算、source未变、凭据扫描0命中，两项test1，customDeepSeekJudge/80轮2400秒限定保留。本轮无新增Benchmark。smoke2已接BrowseComp/GEPA/CC，smoke3已接DeepSearchQA/EvoPrompt/CC，原40轮错误确认后只Target80/2400，均真实experiment。原机无模型，Terminal/RRSI/CC公开check-only零模型预检中；相关源码与旧清单一致，但整根仍有ModularRSI模块和README两处旧差异，不能称整根未变。未修改产品或清环境。

2026-10-27 06:09实查：本轮无新增通过、无新增Benchmark。BrowseComp/ACE/CC80轮复测结束：3Target finished、1test触及80轮、2Worker finished，usage齐/source271未变，保留partial不再循环加预算。smoke2已接BrowseComp/EvoPrompt/CC、smoke3已接DeepSearchQA/ACE/CC，两项原40轮错误已核，仅Target80轮/2400秒，公开预检及免费认证后真实experiment。原机无模型：Terminal/RRSI/CC旧两baseline40轮错误已核，但旧source-current清单与当前ModularRSI模块及README有两处差异，尚待版本核对，未启动或新增付费。未改产品、未清环境。

2026-10-27 05:07实查：新增MATH500/ModularRSI/Mini、BrowseComp/ADAS/Mini、DeepSearchQA/SkillOpt/CC三格完整审计通过，分别18Target+17Worker、3Target+1Worker、3Target+1Worker；usage齐、原生评分重算、源码不变、凭据扫描无命中。MATH500成为第11个24/24范围；预算及custom DeepSeek Judge限定保留。本轮无新增Benchmark。三项原队列均结束。下一项BrowseComp/ACE/CC只调整Target40/1200至80/2400，原两阶段40轮错误已核；零模型配置层级错误保留并纠正，真实状态见本轮报告。没有产品修改或环境清理。

2026-10-27 04:09实查：AppWorld/ModularRSI/Mini新增完整通过（20Target+17Worker，原生评分重算/usage/源码286/凭据76文件0命中，test0正常），成为第10个24格通过范围，Worker120轮/1200秒限定单列。本轮无新增Benchmark。原机MATH500/Mini120轮复测仍运行（12Target+11Worker已finished），smoke2 BrowseComp/ADAS/Mini Worker120轮新尝试真实运行，smoke3 DeepSearchQA/SkillOpt/CC Target80轮新尝试真实运行。上一轮Browse OPRO/CC候选仍触及80轮，baseline/final正常；Wide OPRO/CC Judge8192仍三阶段length截断，两项保留partial并停止继续循环加预算。没有产品改动或环境清理。

2026-10-27 03:09实查：本轮新增完整通过0，无新增Benchmark。MATH输出16384复测达到Worker60轮，16Target+16Worker finished后1Worker error，usage齐；SWE输出16384复测Worker60轮，另有候选TraceWriter.event重复kind参数错误，一条Target usage未知。Wide OPRO/CC三阶段Judge失败，新真实事件证明3个finish_reason=length/completion4096；已用真实launcher环境完成离线审计，保留初次审计环境缺依赖日志。原机AppWorld/ModularMini仍运行（6Target+6Worker finished），唯一MATH120轮后续等待；smoke2 BrowseComp/OPRO/CC 80轮/2400秒新尝试运行；smoke3 Wide OPRO/CC Judge8192新尝试运行，其他参数保留。未修改产品源码、未清环境，旧结果不覆盖。

2026-10-27 02:18实查：新增AIME2026/ModularRSI/Mini（21Target+19Worker）和CRUXEval-O/RRSI/CC（6Target+6Worker）两格审计通过，原预算失败保留。本轮无新增Benchmark。原机MATH500/Mini真实运行、AppWorld/Mini顺序待；smoke2 CRUX已完成、SWE/ModularRSI/Mini已自动接上真实运行；smoke3 WideSearch/OPRO/CC真实运行。MATH两次零模型预检错误由私有调度强制离线和选错源码根引起，原日志保留，已恢复联网并改回原验证MATH根，不改产品源码。WideSearch除40轮外还有旧Judge ValueError，此次使用已验证267证据记录能力，Judge预算和评分不变，不预先宣称已修好。

2026-10-27 01:24实查：BBEH/DarwinX/CC预算复测完整通过（4Target+2Worker，原生评分和usage齐），成为第8个24格通过范围。原机AIME2026/ModularRSI/Mini真实运行（8Target+6Worker已finished），MATH500与AppWorld顺序待运行；smoke2本批1结束/0运行/0待，smoke3无模型。原机安全清3个已结束无引用环境，空闲恢复3.04GB。四项预算复测保持原1/1/1与评分，每项最多一次。本轮无新增Benchmark。

2026-10-27 本轮：三项协议复测已全部审计通过，SearchQA新增成为第7个24格通过范围（14Target+13Worker均finished、usage齐、原生评分重算和源码审计通过，test0正常）。用户已明确授权提高不足的角色预算；新增四项各一次1/1/1预算复测登记，具体状态见[预算复测](smoke-budget-authorized-retries-20261027.json)。原失败与旧预算结果全部保留。

- **项目层面已处理：15项。** 用户确认的 SearchQA、HotpotQA、Terminal2.0、τ³、NQ、TriviaQA、MuSiQue、SWE-bench、BFCL Multi-Turn、OfficeQA Pro、DeepSearchQA、WorkBench，加我方已有证据的2Wiki、AIME2025、SuperGPQA。仍保留各自适配收尾项及原始失败记录。
- **24格均标记通过（含既有范围/分支限定）：15个范围。** HotpotQA、2WikiMultiHopQA、AIME2025、SuperGPQA、TriviaQA、MuSiQue、SearchQA、BBEH、AIME2026、AppWorld、MATH500、CRUXEval-O、WorkBench、NQ、τ² Airline。MATH500 ModularMini采用Worker120轮/1200秒、输出16384。AppWorld ModularRSI/Mini采用Worker120轮/1200秒。AIME2026 ModularRSI/Mini采用Worker120轮/1200秒。BBEH的DarwinX/CC采用本次授权80轮/2400秒；不是统一旧预算全通。不是全部分支或默认冷下载均通过；历史限定仍见逐格引用。
- **同源Modular补齐：** CRUXEval-O已24格通过；Banking余Mini在途。
- **覆盖规模：** 28种公开注册Benchmark中纳入24种，按年份/领域拆成26个范围；12算法 × 2Target，共624格。
- **组合状态：** 552通过（含限定）、26部分、13失败、9历史前置拒绝、24未运行。组合统计保留旧预算结论，新预算尝试只有完成原生审计后才更新对应格。

### 当前任务边界

只用现有代码、公开配置及现有数据执行 **1 train / 1 dev / 1 test** smoke，检查原生执行、评分、轨迹与usage。不追求提分或强制产生候选；不新增开发、不做全量下载/整池研究。已通过格不重跑；旧预算或回复协议失败保留；用户2026-10-27明确授权提高不足的角色预算，每项先一次新配置尝试；环境修复只有得到证明且符合既有恢复次数限制后才复测。算法必要校验仍保留，条件不足如实记录。

### 阅读导航

- [逐Benchmark验收汇总](#逐benchmark验收汇总)
- [算法与Target组合明细](#算法与target组合明细)
- [剩余问题如何处理](#剩余问题如何处理)
- [历史记录与证据索引](#历史记录与证据索引)

## 逐Benchmark验收汇总

“已处理”是项目验收分类，不会把原始失败改成通过。每行24格；通过数包括✓、✓*、✓†，具体限定查明细链接。

| Benchmark / 范围 | 项目分类 | 通过 | 部分 | 失败 | 前置不足 | 未运行 | 剩余事项 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| SearchQA | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | ModularRSI/CC授权复测完整通过；旧协议失败保留。 |
| HotpotQA | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | 24格标记通过；保留逐格范围/分支限定，无需重复运行。 |
| Terminal-Bench 2.0 | 已处理，适配收尾 | 22 | 0 | 2 | 0 | 0 | AHE/CC80原生HarborVerifier及usage审计通过；旧RRSI80 paid结果未知不重派。 |
| AppWorld | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | ModularRSI/Mini Worker120轮/1200秒通过，20Target+17Worker审计齐；旧60轮失败保留。 |
| NQ | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | 同源Modular Mini/CC原生审计通过；复用原3条完整上下文和文件SHA，无整池下载/改题，24格补齐。 |
| 2WikiMultiHopQA | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | 24格标记通过；保留逐格范围/分支限定，无需重复运行。 |
| SWE-bench | 已处理，适配收尾 | 23 | 0 | 1 | 0 | 0 | RRSICC Worker120/1200已原生审计通过，原CC40/1200/111保持；6Target6Worker usage齐/source273/27files0hits/test1。ModularMini仍为findings列表协议失败，不放宽解析或重派。 |
| BFCL Multi-Turn | 已处理，适配收尾 | 22 | 0 | 1 | 1 | 0 | 同源Modular已有真实尝试，保留失败/缺usage；只按实际角色上限一次新配置，不松原生评分。 |
| OfficeQAPro | 已处理，适配收尾 | 20 | 2 | 0 | 2 | 0 | AHE/CC80轮、DarwinX与ACE/CC160轮通过；其他CC部分项受轮数限制，ADAS/Mini Worker失败；ModularRSI两格前置不足。 |
| DeepSearchQA | 已处理，适配收尾 | 19 | 3 | 0 | 2 | 0 | EvoHarness（合法无Worker）、DarwinX、SkillOpt、ACE及GEPA/CC80轮复测通过；其他CC部分项预算/覆盖不足；ModularRSI两格前置不足；custom Judge范围保留。 |
| AIME 2026 | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | ModularRSI/Mini Worker120轮/1200秒复测完整通过，旧60轮失败保留。 |
| WorkBench | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | 同源Modular Mini/CC原生审计通过，24格补齐；原独立来源拒绝保留历史。 |
| BBEH | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | DarwinX/CC以用户授权80轮/2400秒通过；旧40轮部分和Mini解析失败保留。 |
| SuperGPQA | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | 24格标记通过；保留逐格范围/分支限定，无需重复运行。 |
| τ³ Banking | 已处理，适配收尾 | 23 | 1 | 0 | 0 | 0 | 同源Modular/CC通过；Mini完整回退/test1，候选runtime报错且单条usage未知，记partial。 |
| WideSearch | 尚未收尾 | 1 | 19 | 2 | 2 | 0 | Meta CC新Judge8192/Worker120仍partial：baseline/test与Worker完成，candidate到Target80；3Target1Worker usage/native/source267/14files0hits/test0，不自动再增预算或扩组。OPROMini单格通过，旧OPRO8192 raw已删不能反推。 |
| τ² Retail | 尚未收尾 | 19 | 0 | 3 | 2 | 0 | 100步累计19格通过，本轮RRSI Mini/CC通过，当前9项队列全终结；AHEMini/ADASMini/MetaCC原真实失败保留，两格Modular缺独立源。显式DeepSeek NL Judge范围。 |
| LiveMathBench AMC/en | 尚未收尾 | 0 | 0 | 0 | 0 | 24 | HF访问权限拒绝；共享前置受阻，24格均未运行模型。 |
| BrowseComp | 尚未收尾 | 22 | 1 | 1 | 0 | 0 | 同源ModCC160仍partial含未知usage；Mini旧Worker60失败已审计，后续独立预算配置验证，评分不变。 |
| TravelPlanner | 尚未收尾 | 21 | 0 | 3 | 0 | 0 | 包装兼容及有证据的角色预算修复后逐格原生审计；原评分/任务不变，旧失败保留。 |
| TriviaQA | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | 24格标记通过；保留逐格范围/分支限定，无需重复运行。 |
| τ² Airline | 尚未收尾 | 24 | 0 | 0 | 0 | 0 | 同源Modular Mini Worker输出16384后完整通过，19Target19Worker usage/native/test齐，24格补齐；旧60轮/8192输出失败保留。 |
| AIME 2025 | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | 24格标记通过；保留逐格范围/分支限定，无需重复运行。 |
| MuSiQue | 已处理，适配收尾 | 24 | 0 | 0 | 0 | 0 | ModularRSI/Mini授权复测完整通过，旧单对象协议失败保留。 |
| MATH-500 | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | ModularMini Worker120轮/1200秒、输出16384完整通过；旧预算失败保留。 |
| CRUXEval-O | 已处理，smoke补齐 | 24 | 0 | 0 | 0 | 0 | 同源Modular Mini/CC均完整原生审计通过；24格补齐，旧独立来源拒绝保留。 |

## 算法与Target组合明细

下表52行、624格与整理前逐格完全一致，原报告引用保持不变。

- **✓**：已有真实流程通过记录，细节以引用报告为准。
- **✓***：通过但有预算终止、分支覆盖、模型/Judge或其他范围限制。
- **✓†**：保留历史标记：真实运行后选优规则发生变更，离线回归和后续证据需结合原报告阅读；不在本次整理中升级或改写。
- **△**：部分完成或证据/覆盖不足，不等于仍在运行。
- **×**：该次真实执行失败，不等于已证明产品代码有缺陷。
- **⊘**：现有配置不满足算法前置条件，未作为模型通过。
- **—**：尚无真实组合验证；当前全部24格为LiveMath共享权限阻塞。

| **Benchmark** | **Target Agent** | **SkillOpt** | **OPRO** | **AHE** | **ACE** | **EvoPrompt** | **GEPA** | **ADAS** | **DarwinX** | **MetaHarness** | **ModularRSI** | **EvoHarness** | **RRSI** |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| SearchQA | Claude Code | [✓*][QB3] | [✓][QC1] | [✓][CB2] | [✓][T20] | [✓][SQ2] | [✓][T20] | [✓][CB2] | [✓][CB2] | [✓][CB2] | [✓][SQ27R] | [✓*][S3] | [✓][QB4] |
| SearchQA | MiniAgent | [✓][S1] | [✓][Q1] | [✓][SQ2] | [✓][T20] | [✓][SQ2] | [✓][T20] | [✓][SQ2] | [✓*][SQ2] | [✓][SQ2] | [✓][SQ26T] | [✓*][S3] | [✓][PF1] |
| HotpotQA | Claude Code | [✓*][SF1] | [✓][A1] | [✓*][HC1] | [✓][M20] | [✓][EC1] | [✓][T20] | [✓][AC1] | [✓*][NW1] | [✓][MC1] | [✓][HP26E] | [✓*][EHC1] | [✓][NW1] |
| HotpotQA | MiniAgent | [✓][SF1] | [✓][Q1] | [✓][H1] | [✓†][A1] | [✓][A1] | [✓†][A1] | [✓][D1] | [✓][DX1] | [✓][M1] | [✓][HP26E] | [✓*][E1] | [✓][CB2] |
| Terminal-Bench 2.0 | Claude Code | [✓][TS2] | [✓*][TOP3] | [✓][TAH28] | [✓][TA25] | [✓][TA25] | [✓*][T24] | [✓*][T24] | [✓*][TD2] | [✓][TM3] | [✓*][TN3] | [✓*][TEH3] | [×][TRR2] |
| Terminal-Bench 2.0 | MiniAgent | [✓][T24] | [✓][T24] | [✓][T24] | [✓][T24] | [✓][TA25] | [✓][T24] | [✓][T24] | [✓][T24] | [✓][T24] | [×][TA25] | [✓*][TE25] | [✓][T24] |
| AppWorld | Claude Code | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][AW26E] | [✓*][TA25] | [✓][TA25] |
| AppWorld | MiniAgent | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓][TA25] | [✓*][AW27B] | [✓][TA25] | [✓][TA25] |
| NQ | Claude Code | [✓][QB4] | [✓][QC1] | [✓][QB3] | [✓][T20] | [✓][NQ3] | [✓][T20] | [✓][QB3] | [✓][QB3] | [✓][QB3] | [✓][NMS28C] | [✓*][NU25] | [✓][QB4] |
| NQ | MiniAgent | [✓][QB3] | [✓][Q1] | [✓][NQ3] | [✓][T20] | [✓][NQ3] | [✓][T20] | [✓][PF1] | [✓][NQ3] | [✓][NQ3] | [✓][NMS28M] | [✓*][NU25] | [✓][PF1] |
| 2WikiMultiHopQA | Claude Code | [✓][QB4] | [✓][QC1] | [✓][QB3] | [✓][T20] | [✓][W4] | [✓][T20] | [✓][QB3] | [✓][QB3] | [✓][QB3] | [✓][TW26E] | [✓*][T20] | [✓][QB4] |
| 2WikiMultiHopQA | MiniAgent | [✓][QB4] | [✓][W1] | [✓][CB2] | [✓][T20] | [✓][W4] | [✓][T20] | [✓][PF1] | [✓][W4] | [✓][W4] | [✓][TW26E] | [✓*][T20] | [✓][PF1] |
| SWE-bench | Claude Code | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SW26R] | [✓*][SM2] | [✓*][SW28RRSICCW120] |
| SWE-bench | MiniAgent | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓][SM2] | [✓*][SM2] | [✓*][SM2] | [✓][SM2] | [×][SW28F] | [✓*][SM2] | [✓*][SM2] |
| BFCL Multi-Turn | Claude Code | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [⊘][BF24] | [✓*][NU25] | [✓][BF24] |
| BFCL Multi-Turn | MiniAgent | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [✓][BF20] | [×][BFMSS28MF] | [✓*][NU25] | [✓][BF24] |
| OfficeQAPro | Claude Code | [✓*][OQ27SK160] | [✓*][OQ27OPRO160] | [✓*][OQ27AHE] | [✓*][OQ27ACE160] | [△][OQ27EV] | [✓*][OQ27GEPA160] | [△][OQ24] | [✓*][OQ27DX160] | [✓*][OQ27MH160] | [⊘][OQ24] | [✓*][OQ27EH160] | [✓*][OQ27R160] |
| OfficeQAPro | MiniAgent | [✓][OQ24] | [✓][OQ24] | [✓][OQ24] | [✓][OQ24] | [✓][OQ24] | [✓][OQ24] | [✓*][OQ27ADM120] | [✓][OQ24] | [✓][OQ24] | [⊘][OQ24] | [✓][OQ24] | [✓][OQ24] |
| DeepSearchQA | Claude Code | [✓*][DS27S] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DS27A] | [△][DS27E] | [✓*][DS27G] | [△][DSQ24] | [✓*][DS27DX] | [✓*][DS28MH160] | [⊘][DSQ24] | [✓*][DS27EH] | [△][DSQ24] |
| DeepSearchQA | MiniAgent | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] | [⊘][DSQ24] | [✓*][DSQ24] | [✓*][DSQ24] |
| AIME 2026 | Claude Code | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26E] | [✓][AI26] | [✓][AI26] |
| AIME 2026 | MiniAgent | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓][AI26] | [✓*][AI27B] | [✓][AI26] | [✓][AI26] |
| WorkBench | Claude Code | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WMS28C] | [✓][WB26] | [✓][WB26] |
| WorkBench | MiniAgent | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WB26] | [✓][WMS28M] | [✓][WB26] | [✓][WB26] |
| BBEH | Claude Code | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓*][BB27B] | [✓][BB26] | [✓][BB26E] | [✓][BB26] | [✓][BB26] |
| BBEH | MiniAgent | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB26] | [✓][BB27R] | [✓][BB26] | [✓][BB26] |
| SuperGPQA | Claude Code | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26E] | [✓][SG26] | [✓][SG26] |
| SuperGPQA | MiniAgent | [✓][SG26F] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26] | [✓][SG26E] | [✓][SG26] | [✓][SG26] |
| τ³ Banking | Claude Code | [✓*][TB28SKILLOPTCC100] | [✓*][TB28OPROCC100] | [✓*][TB28AHECC100] | [✓*][TB28ACECC100] | [✓*][TB28EVOPROMPTCC100] | [✓*][TB28GEPACC100] | [✓*][TB28ADASCC100] | [✓*][TB28DARWINXCC100] | [✓*][TB28META_HARNESSCC100] | [✓][BMS28C] | [✓*][TB28EVO_HARNESSCC100] | [✓*][TB28RRSICC100] |
| τ³ Banking | MiniAgent | [✓*][TB28SK100] | [✓*][TB28BM100] | [✓*][TB28AHEM100] | [✓*][TB28ACE100] | [✓*][TB28EVOPROMPTM100] | [✓*][TB28GEPAM100] | [✓*][TB28ADASM100] | [✓*][TB28DARWINXM100] | [✓*][TB28MHMW120] | [△][BMS28M] | [✓*][TB28EVO_HARNESSM100] | [✓*][TB28RRSIM100] |
| WideSearch | Claude Code | [△][WS26] | [△][WS27J] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS28META8192W120] | [⊘][WS26] | [△][WS26] | [×][WS26] |
| WideSearch | MiniAgent | [△][WS26] | [✓][WS26E] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [△][WS26] | [⊘][WS26] | [△][WS26] | [×][WS26] |
| τ² Retail | Claude Code | [✓*][TR28SKILLOPTCC100] | [✓*][TR28OPROCC100] | [✓*][TR28AHECC100] | [✓*][TR28ACECC100] | [✓*][TR28EVOPROMPTCC100] | [✓*][TR28GEPACC100] | [✓*][TR28ADASCC100] | [✓*][TR28DARWINXCC100] | [×][TR26] | [⊘][TR26] | [✓*][TR28EVO_HARNESSCC100] | [✓*][TR28RRSICC100] |
| τ² Retail | MiniAgent | [✓*][TR28SKILLOPTM100] | [✓*][TR28OPROM100] | [×][TR26] | [✓*][TR28ACEM100] | [✓*][TR28EVOPROMPTM100] | [✓*][TR28GEPAM100] | [×][TR26] | [✓*][TR28DARWINXM100] | [✓*][TR28META_HARNESSM100] | [⊘][TR26] | [✓*][TR28EVO_HARNESSM100] | [✓*][TR28RRSIM100] |
| LiveMathBench AMC/en | Claude Code | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] |
| LiveMathBench AMC/en | MiniAgent | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] | [—][LM26] |
| BrowseComp | Claude Code | [✓*][BC27S] | [✓*][BC28OPRO160] | [✓*][BC26] | [✓*][BC28ACE160] | [✓*][BC27E] | [✓*][BC28G160] | [✓*][BC27ACC] | [✓*][BC28DX160] | [✓*][BC27MH] | [△][BCMSS28CP] | [✓*][BC28EVO_HARNESSCC160] | [✓*][BC28RRSICC160] |
| BrowseComp | MiniAgent | [✓*][BC26] | [✓*][BC26] | [✓*][BC26] | [✓*][BC26] | [✓*][BC26] | [✓*][BC26] | [✓*][BC27A] | [✓*][BC26] | [✓*][BC26] | [×][BCMSS28MF] | [✓*][BC26] | [✓*][BC26] |
| TravelPlanner | Claude Code | [✓][TPJ28CS] | [✓][TPJ28CO] | [✓][TPJB28CAH] | [✓][TPJ28CA] | [✓][TPJ28CE] | [✓][TPJ28CG] | [✓][TPJB28CAD] | [✓][TPJB28CDX] | [✓][TPJB28CMH] | [×][TPMSS28CF] | [✓][TPJB28CEH] | [×][TP26] |
| TravelPlanner | MiniAgent | [✓][TPJ28S] | [✓][TPJ28O] | [✓][TPJR28MAH] | [✓][TPJ28A] | [✓][TPJ28E] | [✓][TPJ28G] | [✓][TPJB28MAD] | [✓][TPJB28MDX] | [✓][TPJB28MMH] | [✓][TPMSS28M16] | [✓][TPJR28MEH] | [×][TP26] |
| TriviaQA | Claude Code | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26E] | [✓][TQ26] | [✓][TQ26] |
| TriviaQA | MiniAgent | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26] | [✓][TQ26E] | [✓][TQ26] | [✓][TQ26] |
| τ² Airline | Claude Code | [✓*][TA28SKILLOPTCC100] | [✓*][TA28OPROCC100] | [✓*][TA28AHECCW120] | [✓*][TA28ACECC100] | [✓*][TA28EVOPROMPTCC100] | [✓*][TA28GEPACC100] | [✓*][TA28ADASCC100] | [✓*][TA28DARWINXCC100] | [✓*][TA28META_HARNESSCC100] | [✓][AMS28C] | [✓*][TA28EVO_HARNESSCC100] | [✓*][TA28RRSICC100] |
| τ² Airline | MiniAgent | [✓*][TA28SKILLOPTM100] | [✓*][TA28OP30] | [✓*][TA28AHEM100] | [✓*][TA28ACEM100] | [✓*][TA28EVOPROMPTM100] | [✓*][TA28GEPAM100] | [✓*][TA28ADASM100] | [✓*][TA28DARWINXM100] | [✓*][TA28META_HARNESSM100] | [✓][AMS28M16384] | [✓*][TA28EVO_HARNESSM100] | [✓*][TA28RRSIM100] |
| AIME 2025 | Claude Code | [✓][AI25F] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] |
| AIME 2025 | MiniAgent | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] | [✓][AI25] |
| MuSiQue | Claude Code | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26E] | [✓][MU26] | [✓][MU26] |
| MuSiQue | MiniAgent | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU26] | [✓][MU27R] | [✓][MU26] | [✓][MU26] |
| MATH-500 | Claude Code | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526E] | [✓][M526] | [✓][M526] |
| MATH-500 | MiniAgent | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓][M526] | [✓*][M527T] | [✓][M526] | [✓][M526] |
| CRUXEval-O | Claude Code | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CMS28C] | [✓][CX26] | [✓*][CX27B] |
| CRUXEval-O | MiniAgent | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CX26] | [✓][CMS28M] | [✓][CX26] | [✓][CX26] |

## 剩余问题如何处理

2026-10-26 协议检修补充：BBEH/Mini 的原始审查回复是合法 JSON，`reason` 内的代码围栏被通用提取函数误识别，之前归为“分析JSON失败”不准确。已仅修 ModularRSI 外层 JSON 包装解析，59项回归和新wheel安装入口验证通过；原回复的 `accept: false` 拒绝决定保持不变。SearchQA/CC、MuSiQue/Mini确实返回单对象而非列表，仍按原协议拒绝。没有新模型调用、远端冻结源码修改或组合状态升级。见[检修与验证记录](validation-modular-rsi-json-reply-20261026.json)。

| 类型 | 代表项 | 后续边界 |
| --- | --- | --- |
| Worker/Target预算耗尽 | AppWorld Mini、SWE Mini、AIME2026 Mini、MATH500 Mini、部分CC组合 | 保存原失败和usage；用户已授权按实际触及的角色预算合理提高，各新配置先一次，不循环刷通过。不能据此判断必须改代码。 |
| 模型输出未遵循原生协议 | SearchQA CC、MuSiQue Mini、TravelPlanner转换 | 保留原回复和错误，不改回复或放宽解析来凑通过。BBEH另见上方已确认解析缺陷。 |
| 数据/服务/权限前置不足 | ModularRSI若干格、τ³ embedding凭据、LiveMath HF权限 | 仅列明现有条件缺口；停止额外独立来源研究，不伪造配置或代同意权限。 |
| 评分或记录不完整 | WideSearch旧Judge错误、τ²提前结束、Terminal AHE部分证据 | 原生评分不足的格不升级；已有正常阶段不替代完整流程。旧问题不能仅凭猜测归因。 |
| 已确认适配修复有历史复测 | AppWorld CC、SWE CC、WideSearch OPRO/Mini等 | 已通过结果保留；本轮不新增开发、不重复收费验证。 |

本次没有确认可直接新派发的组合，也没有把任何阻塞改记通过。未来只在现有配置/数据条件满足且未重复尝试时执行1/1/1；发现必须开发的问题先单独说明，不扩展任务。

## 历史记录与证据索引

2026-10-27 00:28实查：BBEH/ModularRSI/Mini与MuSiQue/ModularRSI/Mini两项授权复测均完整通过（分别20Target+17Worker、15Target+8Worker），原生评分重算/usage/源码/凭据审计齐，test0有效。MuSiQue新增成为第6个24格通过范围。SearchQA尚未完成：私有免费鉴权检查误读Claude凭据字段，0模型阻塞；已保存原失败、修正私有检查并获得models200后继续原授权尝试。无重复付费；旧实验与失败保留。

**最近实查：2026-10-27 00:06。** 原机 BBEH/ModularRSI/Mini 在运行（5 Target + 5 Worker 已完成），SearchQA/CC 顺序待运行；smoke2 MuSiQue/ModularRSI/Mini 在运行（13 Target + 6 Worker 已完成）；smoke3 无模型。已落盘记录未见错误或usage缺失，新源码hash均未变，尚无新增完整通过。原失败格在新审计完成前保留。[本轮实查](smoke-heartbeat-20261027-0006.json)

2026-10-27 00:01 更新：用户授权检修后的复测及其他协议失败项各一次重试。已新建独立目录，原机按序 BBEH/ModularRSI/Mini → SearchQA/ModularRSI/CC，smoke2 执行 MuSiQue/ModularRSI/Mini；先公开预检及免费鉴权，再最多一次模型实验。数据与原预算不变，旧失败不删除，当前不升级任何通过格。详见[复测登记](smoke-modular-authorized-retries-20261027.json)。下述23:01无进程状态为上次实查，不能覆盖本次调度。

依据最近一次 **2026-10-26 23:01（北京时间）** 实查及既有报告整理；本次仅整理文档，没有新增实验、重新审计模型或修改任何组合状态。


**以下全部为保留的历史内容。** 其中“当前”“运行中”、旧统计数与旧研究计划仅代表记录当时，不作为现在的排期或验收结论；以页首及逐格最新引用为准。数据研究与开发授权已被用户最新任务边界收窄。原始报告、失败、修复与限定均不删除。

2026-10-26 23:01 实查：三机最近 AppWorld 独立2格、SWE 恢复2格、WideSearch 证据1格均已 completed，无模型或数据进程。本轮无新增 Benchmark、无新付费尝试、无新增通过。按用户最新要求，仅执行现有代码/配置/缓存的 1/1/1 smoke，停止全量数据研究及新增开发；预算/回复协议失败不盲重跑，现有必要前置条件不足保留阻塞，不扩大为数据工程。624格状态不变，旧“partial或在途”合并统计不代表当前有运行任务。见[本轮实查](smoke-heartbeat-20261026-2300.json)。

2026-10-26 22:29后实查：本轮无新增Benchmark、0模型调用、0新增通过。三机原AppWorld/SWE/Wide证据批均已结束且冻结源码未变。本轮NQ固定官方294个Parquet分片的HTTP Range身份列读取先通过1071行试点，三机随后共完成8分片8568行，4284条可比旧记录hash完全一致；但TLS错误导致三路均停，smoke2在指定范围完整读取证明后一次curl恢复也已因TLS失败停止。其余286分片未完成，完整池重合及native Task契约结论未知，不升级NQ格、不循环重试。总账仍 {'pass': 422, 'failed': 30, 'partial_or_running': 124, 'unsupported': 24, 'pending': 24}。见[本轮记录](smoke-heartbeat-20261026-2200.json)、[部分读取一致性](smoke-nq-column-range-partial-parity-20261026.json)。

2026-10-26 21:38最终同步：本轮无新增Benchmark。AppWorld ModularRSI/CC与WideSearch OPRO/Mini各新增一格原生审计通过。WideSearch新记录修复单格已结束，3Target/1Worker完整，原生七指标/test0有效、usage/来源/凭据齐；本次未触发失败记录分支，只有离线回归覆盖，不强制再付费。旧partial保留，WS26E仅替换同一格。三机当前均无模型进程。总计 {'pass': 422, 'failed': 30, 'partial_or_running': 124, 'unsupported': 24, 'pending': 24}。见[Wide闭合](smoke-widesearch-judge-evidence-closure-20261026.json)。

2026-10-26 21:33实查：本轮无新增Benchmark。AppWorld独立CC完成11Target/5Worker、11原生Verifier、usage/来源/凭据审计通过；Mini原60轮失败保留，AppWorld最新23/24。WideSearch仅修失败证据记录，两Linux新wheel字节/CLI验证及7专项回归完成，旧266源码未改；267独立新根OPRO/Mini通过公共预检及免费鉴权后仅一次原预算真实验证运行中，不升级原partial。其他两机无模型。用户项目15项已处理、严格24/24五范围保持分口径。当前原始格统计 {'pass': 421, 'failed': 30, 'partial_or_running': 125, 'unsupported': 24, 'pending': 24}。见[本轮记录](smoke-heartbeat-20261026-2100.json)、[AppWorld闭合](smoke-appworld-independent-closure-20261026.json)、[记录修复验证](validation-widesearch-judge-evidence-20261026.json)。

2026-10-26 20:29实查：本轮无新增Benchmark。AppWorld独立Mini已结束，14条Target完成，后续Worker达到60轮上限且有usage、无final，保留失败；CC由原唯一队列自动接续，3Target/1Worker完成且usage齐，未提前通过。另两机无模型；CRUX官方镜像完整800题字节相同不能作独立池，MBPP完整427题不能直接使用当前原生f(input)契约，未改题或发模型。项目口径15项已处理、严格24/24五范围不变。当前原始格统计 {'pass': 420, 'failed': 30, 'partial_or_running': 126, 'unsupported': 24, 'pending': 24}。见[本轮记录](smoke-heartbeat-20261026-2000.json)。

2026-10-26 19:45后同步（旧段落为历史）：本轮无新增Benchmark，仍26范围624格。SWE独立恢复已结束：CC全部11Target/5Worker完成且原生Verifier/usage/离线审计通过；Mini Worker8192输出失败保留。AppWorld公开独立来源接口、66相关回归、新wheel安装入口/完整417外部任务池/原heldout不变和Linux10项回归通过；原机Docker引擎及私有IP变化、镜像丢失已在机器侧恢复，原实验/缓存未删，两个Target原生新容器setup及公开check-only通过后已唯一顺序启动，Mini真实contrast已有完成及usage，CC待。WorkBench三套完整归档690题与当前690题分别重合634/651/679，整池拒绝，0模型。严格24/24审计通过仍为五范围；用户补充其12项已有完整实验，项目收尾口径按“已处理、适配收尾”，加2Wiki/AIME2025/SuperGPQA为15项，不能据此伪改原始smoke失败格。当前原始格统计{'pass': 420, 'failed': 29, 'partial_or_running': 126, 'pending': 25, 'unsupported': 24}。见[本轮记录](smoke-heartbeat-20261026-1823.json)、[SWE闭合](smoke-swe-lite-runtime-recovery-closure-20261026.json)、[AppWorld验证](validation-appworld-independent-20261026.json)。

2026-10-26 17:50后实查同步：本轮无新增Benchmark，仍26范围624格。完整24/24通过含范围/分支限制为HotpotQA、2WikiMultiHopQA、AIME2025、SuperGPQA、TriviaQA五个范围。Trivia独立两格均已审计通过；SearchQA新独立Trivia来源Mini通过、CC分析回复对象非列表导致协议失败，最新23/24，旧native split重合拒绝保留。BrowseComp原24已结束11custom通过/9部分/2执行失败/2缺来源；RRSI-CC两条Target失败后too many failed trials，缺原生Judge不升级通过。WideSearch原24结束20部分/2执行失败/2缺来源，0整格通过，RRSI-Mini Worker8192输出上限、RRSI-CC失败trial分别保存。SWE完整官方Lite dev23提供了真实独立执行数据，先前环境失败及Worker调用保留；机器侧私有代理与官方uv缓存经两角色新容器原生setup/pip check零模型通过后，仅登记一次独立环境恢复队列。恢复Mini两Target原生评分完成但Worker8192输出失败，CC按同一队列继续；不加预算、不热改273源码、不把准备当通过。AppWorld完整缓存原train/dev/test_normal与test_challenge的ID/场景/原始指令无重合只是数据研究，尚无公开独立接口或真实两格通过。BFCL三个候选及composite均有问题重合，拒绝删除重合题。当前总计{'pass': 419, 'failed': 29, 'partial_or_running': 126, 'unsupported': 26, 'pending': 24}。见[本轮记录](smoke-heartbeat-20261026-1602.json)、[Trivia闭合](smoke-triviaqa-independent-closure-20261026.json)、[Search闭合](smoke-searchqa-trivia-independent-closure-20261026.json)、[SWE环境修复证明](smoke-swe-lite-runtime-native-repair-proof-20261026.json)。旧快照及原strict/失败历史保留。

2026-10-26 13:21实查：本轮未新增Benchmark，优先补齐已有范围。TriviaQA独立Mini已正式flow_passed：18Target+15Worker全部finished、usage/原生评分/源码/凭据审计齐，test1；Claude已进入真实实验。TriviaQA完整原生train61888对validation7993的ID/原始问题hash均无重合，公开独立演化来源接入经11新测试/89相关回归、Ruff及freshwheel安装入口验证；完整原生缓存加载/别名评分与heldout不变已核验。独立280文件新根的Mini已完成通过，Claude在途未计通过；旧22通过/2启动拒绝报告保留，新证据只替换原两格[TQ26E]。BrowseComp新增MetaHarness/Mini与EvoHarness/Mini完整custom Judge流程通过，目前10通过/9部分/1ADAS-Mini Worker60失败/RRSI-Mini运行/3待。WideSearch目前9部分/EvoPrompt-Claude运行/14待，0完整通过；实际Judge失败、40轮/1200秒与一次连接重置分别保存，缺Judge不能按正常零分通过。原机只清4个已结束Banking可重建env，释放3,688,300,544字节，清后约6.78GiB，源码/实验/usage/原数据/缓存/镜像/文档保留。SearchQA全216136条原生身份清单已流式生成，零模型完整Trivia train交集检查是原机当前付费队列之后的唯一已登记数据任务。见[本轮报告](smoke-heartbeat-20261026-1235.json)、[TriviaQA来源验证](validation-triviaqa-independent-20261026.json)、[完整原生验证](validation-triviaqa-independent-native-20261026.json)、[磁盘清理](smoke-smokedoc-env-cleanup-20261026-1235.json)。13:28更新总计416通过含限制、119部分或在途、24失败、24旧配置条件不足、41待，624格；截至本快照，全部24格流程通过的范围仍为HotpotQA、2Wiki、AIME2025和SuperGPQA。

2026-10-26 10:32实查：本轮新增WideSearch，公开默认HF201文件下载完成后发现缓存链接丢JSONL格式的问题，公共加载器修复经73回归通过/2Windows权限跳过、Linux两实际链接探针及freshwheel完整200题加载/入口验证，独立266源码已真实运行；首OPRO/Mini baseline原生评分及7次Judge请求正常，candidate/test Judge ValueError，整格部分，当前OPRO/Claude在跑。BBEH独立来源公开接入已补齐：完整原生BBH word_sorting250与原始BBEH4520问题无重合，heldout不变、原生参考评分3/3、74项相关唯一测试和新wheel通过；独立274源码Mini正在真实contrast/Worker，Claude待，并非已通过。原机Retail原24结束19部分/3Worker预算失败/2缺数据；TravelPlanner原24结束17部分/5Worker预算失败/2缺数据，记录修复独立格确认3次custom DeepSeek转换返回裸JSON数组，被未改的原生围栏解析拒绝，记录能力验证成功不等于Bench通过。BrowseComp当前7custom通过/4部分/GEPA-Claude运行/12待。见[本轮报告](smoke-heartbeat-20261026-0933.json)、[BBEH来源验证](validation-bbeh-independent-20261026.json)、[缓存格式验证](validation-native-cache-file-format-20261026.json)、[转换诊断](smoke-travelplanner-converter-format-diagnosis-20261026.json)。

2026-10-26 08:48实查：本轮新增τ² Retail，公开预检及鉴权通过后已开始唯一24格队列；3格已结束均因原生8步会话提前终止而部分完成，SkillOpt/Claude运行、20待。BrowseComp新增AHE/Mini完整通过，当前3custom通过、2Claude40轮部分、AHE/Claude运行、18待。TravelPlanner当前12格部分/待审、ADAS/Mini运行、11待，尚无完整通过；已为测试过的转换失败记录修复登记独立266文件源码、一格OPRO/Mini后续，公开预检通过，严格等待原24格结束/锁释放/真实进程退出，转换提示/解析/评分不改，未热替换在途265。LiveMathBench仍HF401/零模型受阻。smoke2为预防空间不足，又仅清7个已结束BBEH/CRUX/2Wiki的可重建依赖env，实际释放5,498,064,896字节，清后8.74GiB，源码/结果/usage/数据/缓存/镜像/文档保留。见 [本轮记录](smoke-heartbeat-20261026-0836.json)、[安全清理](smoke-smoke2-env-cleanup-20261026-0836.json)。

2026-10-26 08:38实查补充：TriviaQA 已结束22流程通过、2缺独立演化来源，完整原生validation热缓存模式；2Wiki两Target独立train/validation真实流程均通过，旧拒绝保留。本轮新增 BrowseComp（Serper/Jina、显式custom DeepSeek Judge）与 LiveMathBench AMC/en（公开预检HF401，0模型、24待）。BrowseComp当前2通过、1原生40轮部分、1运行、20待；TravelPlanner当前9部分/待审、1运行、14待，未有完整通过，转换错误不能当正常评分。原机反向代理断开导致的12次连接错误均保留，修好后仅各做一次有界复测，未重跑原10个通过项；开发机调度器增加免费鉴权及连接失败停派检查，主体源码未改。TravelPlanner转换失败证据记录的小修复通过7专项及新wheel安装/入口检查，但未部署在途冻结源码，不能追溯补齐旧缺失回复和用量。详见 [本轮报告](smoke-heartbeat-20261026-0732.json)、[网络恢复记录](smoke-triviaqa-network-recovery-20261026.json)、[独立记录修复](validation-travelplanner-conversion-evidence-20261026.json)。

2026-10-26 07:00历史快照：AIME2025 原24格加独立 SkillOpt 修复后的最新证据为24格可运行；MuSiQue独立来源已可用，Claude通过、Mini因Worker返回单个finding对象而非协议要求的列表中断，原失败保留。2Wiki新独立train/validation配置已通过两Target的完整公开启动校验，真实组合排期见[TW26E]；SearchQA三个完整原生split两两均重叠（439/145/23），新配置零模型拒绝，见[全池核查](smoke-searchqa-native-pool-overlap-20261026.json)，不放松检查。τ² Airline整批结束，21原生预算部分、1Worker预算失败、2缺独立数据，不能把MAX_STEPS规则0算业务评分通过。新增TravelPlanner24格已登记，但两次零模型公开准备均遇HF SSL EOF，尚无组合通过。

验收口径（2026-10-25 用户澄清）：在基础设施齐备时，仓库应通过公开配置和统一入口调用原生流程跑通。开发机的依赖、官方镜像/数据缓存、代理和 Docker 连接准备可以在环境侧处理，已有有效组合 smoke 不因此作废或全量重跑。不改算法、gate、原题或评分来凑通过；冷缓存首次使用体验作为补充证据单独记录。详见 [验收约定](smoke-readme-acceptance-policy-20261025.json)。



WorkBench（2026-10-26）当前24格已核验结束：22真实流程通过，2Modular旧配置缺独立演化来源；见 [接入说明](workbench.md) 与 [实际smoke报告](smoke-workbench24-public-original-20261026.json)。该缺口继续研究独立数据，不能把零模型拒绝算真实通过。

更新日期：2026-10-26。范围：原10项加 AIME2026、WorkBench、BBEH、SuperGPQA、CRUXEval-O、MATH-500、MuSiQue、AIME2025、TriviaQA、τ² Airline、TravelPlanner、BrowseComp、LiveMathBench AMC/en、τ² Retail、WideSearch、τ³ Banking，共26项、624格。AIME独立数据复测仍归原两格，不重复计数；此前离线接入说明属于历史，不代表当前排期。在用户列顺序后补 EvoHarness、RRSI。



早期离线阶段记录（以下至τ²段落保留当时范围与证据；AIME2026、WorkBench、BBEH等当前真实smoke以本表及最新报告为准）：

本轮另新增 BBEH 与 SuperGPQA，暂不计入上述优先矩阵和完成数量。

两者完成固定版本真实数据获取、离线适配测试和最新 wheel 的 MiniAgent + OPRO

`--check-only` 初始化（8/4/4 题、占位凭据、零模型调用）。

**尚无真实算法 × Target Agent × Benchmark smoke 证据**，MiniAgent / Claude Code

上的各算法组合均待验证；当前本地配置与角色环境变量未提供 API 密钥。

BBEH 示例显式排除 9 条重复题组记录，并保留上游句号评分行为；SuperGPQA 使用

答案字母协议，不等同上游宽松文本解析。详见[接入说明](lightweight-benchmarks.md)与

[本轮离线验证报告](validation-lightweight-benchmarks-20261025.json)。

后续新增 `aime`（2025 / 2026）与 `cruxeval_output`，同样不计入优先矩阵和真实 smoke
完成数。固定版本真实数据加载、离线评分与参考答案回填见
[数学与代码接入说明](coding-math-benchmarks.md)及
[验证报告](validation-coding-math-benchmarks-20261025.json)。
**尚无这两个基准的真实模型组合 smoke 证据**；CRUXEval 仅支持输出字面量协议。
最新 wheel 独立安装后，AIME 两年份和 CRUXEval 的 MiniAgent + OPRO
`--check-only` 均通过（8/4/4 题、占位凭据、零模型调用），不计作真实 smoke。

本轮新增 `tau2` 的 airline / retail / telecom 文本领域，固定上游 v1.0.1 commit。
真实数据原生 schema、环境 policy、telecom 双控制工具及 reward、retail 独立 Judge
与完整原生评分链路均通过离线验证；模型回复由脚本提供，**不是模型或算法 smoke**。
全量回归 647 passed / 18 skipped / 3 subtests passed；其中 9 项原生运行时测试在
基础环境跳过，另在独立 tau2 环境与专项测试一起验证，40 项通过。
最新代码 wheel 的三个新领域及旧 Banking 的 MiniAgent + OPRO `--check-only`
均通过（4/2/2、占位凭据、零模型调用）。真实模型组合仍待角色凭据配置后验证，
本矩阵及真实 smoke 完成数不变。详见 [τ² 接入说明](tau2-bench.md)和
[本轮验证报告](validation-tau2-20261025.json)。



[NQ3]: smoke-nq-batch3-20261023.json

[W4]: smoke-twowiki-batch4-20261023.json

[SF1]: smoke-skillopt-full-20261023.json

[ES1]: smoke-evo-stream-20261023.json

[PRE1]: smoke-prerequisites-20261023.json

[RD1]: smoke-rrsi-repairdiff-20261023.json

[NW1]: smoke-native-workers-20261023.json

[DE1]: smoke-evoprompt-de-20261023.json

[SM1]: smoke-skillopt-merge-20261023.json

[CB1]: smoke-capability-batch-20261023.json

[CB2]: smoke-continuation-batch-20261023.json

[QB3]: smoke-qa-expansion-20261024.json

[QB4]: smoke-qa-capabilities-20261024.json

[PF1]: smoke-partial-followup-20261024.json

[T20]: smoke-twenty-20261024.json

[M20]: smoke-modes-twenty-20261024.json

[X10]: smoke-extra-ten-20261024.json

[DE2]: smoke-de-two-rounds-20261024.json

[H20]: smoke-history-twenty-20261024.json

[NH1]: smoke-new-host-docker-20261024.json

[BF20]: smoke-bfcl-new-twenty-20261024.json

[BF24]: smoke-bfcl-24-closure-20261024.json

[T24]: smoke-terminal-24-20261025.json

[TA25]: smoke-terminal-retry-appworld-20261025.json

[SM2]: smoke-swe24-smoke2-20261025.json
[S3]: smoke-searchqa-smoke3-20261025.json



当前验收目标是组合能否跑通，不要求分数提高或稳定提升。核对真实模型调用、候选生成/编辑与实际评估、合法的选择或拒绝、最终 test 和结果落盘；正常的同分拒绝不算失败。分支因 gate 未触发时注明覆盖边界，候选内容质量作为附注，不为追求收益反复加预算重跑。



当前有 **188 个组合完成过真实 smoke**；**8 个准备、进行中或部分覆盖，4 个失败，14 个当前配置不支持，50 个待验证**。✓*保留原生预算或覆盖限制；最新两机证据见 [TA25][TA25]、[SM2][SM2]，历史记录保留。



- **✓**：真实模型运行完成，候选生成/编辑、评估、选择和 test 记录已核对；具体预算和覆盖范围见下方记录。

- **✓†**：有真实完成记录，但随后改动了相关选优规则；新规则通过离线回归，真实复测待补。

- **✓\***：真实运行链路完成，但有已观察到的内容质量或实际使用限制，详见对应记录。

- **△**：完成了准备或部分真实运行，但目标候选/分支覆盖尚未完成；实验可能已正常收尾，原因写入记录。

- **×**：真实运行失败，尚未修复并复测通过。修复后保留失败证据，单独记录复测结果。

- **⊘**：当前接入不满足算法前置条件，已用生产入口验证明确拒绝；没有运行模型，不计为 smoke 通过。

- **—**：尚无已核对的真实 smoke 证据。构造器、单元测试和独立文件编辑探针不计为组合通过。



## 已完成与受阻记录



[SM2][SM2] smoke2 独立验证 SWE-bench24格；状态 {"flow_passed": 16, "flow_failed": 3, "partial": 3, "unsupported": 2}。原始镜像、固定1/1/1及官方评分器；准备不计组合通过。



[TA25][TA25] 当前续跑：{"flow_failed": 12, "flow_passed": 3, "preparation_blocked": 24}。先重试15个未完整通过的Terminal组合，再运行AppWorld24格；原9个完整通过不重复，历史尝试保留。✓*含原生预算终止，仍不是完整通过。新Claude三扩展映射单独验证。



[T24][T24] 本批队列已于北京时间 2026-10-25 07:36 结束：9 格完整通过、4 格含原生轮数终止标注、3 格部分覆盖、5 格失败、2 格环境受阻，另 1 格为旧五模块映射拒绝。ModularRSI/MiniAgent 实验正常收尾并保存最终 test，但首次环境启动超时，变更候选被既定 diff 审查证据预算拒绝，未进入实际评估，核定为部分覆盖，原严格审核失败标记保留于 JSON。Claude Code 新 prompt/skill/hook 三模块配置仅完成本地离线验证，实际 smoke 待跑；旧配置拒绝不代表新配置不支持。未启动新批次，本批临时网络服务已关闭，任务镜像和实验记录保留。



[T24][T24] 当前批次进展：13 格链路通过（其中 4 格含原生预算终止，标 ✓*）、3 格部分覆盖、5 格失败、1 格旧映射不支持、2 格环境受阻、0 格正在运行；其余尚待验证。按单个 Benchmark 顺序执行，原生 1/1/1，Target 预算为 MiniAgent 8 轮、Claude Code 20 轮，输出上限 32768，超时 600 秒；这是链路 smoke，不要求答题成功或演化提分。开发机侧预装官方固定版本 uv/uvx 并缓存运行时下载；任务镜像身份、原始指令与评分脚本不改。每格核对真实模型轨迹、变更候选实际评估、最终 test、原生 pytest、Worker 文件工具访问及既定选优规则；207 个主体源码与资源文件持续校验为原始基线。



[T24][T24] 初始受阻记录：Terminal 本批按 12 算法 × 两个 Target 共 24 格准备，尚未完成整批：OPRO/MiniAgent 在恢复原始源码后的公开入口运行仍因容器依赖代理 403 受阻；ModularRSI/Claude Code 已在原始源码的公开入口确认缺少可编辑运行模块，记 ⊘；其余 22 格待真实验证。原生 89 题及三道固定 train/dev/test 的任务文件与评分器保留，另准备了一道去重后的官方独立 ModularRSI 训练题，MiniAgent 的启动准备通过，但不计真实 smoke 通过。10 次诊断尝试均保留，其中临时基础设施源码版本的尝试仅作诊断，不计当前源码通过。本轮临时环境/网络源码与新增测试已按用户要求全部撤回，207 个框架、算法和 harness 源文件与本轮开始时哈希一致；README 已恢复，Ruff 通过，216 个文件格式检查通过。环境和网络只作为前置条件及受阻记录，基础设施齐全后继续同一批，不为这些问题增加仓库代码分支、重试或兜底。



[BF24][BF24] BFCL按完整24格收尾：20格真实运行通过（18格沿用[BF20][BF20]，本轮新增RRSI两个Target通过）、2格EvoHarness部分覆盖、2格ModularRSI当前接入不支持。本轮7次CLI尝试中5次为真实模型实验、2次仅生产入口前置条件验证，不重复计算已有通过格。EvoHarness两项预先固定seed 43、原生1/1/1（train 38/dev 98/test 121）补测均正常执行并官方评分，训练仍全对，按原生gate跳过编译，保留△；原sealed test 29未移入新训练或dev。RRSI使用原seed 42数据，两个Target均完成真实候选测量、选择和最终test；Claude Code首次digester触及Worker 30轮上限，保留失败后提高至50轮/420秒并限定各1条代表轨迹，复测digest用了37轮后通过，未改算法或评分规则。ModularRSI两Target均由生产CLI在启动时明确拒绝：当前BFCL接入缺少独立演化数据源；五模块映射也未接入，不伪造metadata或合并held-out任务，记⊘。EvoHarness 26项、Docker启动10项离线回归通过，离线结果不代替真实组合验证。228份源码及原生数据校验未变；12份Snapshot、96个Snapshot文件、90份运行文件完成凭据/缓存扫描；161次原生Worker文件工具调用已核对。后续每批固定一个Benchmark的12算法 × 两个Target共24格，下一批Terminal-Bench 2.0。



[BF20][BF20] 本轮20个新组合全部完成验证（BFCL × 10算法 × 两个Target）：18个完整通过、2个EvoHarness部分覆盖，共保留23次真实尝试；最终队列用时约52.6分钟，不含前置环境排查。两项EvoHarness的固定训练题均通过，原生成功gate跳过技能编译，最终test正常但没有变更候选执行，记△。OPRO、SkillOpt、AHE、ACE、EvoPrompt、GEPA、ADAS、DarwinX、MetaHarness两个Target均完成候选实际评估和官方评分。前三次OPRO/MiniAgent的网络/uv下载失败及修复后独立复测均保留。固定任务为train 41、dev 61、test 29；测试只使用最终选版，适用算法的同分保留规则已核对。228份源码与固定原生数据未在最终队列中变化；58份Snapshot、642个Snapshot文件和320份运行文件/日志完成检查，未发现凭据或缓存进入Snapshot；155次原生Worker文件工具调用未见成功越目录或未核实调用。所有任务容器及实验进程已结束，临时VPN代理已关闭。



[NH1][NH1] 新开发机31447的Docker已确认可用：之前漏查平台专用socket而误判；通过 `/var/ebcloud/*/dind/docker.sock` 连接26.1.3 engine，独立容器、网络和构建均已验证。默认socket缺失及SSH容器的mount限制不代表平台engine不可用。官方Python镜像经本地VPN下载并逐层校验；实际BFCL模型调用也使用临时VPN通路。补充了可配置的官方GitHub uv安装源和固定版本uv复用，Linux测试521通过、1跳过，Ruff通过。新环境Docker限制已解除，Terminal/AppWorld/SWE组合仍需实际验证；[T1][T1]保留旧机器的历史受阻证据。



同一组合多次运行只计一个格子。表中行是 Target Agent；Worker 单独记录，不能从 Target 推断 Worker 类型。



追加 [X10][X10] 约25分钟完成10项验证，修复后全部通过：4个 EvoPrompt GA tournament/standard、4个 GEPA current_best/strict、2个 ACE online 两批状态传递。共保留14次真实尝试，包括4次修复前运行；前三次同分误选已撤销通过判定，4项同配置独立复测均通过。复用固定原生数据，ACE 使用已固定的前4条 train、dev/test不变。已有格子不重复计数。



本轮 [H20][H20] 约56分钟完成20项：19项通过、1项部分覆盖，均正常退出且完成最终test。8个OPRO两步/多候选历史、6个GEPA两轮Pareto、4个SkillOpt slow/meta全通过；AHE关闭debugger的Claude Code完成合法编辑及候选执行，MiniAgent因唯一训练题已通过而返回空changes，正确拒绝无变更，未覆盖变更候选执行。固定原生1/1/1，单次上限600秒；不按得分重选数据或强制修改。只补分支、已有格子不重复计数，仍暂缓Docker及既定两个旧同分复测。



本轮 [DE2][DE2] 约10分钟完成4项 EvoPrompt DE 两轮核验，均通过：NQ、2Wiki × 两个 Target，种群4、best donor、固定原生1/1/1。32次实际 Worker DE 提示逐条与当轮冻结父代及最佳 donor 对照，两轮均有变更 trial 实际评估；逐槽记录为31次同分保留、1次退步保留，未观察到严格提分采纳，不据此宣称该采纳分支获得本批真实覆盖。最终都保留历代最早最高 dev 分版本，test在最终选版后只执行一次。本批仅改实验配置、没有源码或数据变更；已有格子不重复计数。



本轮 [M20][M20] 已结束 20 项模式/多轮验证：17 项通过、2 项部分覆盖、1 项超时。8 个 ACE online 与6 个 EvoPrompt DE 全通过；RRSI 两轮中 SearchQA/MiniAgent、2Wiki/Claude Code 完整通过，SearchQA/Claude Code 在第二轮修复时达600秒上限，2Wiki/MiniAgent 首轮被 critic 正确拒绝、第二轮及 test 正常完成；SkillOpt slow/meta 的 Claude Code 完成变更 slow 候选测量及 meta 复用，MiniAgent 两次 slow 均 no_change，相关调用和 meta 复用已验证但变更 slow 候选测量未覆盖。均为固定原生 1/1/1。HotpotQA/Claude Code/ACE 从部分覆盖补为完成，其余已有格子不重复计数；HotpotQA/MiniAgent 的 offline 同分复测仍暂缓，保留 ✓†。本批没有源码变更：183 个基线文件、10 份数据哈希未变，90 份 Snapshot 与562份运行文件/日志完成扫描，312次原生 Worker 文件工具调用未发现成功越目录调用。



本批 [T20][T20] 约 53 分钟完成 20 项验证：19 个新组合与 1 个已有组合的跨批次分支，共 21 次真实尝试（含 ACE 修复后复测）。15 项通过、5 项部分覆盖，新增 14 个完成格子、5 个 △；跨批次项不重复计数。7 个 ACE 中 6 个通过，HotpotQA/Claude Code Curator 返回合法空更新；7 个 GEPA 均通过。SearchQA、NQ 两个 Target 的 4 个 EvoHarness 因固定训练题全对跳过技能编译，记 △；2Wiki/Claude Code 完成技能编译及原生 Skill 自主调用，2Wiki/MiniAgent 另完成跨批次版本传递。此前暂缓的 HotpotQA/MiniAgent/ACE 与 GEPA 旧格子不自动重选。



本轮 [PF1][PF1] 约 20 分钟复测现有 5 个 △，均完成候选评估和最终 test：SearchQA、NQ、2Wiki 的 MiniAgent/RRSI，以及 NQ、2Wiki 的 MiniAgent/ADAS。配置差异核对确认只调整 Worker 输出上限至 8192、ADAS Worker 上限至 30 轮及独立输出目录；原生 1/1/1 样本、Target 配置、算法参数与协议保持一致，单次总上限仍为 600 秒。5 个 △ 更新为 ✓，旧失败证据保留，不据一次成功声称必然消除模型波动。



第四批 [QB4][QB4] 约 60 分钟完成 10 个新组合的验证：7 个通过、3 个部分完成，共 11 次真实尝试（包含一次修复后复测）。3 个 SkillOpt 和 3 个 Claude Code Target 的 RRSI 通过；3 个 MiniAgent Target 的 RRSI 中，2 个触及 4096 输出 token 上限，1 个候选未通过审查，均记 △。2Wiki/MiniAgent/EvoHarness 完成技能生成与最终评估，但 test 未自主读取新技能，记 ✓*。固定 1/1/1，编辑 Worker 使用已有目录受限 Claude Code profile，单次运行上限 600 秒；原始失败记录均保留。



第三批 [QB3][QB3] 约 30 分钟完成 10 个新组合，均跑通：NQ、2Wiki 的 Claude Code Target 各验证 ADAS、AHE、MetaHarness、DarwinX，再验证 SearchQA/Claude Code 与 NQ/MiniAgent 的 SkillOpt。沿用固定 1/1/1，编辑 Worker 使用已有目录受限 profile；新增 10 个完成格子，其中 SearchQA/Claude Code/SkillOpt 标注候选技能未自主调用的限制。



续轮 [CB2][CB2] 已在两小时预算内完成 10 次真实尝试：7 次完成目标流程，2 次 Worker 达轮数上限，1 次候选新增未配置依赖而执行失败。其中一次失败 Worker 还读取了 test 文件，明确列为无效评测。新增 6 个完成格子（2 个由 △ 转为 ✓，4 个原待验证组合通过），SkillOpt 另补合并与排序分支。探针和离线测试不增加组合计数。



| 日期 | 组合 | Worker | 实际覆盖与结果 | 证据 |

| --- | --- | --- | --- | --- |

| 10-19 | SearchQA / MiniAgent / SkillOpt | 文本 LLM | 本地历史实验；train 实际评估 8 题、dev 3 题、test 6 题。fast 候选 dev 0→1/3，获选；test EM 2/3。27 条成功请求记录，0 失败。尚未在当前源码重新跑此组合。 | [S1][S1] |

| 10-23 | SearchQA / MiniAgent / OPRO | 文本 LLM，DeepSeek Flash | 1/1/1，1 个候选；train 1→1，保留原版；test EM 1。 | [Q1][Q1] |

| 10-23 | HotpotQA / MiniAgent / OPRO | 文本 LLM，DeepSeek Flash | context，1/1/1，1 个候选；train 0→1，选择候选；test EM 0、F1 0.8。 | [Q1][Q1] |

| 10-23 | NQ / MiniAgent / OPRO | 文本 LLM，DeepSeek Flash | 原始页面上下文，1/1/1，1 个候选；train 0→1，选择候选；test EM 0。 | [Q1][Q1] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / OPRO | 文本 LLM，DeepSeek Flash | context，1/1/1，1 个候选；train 同分保留原版；test EM 1。 | [W1][W1] |

| 10-23 | HotpotQA / Claude Code / OPRO | 文本 LLM，DeepSeek Flash | context，1/1/1，1 个候选；目标使用官方 Anthropic 兼容接口，Worker 使用 Chat Completions；test EM 0。 | [A1][A1] |

| 10-23 | HotpotQA / MiniAgent / SkillOpt | 文本 LLM，DeepSeek Flash | context，1/1/1；仅 fast update，slow update 关闭。实际生成并评估修改，dev 1→1，按 gate 拒绝；test EM 0。 | [A1][A1] |

| 10-23 | HotpotQA / MiniAgent / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新；生成 playbook 并评估，test EM 0。历史中含同分保留旧版和同分选择新版两次运行；现已恢复保留旧版，回归测试通过，恢复后尚未真实复测。 | [A1][A1]、[D1][D1] |

| 10-23 | HotpotQA / MiniAgent / EvoPrompt | 文本 LLM，DeepSeek Flash | context，1/1/1；GA、种群 2、1 轮；完成种群初始化和子代评估，test EM 0。DE 未测。 | [A1][A1] |

| 10-23 | HotpotQA / MiniAgent / GEPA | 文本 LLM，DeepSeek Flash | context，1/1/1，1 轮；真实反思、候选筛选和 dev 评估完成，test EM 0。最终 dev 同分规则随后恢复为保留先选中的版本；回归测试通过，尚未真实复测。 | [A1][A1]、[D1][D1] |

| 10-23 | HotpotQA / MiniAgent / ADAS | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1，1 个设计，反思 0 次，Worker 上限 30 轮。首轮发现收尾工具标记误判并修复；复测实际修改 9 个文件，dev 1→0，保留原版，test EM 0、F1 0.8。Worker 普通文字说明符合现有无标签回退契约；收尾修复另有确定性回归测试。 | [D1][D1] |

| 10-23 | HotpotQA / MiniAgent / AHE | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1，1 轮，逐题与汇总 debugger 开启，Worker 上限 20 轮。首轮编辑后未交付 JSON manifest，被正确拒绝；补齐带文字前缀的工具标记收尾逻辑后复测，修改 4 个文件、manifest 与差异一致，候选与 test 评估完成，6 条成功请求记录、0 失败。train 1→1，4 项修改均为 INEFFECTIVE，test EM 0、F1 0.8。 | [H1][H1] |

| 10-23 | HotpotQA / MiniAgent / EvoHarness | Agent Worker：MiniAgent，DeepSeek Flash | 前两次 1/1/1 的 train 均答对，正确跳过编译；随后按原始顺序取接下来的 3 条训练样本，3/1/1、1 批次，3 题 EM 均为 0。完成 3 次反思、topic/general 两级编译，新增 1 个 topic 和 3 个 general SKILL.md，来源与权限校验通过，9 条成功请求记录、0 失败。test EM 0、F1 0.8；技能目录可见，但 test 未调用 read_skill。独立真实探针重新加载最终 Snapshot 后成功读取技能正文。技能含训练案例与 ID，质量限制见下文。 | [E1][E1] |

| 10-23 | HotpotQA / MiniAgent / MetaHarness | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1，1 次提案，Worker 上限 20 轮；6 次工具调用涉及历史目录，修改 prompt、runtime、skill 共 3 个文件。dev 1→0，保留初始版本；test EM 0、F1 0.5。所有调用完成，Snapshot 不含历史目录；多候选历史复用未测。 | [M1][M1] |

| 10-23 | HotpotQA / MiniAgent / DarwinX | Agent Worker：MiniAgent，DeepSeek Flash | 3/1/1，1 次 mutation，screen_size=1，筛选与确认各 1 次，关闭重组。初始 train 1/3；配对确认 parent 0、candidate 2/3，候选满足 gain/regression/invariant gate 后选中。test EM 0、F1 0.8。所有调用完成；单次确认存在波动，未验证多次置信度与互补分支重组。 | [DX1][DX1] |

| 10-23 | HotpotQA / MiniAgent / RRSI | Agent Worker：MiniAgent，DeepSeek Flash | 共 5 次尝试，先 1/1/1 后 3/1/1；T=1/k=2/m=1。修复摘要引用说明、累计清单提示和缺失路径错误。一轮因反复追问未提供的试验而外部中止；明确代表轨迹范围后，最后一轮一批摘要即完成分析。候选仍因漏报/超预算清单被拒，未进入测量。另修复说明文字中未闭合标签干扰 JSON 的解析问题：真实回复离线重放可解析，但仍拒绝漏报的 3 个文件；不改写原始结果。最后 test EM 0、F1 0.8 使用原版，记 △。 | [R1][R1] |

| 10-23 | HotpotQA / Claude Code / EvoPrompt | 文本 LLM，DeepSeek Flash | context，1/1/1；GA、种群 2、1 轮。3 个不同 CLAUDE.md 候选完成评估，dev 均为 1，保留初始版本；test EM 0、F1 2/3。所有调用完成，DE 未测。 | [EC1][EC1] |

| 10-23 | HotpotQA / Claude Code / SkillOpt | 文本 LLM，DeepSeek Flash | context，1/1/1，仅 fast。首次配置关闭 Skill 工具，补开后一次 Worker JSON 格式失败，原配置新目录重试完成。新增技能候选 dev 1→1，拒绝同分；test EM 0、F1 0.8。候选 dev 未自主调用 Skill；独立原生探针成功调用 Skill 并读出技能正文，故记 ✓*，不声称自主复用。 | [SC1][SC1] |

| 10-23 | HotpotQA / Claude Code / ADAS | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1；1 个设计、反思 0 次、Worker 上限 20 轮。实际修改 CLAUDE.md 与 skills/main.md，候选 dev 1→1，严格 admission 拒绝同分，保留原版；test EM 0、F1 0.8。所有调用完成；只核实 CLAUDE.md 指令加载，未把非原生布局的 skills/main.md 算作技能加载通过。 | [AC1][AC1] |

| 10-23 | HotpotQA / Claude Code / AHE | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1，1 轮，debugger 开启，target_score=1.01 强制执行编辑。manifest 覆盖两个修改，train 1→1，两项均 INEFFECTIVE；按 AHE 原规则保留，test EM 0、F1 0.6。Stop hook 注册并执行成功，但目录 guard 直接退出，预期收尾检查未触发；skills/main.md 也不是原生技能布局。链路完成但候选机制实际无效，记 ✓*。 | [HC1][HC1] |

| 10-23 | HotpotQA / Claude Code / MetaHarness | Agent Worker：MiniAgent，DeepSeek Flash | context，1/1/1，1 次提案。首次 20 轮只读取未修改；30 轮预算复测在 12 轮内生成候选，dev 1→1，候选进入 archive，最终保留初始版本；test EM 0、F1 0.5。历史目录读取与隔离通过，版本指令加载通过；多轮历史复用未测。 | [MC1][MC1] |

| 10-23 | HotpotQA / Claude Code / DarwinX | Agent Worker：MiniAgent，DeepSeek Flash | context，3/1/1，1 次 mutation，screen/confirm 各 1 次，关闭重组。20 轮和 30 轮 Worker 两次均未改文件，算法正确拒绝空候选；基线 train 1/3，后一次 test EM 0、F1 0.8。候选 screen/confirmation 未执行，记 △，不继续堆预算重试。 | [DC1][DC1] |

| 10-23 | HotpotQA / Claude Code / EvoHarness | Agent Worker：MiniAgent，DeepSeek Flash | context，3/1/1，1 批次。train EM 1/3，2 次失败反思；topic 编译新增 1 个原生 SKILL.md，general 编译因只有 2 个支持任务未修改（默认门槛 3）。最终 test 自主调用 Skill 加载新技能，EM 0、F1 0.8；技能正文保留训练题具体短语与 alcohol 答案例子，记 ✓*，不声称泛化提升。 | [EHC1][EHC1] |

| 10-23 | HotpotQA / Claude Code / RRSI | Agent Worker：MiniAgent，DeepSeek Flash | context，3/1/1，T=1/k=2/m=1，编辑预算 1、修复 2 次、Worker 上限 30 轮。基线均值 1/3；三类摘要通过，首个提案清单有效并进入 critic，但被判过度贴近训练题；两次修复又分别声明未变化路径、漏报 hooks/hooks.json。尚无候选进入测量；test EM 0、F1 0.8 使用原版，记 △。 | [RC1][RC1] |

| 10-23 | SearchQA / Claude Code / OPRO | 文本 LLM，DeepSeek Flash | 原生 snippets context，1/1/1，1 个 CLAUDE.md 候选；train 1→1，同分保留原版，dev 仅加载。test EM 1、F1 1；所有调用完成，候选指令加载验证通过。远程自动下载未测。 | [QC1][QC1] |

| 10-23 | NQ / Claude Code / OPRO | 文本 LLM，DeepSeek Flash | 原始页面 context，1/1/1，1 个 CLAUDE.md 候选；train 1→0，拒绝候选并保留原版。test EM 0、F1 0；所有调用完成，候选指令加载验证通过。 | [QC1][QC1] |

| 10-23 | 2WikiMultiHopQA / Claude Code / OPRO | 文本 LLM，DeepSeek Flash | 固定原生 validation.parquet、context/answer_text、1/1/1、seed=42，1 个 CLAUDE.md 候选；train 0→0，同分保留原版。test EM 1、F1 1；所有调用完成，候选指令加载验证通过。 | [QC1][QC1] |

| 10-23 | SearchQA / MiniAgent / EvoPrompt | 文本 LLM，DeepSeek Flash | 原生分区 context，1/1/1；GA、种群 2、1 轮。初始 dev 0，初始化生成的候选 dev 1，两个子代 dev 均为 0；选择已评估的初始化候选，test EM 1、F1 1。全部调用完成；DE 未测，单题变化不代表正式收益。 | [SQ2][SQ2] |

| 10-23 | SearchQA / Claude Code / EvoPrompt | 文本 LLM，DeepSeek Flash | 原生分区 context，1/1/1；GA、种群 2、1 轮。3 个不同 CLAUDE.md 候选 dev EM 均为 0，与初始版本同分，保留初始版本；test EM 1、F1 1。全部调用完成，版本指令实际加载通过；DE 未测。 | [SQ2][SQ2] |

| 10-23 | SearchQA / MiniAgent / ADAS | Agent Worker：MiniAgent，DeepSeek Flash | 原生分区 context，1/1/1，1 个设计、反思 0 次。Worker 在 30 轮上限内用 23 轮修改 9 个文件；候选 dev 0→0，同分保留原版，test EM 1、F1 1。所有调用完成；候选直接作答，新增证据笔记工具未实际调用，多设计历史与反思分支未测。 | [SQ2][SQ2] |

| 10-23 | SearchQA / MiniAgent / AHE | Agent Worker：MiniAgent，DeepSeek Flash | 原生分区 context，1/1/1，1 轮、debugger 开启、target_score=1.01。Worker 上限 20 轮，修改 runtime/workspace.py；manifest 合法，候选 train 1→1，唯一改动为 INEFFECTIVE，按 AHE 原规则保留，test EM 1、F1 1。所有调用完成，未观察到收益。 | [SQ2][SQ2] |

| 10-23 | SearchQA / MiniAgent / MetaHarness | Agent Worker：MiniAgent，DeepSeek Flash | 原生分区 context，1/1/1，1 次提案，Worker 上限 20 轮。10 次工具调用涉及历史目录，修改 7 个文件；候选 dev 0→1 并获选，test EM 1、F1 1。Snapshot 未包含历史目录；候选/test 直接作答，新增 inspect_context 工具未调用，多候选历史复用未测。单题变化不代表正式收益。 | [SQ2][SQ2] |

| 10-23 | SearchQA / MiniAgent / DarwinX | Agent Worker：MiniAgent，DeepSeek Flash | 原生分区 context，1/1/1，1 次 mutation，screen/confirm 各配置 1 次，关闭重组。修改 prompt/runtime/skill 3 个文件；screen parent/candidate 均为 1，同分拒绝，未进入 confirmation；完成经验提取，保留初始版本，test EM 1、F1 1。生成的短答案清理函数离线重放会破坏 JSON 字符串引号，记 ✓*；候选未选中，未合入源码。 | [SQ2][SQ2] |

| 10-23 | NQ / MiniAgent / EvoPrompt | 文本 LLM，DeepSeek Flash | 原始页面 context，1/1/1；GA、种群 2、1 轮。初始化和两个子代共 3 个变更候选完成评估，dev 均为 0，同分保留原版；test EM 0。全部调用和落盘完成，DE 分支未测。 | [NQ3][NQ3] |

| 10-23 | NQ / Claude Code / EvoPrompt | 文本 LLM，DeepSeek Flash | 原始页面 context，1/1/1；GA、种群 2、1 轮。3 个 CLAUDE.md 变更候选完成评估，dev 同分保留原版；test EM 1。全部调用完成，版本指令实际加载通过；DE 分支未测。 | [NQ3][NQ3] |

| 10-23 | NQ / MiniAgent / ADAS | Agent Worker：MiniAgent，DeepSeek Flash | 原始页面 context，1/1/1，1 个设计、反思 0 次、Worker 上限 30 轮。Worker 正常结束但未修改文件，空设计被正确拒绝；最终 test 完成、EM 0。流程正常退出，尚未覆盖变更候选加载与评估，记 △；不加预算追求修改或收益。 | [NQ3][NQ3] |

| 10-23 | NQ / MiniAgent / AHE | Agent Worker：MiniAgent，DeepSeek Flash | 原始页面 context，1/1/1，1 轮、逐题与汇总 debugger、target_score=1.01。Worker 在 20 轮上限内用 11 轮完成编辑；manifest 校验、变更候选评估与保留、最终 test 全部完成。train EM 0→0，test EM 0；按运行链路判定通过，不要求分数改善。 | [NQ3][NQ3] |

| 10-23 | NQ / MiniAgent / MetaHarness | Agent Worker：MiniAgent，DeepSeek Flash | 原始页面 context，1/1/1，1 次提案、Worker 上限 20 轮。实际变更候选完成 dev 评估并进入 archive；dev 同分保留原版，最终 test EM 0。全部调用、选择与落盘完成，历史目录未混入 Snapshot；多提案历史复用未测。 | [NQ3][NQ3] |

| 10-23 | NQ / MiniAgent / DarwinX | Agent Worker：MiniAgent，DeepSeek Flash | 原始页面 context，1/1/1，1 次 mutation，screen/confirm 各 1 次，关闭重组。Worker 10 轮完成编辑；筛选和配对确认 parent 0、candidate 1，候选获准进入 archive；最终与初始基线最高分同分，保留原版。经验提取、最终选择和 test 完成，test EM 0；重组分支未测。 | [NQ3][NQ3] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / EvoPrompt | 文本 LLM，DeepSeek Flash | 固定原生 validation.parquet，context/answer_text、seed=42、1/1/1；GA、种群 2、1 轮。3 个变更候选完成 dev 评估，保留原版；test EM 1。所有调用及落盘完成，DE 未测；无需搜索 API，未验证联网搜索。 | [W4][W4] |

| 10-23 | 2WikiMultiHopQA / Claude Code / EvoPrompt | 文本 LLM，DeepSeek Flash | 固定原生 validation.parquet，context/answer_text、seed=42、1/1/1；GA、种群 2、1 轮。3 个 CLAUDE.md 候选完成加载和 dev 评估，同分保留原版；test EM 1。全部调用和落盘完成，DE 未测；未验证联网搜索。 | [W4][W4] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / ADAS | Agent Worker：MiniAgent，DeepSeek Flash | context/answer_text、seed=42、1/1/1，1 个设计、反思 0 次，Worker 上限 30 轮。Worker 正常结束但未修改文件，空设计被正确拒绝；最终 test 完成、EM 1。变更候选加载与评估尚未覆盖，记 △；未加预算重试。 | [W4][W4] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / AHE | Agent Worker：MiniAgent，DeepSeek Flash | context/answer_text、seed=42、1/1/1，1 轮、debugger 开启、Worker 上限 20 轮。manifest 声明 3 个修改，实际只改 middleware/answer_form_check.py，候选被正确拒绝；最终 test 完成、EM 1。全部调用正常，但候选执行未覆盖，记 △；未放宽校验或重跑。 | [W4][W4] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / MetaHarness | Agent Worker：MiniAgent，DeepSeek Flash | context/answer_text、seed=42、1/1/1，1 次提案、Worker 上限 20 轮。实际变更候选完成评估并入 archive，保留原版，最终 test EM 1。全部调用、选择和落盘完成，历史目录未混入 Snapshot；多提案历史复用及联网搜索未测。 | [W4][W4] |

| 10-23 | 2WikiMultiHopQA / MiniAgent / DarwinX | Agent Worker：MiniAgent，DeepSeek Flash | context/answer_text、seed=42、1/1/1，1 次 mutation，screen/confirm 各 1 次，关闭重组。Worker 19 轮完成编辑；实际候选通过筛选和配对确认后获选，经验提取、最终选择、test 和落盘完成，test EM 1；重组及联网搜索未测。 | [W4][W4] |

| 10-23 | HotpotQA / MiniAgent / SkillOpt（补分支） | 文本 LLM，DeepSeek Flash | context，1/1/1，3 个单 batch epoch，edit_budget=1；fast/slow/meta 全开。3 次 fast 候选评估、2 次 slow 提案和 2 次 meta 提炼完成；首个 slow 候选含受保护指导区并完成 dev 评估，第二次为 no_change。已核对 epoch 2 的 meta 文本进入 epoch 3 反思提示；同分保留原版，test 完成。补已有格子的覆盖，不增加组合计数。 | [SF1][SF1] |

| 10-23 | HotpotQA / Claude Code / SkillOpt（补分支） | 文本 LLM，DeepSeek Flash | context，1/1/1，3 个单 batch epoch，fast/slow/meta 全开。独立 source_dir 预置通用原生技能，用于满足 slow 只改已有技能的前提，不改默认 Agent。2 个 fast 和 2 个 slow 变更候选完成评估，第三次 fast 为空；meta 文本确实进入下一 epoch。fast 候选和第二个 slow 候选评估中实际调用原生 Skill；最终 test 未调用。所有调用完成，同分保留初始版本。补已有格子，不增加组合数。 | [SF1][SF1] |

| 10-23 | HotpotQA / MiniAgent / EvoHarness（跨批次） | Agent Worker：MiniAgent，DeepSeek Flash | 固定 3/1/1，batch_size=1、max_steps=3。第一批生成 topic skill，第二、三批训练实际使用其 Snapshot；第三批修订因引用前批次 task ID 被拒，general 因支持任务不足被拒。全部调用和 test 完成；覆盖版本跨批传递，未覆盖成功修订/合并/删除。 | [ES1][ES1] |

| 10-23 | HotpotQA / Claude Code / EvoHarness（跨批次） | Agent Worker：MiniAgent，DeepSeek Flash | 相同固定 3/1/1、三个单题 batch。首批编译未改文件，第三批才生成 topic skill，最终 test 完成；新技能后没有后续 train batch，跨训练批次复用尚未覆盖。所有调用正常，保留现有单批次完成记录，不新增格子或冒充复用通过。 | [ES1][ES1] |

| 10-23 | HotpotQA / MiniAgent / RRSI（累计差异复测） | Agent Worker：MiniAgent，DeepSeek Flash | 固定 3/1/1、T1/k2/m1、编辑预算 1、修复 2 次、Worker30。修复时提供 current-diff.txt，保持原校验；首次清单声明未变化路径，第二次通过清单后被 critic 拒绝。第三次编辑完成，但下一次 critic 仍在执行时达到外部 600 秒上限而中止。未进入候选测量、未完成最终 test；未落盘调用用量未知，保留 △。 | [RD1][RD1] |

| 10-23 | HotpotQA / Claude Code / RRSI（累计差异复测） | Agent Worker：MiniAgent，DeepSeek Flash | 固定 3/1/1、T1/k2/m1、编辑预算 1、修复 2 次、Worker30。前两次提案清单均通过并进入 critic 后被拒，最后一次清单含多个独立编辑，超预算被拒；未进入候选测量，最终 test 正常完成。部分 critic 理由混淆归因清单与源码泄漏，另行澄清提示，原始拒绝不改写。仍记 △。 | [RD1][RD1] |

| 10-23 | HotpotQA / Claude Code / DarwinX（原生 Worker） | Agent Worker：Claude Code，DeepSeek Flash | 固定 3/1/1，1 次 mutation，screen/confirm 各配置 1 次，关闭重组；Worker 上限 20 轮，使用原生文件工具。实际生成变更候选并进入 screen，parent/candidate 均为 0，同分拒绝，未进入 confirmation；经验提取和最终 test 完成。此前 MiniAgent Worker 的空编辑记录保留，本次将该组合由 △ 更新为 ✓。 | [NW1][NW1] |

| 10-23 | HotpotQA / Claude Code / RRSI（原生 Worker） | Agent Worker：Claude Code，DeepSeek Flash | 固定 3/1/1、T1/k2/m1、编辑预算 1、修复 2 次、Worker 配置 20 轮。累计差异证据及 critic 归因边界澄清后，变更候选通过审查和 smoke gate，完成两次 trial 测量、选中版本及最终 test。全部调用完成，test EM 0、F1 0.5；未放宽 gate。将此组合由 △ 更新为 ✓，多候选、探索和剪枝未测。 | [NW1][NW1] |

| 10-23 | HotpotQA / Claude Code / EvoHarness（后续训练批） | Agent Worker：MiniAgent，DeepSeek Flash | 4/1/1、四个单题 batch；在既定三条训练记录后接入原先已准备的独立 train 记录，未按答案筛选。生成的 topic skill Snapshot 实际传入后续 train，完整 stream 和最终 test 完成；覆盖版本跨批次传递，技能正文是否自主读取单独看原生工具记录，未强制调用。 | [ES1][ES1] |

| 10-23 | HotpotQA / MiniAgent / EvoPrompt（DE） | 文本 LLM，DeepSeek Flash | context、1/1/1，DE 种群 4、1 代，默认 best-base donor。3 个初始化候选、3 个变更 trial 实际评估；另 1 个 trial 未变，复用已有分数。四个位置的选择及最终 test 完成，同分保留原版。补 DE 分支，不增加组合计数；随机 donor 与多代未测。 | [DE1][DE1] |

| 10-23 | HotpotQA / Claude Code / EvoPrompt（DE） | 文本 LLM，DeepSeek Flash | context、1/1/1，DE 种群 4、1 代，默认 best-base donor。3 个初始化候选和 4 个变更 trial 实际评估；全部调用、四个位置的选择及最终 test 完成，版本中的 CLAUDE.md 实际传入。补 DE 分支，不增加组合计数；随机 donor 与多代未测。 | [DE1][DE1] |

| 10-23 | HotpotQA / MiniAgent / SkillOpt（多提案合并） | 文本 LLM，DeepSeek Flash | 固定 3/1/1，单轮、3 题 batch、逐题反思、编辑预算 1、merge_batch_size=2；2 次 failure、1 次 success 反思后，实际执行 failure 组内合并及 failure_first 跨组合并。合并后仅 1 项编辑，未触发 rank；变更候选评估、同分拒绝和最终 test 完成。补合并分支，不增加组合计数。 | [SM1][SM1] |

| 10-23 | Terminal-Bench 2.0 / MiniAgent / OPRO | 未执行模型调用 | 89 个原生任务目录准备完成；数据加载、Harbor 绑定、算法初始化通过。Docker daemon/socket 不可达，真实容器任务和模型调用均为 0，按用户要求暂缓。 | [T1][T1] |

| 10-23 | HotpotQA / MiniAgent / RRSI（原生 Worker 续测） | Agent Worker：Claude Code，DeepSeek Flash | 固定 3/1/1、T1/k2/m1、编辑预算 1、修复 2 次，Worker20；首次 critic 拒绝后修复通过，smoke gate 和两次候选 trial 完成，选中候选并完成最终 test（EM 0、F1 0.8）。全部调用正常，△ 更新为 ✓；多候选、探索与剪枝仍未测。远程等价常量写法单独记录源码哈希。 | [CB2][CB2] |

| 10-24 | NQ / MiniAgent / ADAS（原生 Worker，未隔离） | Agent Worker：Claude Code，DeepSeek Flash | 固定 1/1/1、单轮、Worker20。Worker 达轮数上限，未完成编辑与候选评估；轨迹显示其越过 checkout 读取原生 test.json 及答案元数据，此运行违反 sealed test 边界，不能作为有效评测。保留历史 △，另建受限 Worker 配置复测，不复用此次会话。 | [CB2][CB2] |

| 10-24 | NQ / MiniAgent / ADAS（目录受限 Worker） | Agent Worker：Claude Code，DeepSeek Flash | 固定 1/1/1、单轮、Worker20；原生 hook profile 下完成真实文件编辑，逐项核对工具调用未成功越界。候选自行启用未配置 endpoint 的 web_search，执行报错；框架记录失败，保留原版并完成最终 test。维持 △，未把候选新增依赖误算为原生 context benchmark 要求。 | [CB2][CB2] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / ADAS（目录受限 Worker） | Agent Worker：Claude Code，DeepSeek Flash | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，单轮、Worker20。原生文件工具策略下 Worker 达到轮数上限，未返回完整设计，候选评估及最终 test 未完成；保留 △，未增加预算或复用未完成编辑。 | [CB2][CB2] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / AHE（目录受限 Worker） | Agent Worker：Claude Code，DeepSeek Flash | 固定 1/1/1、单轮、debugger 开启、target_score=1.01，Worker20。清单与实际编辑一致，变更候选正常执行，train keep 决策和最终 test 完成；全部调用正常，工具访问核对通过。△ 更新为 ✓；本次 test EM/F1 为 1，不据单题声称泛化提升。 | [CB2][CB2] |

| 10-24 | SearchQA / Claude Code / ADAS | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生分区 1/1/1、单轮、num_reflections=0、Worker20。实际变更候选完成 dev 评估和 archive 登记，同分保留原版，最终 test 完成；全部调用正常，版本指令传入和工具访问核对通过。新增 ✓；多轮 archive 反馈与自反思未测。 | [CB2][CB2] |

| 10-24 | SearchQA / Claude Code / AHE | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生分区 1/1/1、单轮、debugger 开启、target_score=1.01、Worker20。实际编辑与清单通过，候选 train 评估、keep 决策、最终 test 完成；AHE 按原有 train 规则保留合法同分编辑，不涉及 dev 同分选新版。全部调用及工具访问核对通过，新增 ✓。 | [CB2][CB2] |

| 10-24 | SearchQA / Claude Code / MetaHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生分区 1/1/1、单轮提案、Worker20。历史证据置于 checkout 内可读，变更候选完成 dev 评估、选中并完成最终 test；历史目录未进入 Snapshot，所有调用和工具访问核对通过。新增 ✓；多轮历史增长未测，单题分数不代表稳定提升。 | [CB2][CB2] |

| 10-24 | SearchQA / Claude Code / DarwinX | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生分区 1/1/1、1 次 mutation、screen/confirm 各配置 1 次、关闭重组，Worker20。变更候选实际执行 screen，与 parent 同分被拒，未进入 confirmation；经验提取、最终 test 和工具访问核对通过，新增 ✓。 | [CB2][CB2] |

| 10-24 | HotpotQA / Claude Code / SkillOpt（合并与排序） | 文本 LLM，DeepSeek Flash | 固定 3/1/1、单轮、逐题反思、edit_budget=1、merge_batch_size=2，使用独立通用 context-qa 初始技能。2 次失败、1 次成功反思后，组内合并、跨组合并及 rank 均实际执行；选出 1 项编辑，完成候选 dev 评估、同分拒绝与最终 test。补分支不新增格子；生成技能的自主调用另看工具记录。 | [CB2][CB2] |

| 10-24 | NQ / Claude Code / ADAS | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context、1/1/1、单轮、num_reflections=0、Worker20。变更候选实际评估并进入 archive，同分保留原版，最终 test 完成；调用、版本指令和工具访问核对通过。新增 ✓；多轮 archive 与自反思未测。 | [QB3][QB3] |

| 10-24 | NQ / Claude Code / AHE | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context、1/1/1、单轮、debugger 开启、target_score=1.01、Worker20。清单通过，候选正常执行；train 由 1 降为 0，记录 pass_to_fail，按 AHE 原生“保留合法编辑并反馈逐项结果”规则保留，最终 test 完成。新增 ✓，不声称提升或改动 gate；Worker 对截断证据的缺陷推断不等于实际运行错误。 | [QB3][QB3] |

| 10-24 | NQ / Claude Code / MetaHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context、1/1/1、单轮提案、Worker20。变更候选实际评估、选中并完成最终 test；历史未进入 Snapshot，调用、版本指令及工具访问核对通过。新增 ✓；多轮历史增长和生成扩展的自主使用不从此推断。 | [QB3][QB3] |

| 10-24 | NQ / Claude Code / DarwinX | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context、1/1/1、1 次 mutation、screen/confirm 各配置 1 次、关闭重组，Worker20。变更候选实际执行 screen，同分拒绝，未进入 confirmation；经验提取、最终 test、版本指令和工具访问核对通过。新增 ✓。 | [QB3][QB3] |

| 10-24 | 2WikiMultiHopQA / Claude Code / ADAS | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1、单轮、num_reflections=0，Worker20。变更候选完成 dev 评估、archive 登记、同分保留原版和最终 test；全部调用、版本指令及工具访问核对通过。新增 ✓；与 MiniAgent Target 的部分完成记录分开。 | [QB3][QB3] |

| 10-24 | 2WikiMultiHopQA / Claude Code / AHE | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context/answer_text、seed=42、1/1/1、单轮、debugger 开启、target_score=1.01、Worker20。清单与实际编辑通过，候选评估、keep 决策和最终 test 完成；全部调用、版本指令及工具访问核对通过，新增 ✓。 | [QB3][QB3] |

| 10-24 | 2WikiMultiHopQA / Claude Code / MetaHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 context/answer_text、seed=42、1/1/1、单轮提案、Worker20。变更候选实际评估、archive 登记、同分保留原版及最终 test 完成；历史目录未进入 Snapshot，调用、版本指令和工具访问核对通过。新增 ✓；多轮历史未测。 | [QB3][QB3] |

| 10-24 | 2WikiMultiHopQA / Claude Code / DarwinX | Agent Worker：Claude Code，DeepSeek Flash；目录受限 profile | 固定 1/1/1，1 次 mutation；修改 CLAUDE.md 和原生 context-qa 技能。screen 候选 EM 0，被 gate 拒绝，未进入 confirmation；最终保留原版，test EM 1。全部调用完成、版本指令加载通过；本次 Target 未调用 Skill。 | [QB3][QB3] |

| 10-24 | SearchQA / Claude Code / SkillOpt | 文本 LLM，DeepSeek Flash | 固定原生 1/1/1，仅 fast，沿用独立通用 context-qa 初始技能。实际修改 SKILL.md，dev 1→0，被 gate 拒绝；最终原版 test EM 1。train 与最终 test 自主调用初始 Skill，但候选 dev 未调用修改后的 Skill，故记 ✓*；不声称新技能自主复用。slow/meta 与合并排序未测。 | [QB3][QB3] |

| 10-24 | NQ / MiniAgent / SkillOpt | 文本 LLM，DeepSeek Flash | 固定原始页面 context，1/1/1，仅 fast。生成并评估技能修改，dev 0→0，同分被 gate 拒绝；最终原版 test EM 0。全部 Target/Worker 调用完成、最终 test 与选中版本一致；slow/meta 与合并排序未测。 | [QB3][QB3] |

| 10-24 | NQ / Claude Code / SkillOpt | 文本 LLM，DeepSeek Flash | 固定页面 context，1/1/1，仅 fast。修改 context-qa 原生技能，候选 dev 自主调用该 Skill，EM 0→0，被 gate 拒绝；最终原版 test EM 0。全部调用完成、版本指令加载核对通过；slow/meta 与合并排序未测。 | [QB4][QB4] |

| 10-24 | 2WikiMultiHopQA / Claude Code / SkillOpt | 文本 LLM，DeepSeek Flash | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，仅 fast。修改原生 context-qa 技能，候选 dev 自主调用修改后的 Skill；dev 1→1，同分被 gate 拒绝，最终原版 test EM 1。全部调用完成、版本指令加载通过；slow/meta 与合并排序未测。 | [QB4][QB4] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / SkillOpt | 文本 LLM，DeepSeek Flash | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，仅 fast。实际修改并评估 skills/main.md，dev 1→0，被 gate 拒绝；最终原版 test EM 1。全部调用完成、最终 test 与选中版本一致；slow/meta 与合并排序未测。 | [QB4][QB4] |

| 10-24 | SearchQA / Claude Code / RRSI | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原生 1/1/1，T=1/k=2/m=1，编辑预算 1、repair_rounds=2。新增 CLAUDE.md，通过 critic 和 smoke，完成两次候选测量；train EM 同为 1，成本增加，按 score/cost/novelty gate 拒绝，最终原版 test EM 1。全部调用完成、版本指令加载通过；两次越界 Glob 被原生 hook 拒绝，无成功越界文件调用。 | [QB4][QB4] |

| 10-24 | SearchQA / MiniAgent / RRSI | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原生 1/1/1，T=1/k=2/m=1，编辑预算 1、repair_rounds=2。首次候选被 critic 指出可能把题目文字误当答案，完成一次修复后，后续 Worker 调用触及 4096 输出 token 上限并报错。候选重复测量及最终 test 未完成，记 △；保留错误与修复记录，不放宽协议或增加预算重试。 | [QB4][QB4] |

| 10-24 | NQ / Claude Code / RRSI（修复前） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 1/1/1，T=1/k=2/m=1。基线完成；digester 读取单行 trace.json 时触及 Read 25000-token 文件限制，Grep 省略长行，20 轮耗尽。候选编辑、测量与最终 test 未完成，记 △。已定位证据布局问题：改用分行 JSON，另建目录复测，原记录保留。 | [QB4][QB4] |

| 10-24 | NQ / Claude Code / RRSI（分行证据修复后） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 新目录、原样本及原预算 1/1/1、T=1/k=2/m=1 复测。digester 完成；修改 CLAUDE.md，经一次修复通过 critic 和 smoke，完成两次候选测量，均 EM 0，按 gate 保留原版；最终 test EM 0。全部调用与文件访问核对通过，△ 更新为 ✓；原始失败证据保留。 | [QB4][QB4] |

| 10-24 | NQ / MiniAgent / RRSI | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原生 1/1/1，T=1/k=2/m=1，使用分行轨迹修复。digester 完成；候选被 critic 要求修复，修复后下一次 Worker 调用触及 4096 输出 token 上限。候选重复测量及最终 test 未完成，记 △；保留完整失败记录，未增预算重试。 | [QB4][QB4] |

| 10-24 | 2WikiMultiHopQA / Claude Code / RRSI | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，T=1/k=2/m=1。修改 CLAUDE.md，通过 critic 和 smoke，完成两次候选测量（均 EM 1），通过 gate 并选中，最终 test EM 1。全部调用、版本指令加载及目录访问核对通过；单轮单题不代表稳定收益。 | [QB4][QB4] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / RRSI | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，T=1/k=2/m=1，repair_rounds=2。分析、编辑及修复均完成，但候选先后未通过 critic 或编辑清单约束，未进入重复测量；最终原版 test EM 1。退出码 0、调用正常，但候选执行覆盖不足，记 △。 | [QB4][QB4] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，batch_size=1/max_steps=1。train EM 0，完成反思并新增 topic SKILL.md；general 未产生有效变更。更新后 Snapshot 的最终 test EM 1，但 Target 未自主读取新技能，记 ✓*；单题不覆盖三任务 general 门槛及跨批次复用。 | [QB4][QB4] |

| 10-24 | SearchQA / MiniAgent / RRSI（输出预算复测） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生 1/1/1，T=1/k=2/m=1，Worker 输出上限 8192、20 轮。修改 skills/main.md，通过审查与 smoke，完成两次候选测量及最终 test（EM 1）；全部调用及目录访问核对通过。旧输出超限记录保留，△ 更新为 ✓；单轮不覆盖长期历史与退火。 | [PF1][PF1] |

| 10-24 | NQ / MiniAgent / RRSI（输出预算复测） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生页面 context、1/1/1，T=1/k=2/m=1；Worker 输出上限 8192、20 轮。修改 skills/main.md，候选通过审查和 smoke，完成两次测量与最终 test（EM 0）。全部调用和目录访问核对通过；旧输出超限记录保留，△ 更新为 ✓，不声称收益。 | [PF1][PF1] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / RRSI（预算复测） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1，T=1/k=2/m=1；Worker 输出上限 8192、20 轮。修改 skills/main.md，本次候选通过原有审查和 smoke，完成两次测量与最终 test（EM 1）。全部调用和目录访问核对通过，△ 更新为 ✓；上轮审查失败证据保留，不归因于确定性效果提升。 | [PF1][PF1] |

| 10-24 | NQ / MiniAgent / ADAS（编辑预算复测） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原始页面 context、1/1/1，单轮设计、num_reflections=0；Worker 输出上限 8192、30 轮。实际修改配置、prompt、skill、中间件与本地工具等 8 个文件，候选正常完成 dev 评估和 archive 登记，最终 test EM 0。全部调用与目录访问核对通过，未重现外部搜索未配置错误，△ 更新为 ✓；不从候选执行推断每个新工具已被自主调用。 | [PF1][PF1] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / ADAS（编辑预算复测） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定 validation.parquet、context/answer_text、seed=42、1/1/1；单轮设计、num_reflections=0，Worker 输出上限 8192、30 轮。实际修改配置、prompt、skill、中间件和工具等 11 个文件，候选正常完成 dev 评估和 archive 登记，最终 test EM 1。全部调用及目录访问核对通过，△ 更新为 ✓；未验证每个新工具、中间件或联网服务实际触发。 | [PF1][PF1] |

| 10-24 | SearchQA / MiniAgent / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [0.0, 1.0]。变更候选实际评估，选中变更版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | SearchQA / Claude Code / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [0.0, 0.0]。变更候选实际评估，保留初始版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | NQ / MiniAgent / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [0.0, 0.0]。变更候选实际评估，保留初始版本，最终 test EM 0.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | NQ / Claude Code / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [0.0, 0.0]。变更候选实际评估，保留初始版本，最终 test EM 0.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [0.0, 1.0]。变更候选实际评估，选中变更版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [1.0, 1.0]。变更候选实际评估，保留初始版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | HotpotQA / Claude Code / ACE | 文本 LLM，DeepSeek Flash | offline，1/1/1，1 次更新、edit_budget=1、反思 1 轮；dev 评估 [1.0, 1.0]。本次覆盖不足：candidate_not_evaluated，最终 test EM 0.0；不计完整通过。 | [T20][T20] |

| 10-24 | SearchQA / MiniAgent / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 1.0→1.0，候选 dev [0.0]。变更候选实际评估，保留初始版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | SearchQA / Claude Code / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 1.0→1.0，候选 dev [1.0]。变更候选实际评估，选中变更版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | NQ / MiniAgent / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 1.0→1.0，候选 dev [0.0]。变更候选实际评估，保留初始版本，最终 test EM 0.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | NQ / Claude Code / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 0.0→0.0，候选 dev [0.0]。变更候选实际评估，保留初始版本，最终 test EM 0.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 0.0→0.0，候选 dev [1.0]。变更候选实际评估，保留初始版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 0.0→1.0，候选 dev [1.0]。变更候选实际评估，保留初始版本，最终 test EM 1.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | HotpotQA / Claude Code / GEPA | 文本 LLM，DeepSeek Flash | 1/1/1，max_metric_calls=4，单次反思、skip_perfect_score=false，minibatch gate=improvement_or_equal；候选 minibatch 1.0→1.0，候选 dev [1.0]。变更候选实际评估，保留初始版本，最终 test EM 0.0；调用及落盘核对通过。 | [T20][T20] |

| 10-24 | SearchQA / MiniAgent / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 3/1/1，batch_size=3/max_steps=1；有效编译 0 次。本次覆盖不足：candidate_not_evaluated，最终 test EM 1.0；不计完整通过。技能生成与后续自主读取分开记录，单次评估不证明自主复用。 | [T20][T20] |

| 10-24 | SearchQA / Claude Code / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 3/1/1，batch_size=3/max_steps=1；train EM [1.0, 1.0, 1.0]，有效编译 0 次。本次覆盖不足：candidate_not_evaluated，最终 test EM 1.0；不计完整通过。技能生成与后续自主读取分开记录，单次评估不证明自主复用。 | [T20][T20] |

| 10-24 | NQ / MiniAgent / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 1/1/1，batch_size=1/max_steps=1；train EM [1.0]，有效编译 0 次。本次覆盖不足：candidate_not_evaluated，最终 test EM 0.0；不计完整通过。技能生成与后续自主读取分开记录，单次评估不证明自主复用。 | [T20][T20] |

| 10-24 | NQ / Claude Code / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 1/1/1，batch_size=1/max_steps=1；train EM [1.0]，有效编译 0 次。本次覆盖不足：candidate_not_evaluated，最终 test EM 0.0；不计完整通过。技能生成与后续自主读取分开记录，单次评估不证明自主复用。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / EvoHarness | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 4/1/1，batch_size=4/max_steps=1；train EM [0.0, 1.0, 0.0, 1.0]，有效编译 1 次。变更候选实际评估，选中变更版本，最终 test EM 1.0；调用及落盘核对通过。最终 test 已核实原生 Skill 自主调用；新技能保留训练案例和未经验证的评分假设，因此记 ✓*，不声称泛化。 | [T20][T20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoHarness（跨批次分支） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 4/1/1，batch_size=1/max_steps=4；train EM [0.0, 1.0, 0.0, 1.0]，有效编译 1 次。变更候选实际评估，选中变更版本，最终 test EM 1.0；调用及落盘核对通过。技能生成和自主读取分别记录；未发现实际读取时不声称自主复用。后续训练批次复用编译版本 3 次；不新增组合格子。 | [T20][T20] |

| 10-24 | SearchQA / MiniAgent / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / Claude Code / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | NQ / MiniAgent / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | NQ / Claude Code / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | HotpotQA / MiniAgent / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | HotpotQA / Claude Code / ACE（online） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，online、1 次更新、edit_budget=1；训练流记分及不调用 dev 验证的规则核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / MiniAgent / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / Claude Code / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | NQ / MiniAgent / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | NQ / Claude Code / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / EvoPrompt（DE random donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群 4、1 轮、donor_random=true；四槽 generation 和实际变更 trial 评估核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / MiniAgent / RRSI（两轮/退火） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生 1/1/1，T=2/k=2/m=1，编辑预算 3→2；第二轮历史和各轮重复候选测量核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / Claude Code / RRSI（两轮/退火） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生 1/1/1，T=2/k=2/m=1，编辑预算 3→2；第二轮历史和各轮重复候选测量核对。目标覆盖未完成：wall_clock_timeout，最终 test EM 未完成。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / RRSI（两轮/退火） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生 1/1/1，T=2/k=2/m=1，编辑预算 3→2；第二轮历史和各轮重复候选测量核对。首轮候选修复后仍被 critic 拒绝、未进入测量；第二轮候选测量与最终 test 正常完成，test EM 1.0。本次两轮重复测量覆盖不完整，保留已有通过记录。 | [M20][M20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / RRSI（两轮/退火） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 原生 1/1/1，T=2/k=2/m=1，编辑预算 3→2；第二轮历史和各轮重复候选测量核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / MiniAgent / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，3 epoch、max_steps=3；两次 slow/meta 调用及后续 fast 对 meta 记忆的复用均发生，但 slow 均 no_change，未覆盖变更 slow 候选评估；fast 候选和最终 test 正常完成，test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | SearchQA / Claude Code / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，3 epoch、max_steps=3，slow/meta 开启；两次 slow/meta 与后续 fast 提示复用 meta 记忆核对。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [M20][M20] |

| 10-24 | NQ / MiniAgent / EvoPrompt（GA 修复前） | 文本 LLM，DeepSeek Flash | 修复前 standard 整代替换后丢失此前同分版本，最终错误选新版本；原始结果保留，撤销本次通过判定，另建目录复测。 | [X10][X10] |

| 10-24 | NQ / Claude Code / EvoPrompt（GA 修复前） | 文本 LLM，DeepSeek Flash | 修复前 standard 整代替换后丢失此前同分版本，最终错误选新版本；原始结果保留，撤销本次通过判定，另建目录复测。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoPrompt（GA 修复前） | 文本 LLM，DeepSeek Flash | 修复前 standard 整代替换后丢失此前同分版本，最终错误选新版本；原始结果保留，撤销本次通过判定，另建目录复测。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / Claude Code / EvoPrompt（GA 修复前） | 文本 LLM，DeepSeek Flash | 修复前本次保留初始版本、流程正常完成；为验证统一选优修复，另建目录复测，原记录保留。 | [X10][X10] |

| 10-24 | NQ / MiniAgent / EvoPrompt（GA tournament/standard 选优修复复测） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，GA、种群 2、1 轮，tournament 选亲本、standard 用子代替换种群；核对实际 child 评估、survivor 等于 children，以及最终保留历代最早最高 dev 分版本。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | NQ / Claude Code / EvoPrompt（GA tournament/standard 选优修复复测） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，GA、种群 2、1 轮，tournament 选亲本、standard 用子代替换种群；核对实际 child 评估、survivor 等于 children，以及最终保留历代最早最高 dev 分版本。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoPrompt（GA tournament/standard 选优修复复测） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，GA、种群 2、1 轮，tournament 选亲本、standard 用子代替换种群；核对实际 child 评估、survivor 等于 children，以及最终保留历代最早最高 dev 分版本。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / Claude Code / EvoPrompt（GA tournament/standard 选优修复复测） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，GA、种群 2、1 轮，tournament 选亲本、standard 用子代替换种群；核对实际 child 评估、survivor 等于 children，以及最终保留历代最早最高 dev 分版本。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | SearchQA / MiniAgent / GEPA（current_best/strict） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，current_best、strict_improvement、skip_perfect=false，4 次 metric 预算；核对候选 minibatch 测量及严格筛选，未提高时正确拒绝也是目标分支完成。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | SearchQA / Claude Code / GEPA（current_best/strict） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，current_best、strict_improvement、skip_perfect=false，4 次 metric 预算；核对候选 minibatch 测量及严格筛选，未提高时正确拒绝也是目标分支完成。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / GEPA（current_best/strict） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，current_best、strict_improvement、skip_perfect=false，4 次 metric 预算；核对候选 minibatch 测量及严格筛选，未提高时正确拒绝也是目标分支完成。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / Claude Code / GEPA（current_best/strict） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，current_best、strict_improvement、skip_perfect=false，4 次 metric 预算；核对候选 minibatch 测量及严格筛选，未提高时正确拒绝也是目标分支完成。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / ACE（online 两批） | 文本 LLM，DeepSeek Flash | 固定原生 4/1/1，online、batch_size=2、每批一次 Curator 尝试；核对前一次 curate 的 Snapshot 被后续 train 使用，训练流按更新前记分，dev 不参与。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | 2WikiMultiHopQA / Claude Code / ACE（online 两批） | 文本 LLM，DeepSeek Flash | 固定原生 4/1/1，online、batch_size=2、每批一次 Curator 尝试；核对前一次 curate 的 Snapshot 被后续 train 使用，训练流按更新前记分，dev 不参与。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [X10][X10] |

| 10-24 | NQ / MiniAgent / EvoPrompt（DE 两轮/best donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群4、两轮，donor_random=false；核对8次 Worker 提示中的最佳 donor 和冻结父代、逐槽严格替换、两轮变更 trial 测量及历代最早最高 dev 分最终选择。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [DE2][DE2] |

| 10-24 | NQ / Claude Code / EvoPrompt（DE 两轮/best donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群4、两轮，donor_random=false；核对8次 Worker 提示中的最佳 donor 和冻结父代、逐槽严格替换、两轮变更 trial 测量及历代最早最高 dev 分最终选择。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [DE2][DE2] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / EvoPrompt（DE 两轮/best donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群4、两轮，donor_random=false；核对8次 Worker 提示中的最佳 donor 和冻结父代、逐槽严格替换、两轮变更 trial 测量及历代最早最高 dev 分最终选择。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [DE2][DE2] |

| 10-24 | 2WikiMultiHopQA / Claude Code / EvoPrompt（DE 两轮/best donor） | 文本 LLM，DeepSeek Flash | 原生 1/1/1，DE、种群4、两轮，donor_random=false；核对8次 Worker 提示中的最佳 donor 和冻结父代、逐槽严格替换、两轮变更 trial 测量及历代最早最高 dev 分最终选择。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [DE2][DE2] |

| 10-24 | SearchQA / MiniAgent / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | SearchQA / Claude Code / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / MiniAgent / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / Claude Code / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | HotpotQA / MiniAgent / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | HotpotQA / Claude Code / OPRO（两步/多候选历史） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两步、每步请求两个候选，history_size=2、score_threshold=0；核对历史分数排序、窗口与第二步候选复用，最终按 train 严格选优。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | SearchQA / MiniAgent / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | SearchQA / Claude Code / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / MiniAgent / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / Claude Code / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / GEPA（两轮 Pareto） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，两轮、Pareto、improvement_or_equal、skip_perfect=false，metric预算7；核对两轮父代/候选测量、筛选和最终 dev 同分保留。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / MiniAgent / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，3 epoch、max_steps=3，slow/meta开启；核对两次slow/meta、后续fast复用meta记忆和变更slow候选测量。目标分支完成，最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | NQ / Claude Code / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，3 epoch、max_steps=3，slow/meta开启；核对两次slow/meta、后续fast复用meta记忆和变更slow候选测量。目标分支完成，使用已有独立通用context-qa初始技能，部分slow候选显式请求原生Skill，非每次自主调用；最终 test EM 0.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / MiniAgent / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，3 epoch、max_steps=3，slow/meta开启；核对两次slow/meta、后续fast复用meta记忆和变更slow候选测量。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | 2WikiMultiHopQA / Claude Code / SkillOpt（slow/meta） | 文本 LLM，DeepSeek Flash | 固定原生1/1/1，3 epoch、max_steps=3，slow/meta开启；核对两次slow/meta、后续fast复用meta记忆和变更slow候选测量。目标分支完成，使用已有独立通用context-qa初始技能，部分slow候选显式请求原生Skill，非每次自主调用；最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |

| 10-24 | SearchQA / MiniAgent / AHE（debugger关闭） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原生1/1/1，一轮、target_score=1.01、debugger关闭，原生目录受限 Claude Code Worker30轮/8192输出上限；核对无 debugger 调用、变更候选测量及合法编辑保留。唯一训练题已通过，Worker 明确返回空 changes、未改文件，算法正确拒绝无变更并完成 test，EM 1.0；debugger 关闭及单次 Evolve 调用已验证，变更候选执行未覆盖，保留原有完成记录。 | [H20][H20] |

| 10-24 | SearchQA / Claude Code / AHE（debugger关闭） | Agent Worker：Claude Code，DeepSeek Flash，目录受限 profile | 固定原生1/1/1，一轮、target_score=1.01、debugger关闭，原生目录受限 Claude Code Worker30轮/8192输出上限；核对无 debugger 调用、变更候选测量及合法编辑保留。目标分支完成，最终 test EM 1.0。已有通过记录不重复计数；通过不代表效果提升。 | [H20][H20] |



## 证据范围与下一步



[H20][H20] 的8个OPRO共评估32个变更候选，实际Worker提示中的历史分数排序、两行窗口及第二步复用均逐条核对，最终按train保留历代最早最高分版本。GEPA共12轮筛选，11个候选入群、1个因minibatch退步被拒；5项在第二轮实际使用首轮入群候选作为父代。评分计数与7次预算、最终dev同分保留及选版后一次test均核对。单dev题尚不能覆盖多任务互补frontier。SkillOpt的两次slow/meta及后续fast记忆复用在4项中均触发，共7个变更slow候选被测量，slow均未获选，仍未覆盖选中slow后再接受fast的情况；Claude Code沿用独立通用context-qa初始技能。NQ/Claude Code的一个slow候选及最终test有显式Skill请求；2Wiki/Claude Code一个slow候选有请求，最终test没有，不把Snapshot传入等同于每次自主使用。



AHE的两个关闭debugger实验均只有一次原生Evolve Worker调用。MiniAgent明确认为已通过的训练轨迹不足以支撑修改，未改文件；Claude Code实际修改CLAUDE.md并完成候选及test。AHE按train保留合法编辑，train 1→1仍保留候选，不是dev选优规则的例外。生成指令中的重复片段偏好与短答策略不构成泛化证据。20个运行及所属进程组已结束，183个源码及Worker示例文件、10份数据哈希不变。87份保存的Snapshot和484份运行文件/日志未检出运行凭据、Snapshot缓存；两次原生Worker共16次显式文件工具调用均在目录规则内，无未核实或成功越目录调用，该策略不等于候选代码的OS隔离。本批未改源码，未重复全量离线测试，沿用此前511通过、1跳过及Ruff通过的基线。



[DE2][DE2] 的4个运行和所属进程组均已结束。183个源码及 Worker 示例文件、4份数据哈希未变；45份保存的 Snapshot 和174份运行文件/日志完成凭据与缓存扫描，未检出运行凭据或 Snapshot 缓存。本批 Worker 均为文本 LLM，不据此增加原生编辑工具隔离覆盖。只增加配置及证据，未重复全量离线测试；沿用最近修复后511通过、1跳过及 Ruff 检查通过的基线。



[X10][X10] 发现 EvoPrompt 的 GA standard 会把旧版本移出整代种群，最终只从末代选优，导致 dev 同分时错误选择新版本，也可能丢失历代更好的版本。修复保留原生整代种群替换，只让最终选择记住历代最早最高分版本，严格更高分才替换；不改公共接口、任务数据、模型、种群预算或 gate。新增回归覆盖两个 Target 的初始/初始化候选/中间代最佳保留、同分和后续退步，旧实现8例失败、2例通过，修复后10例均通过。全量测试511通过、1跳过，Ruff 检查与215个文件格式检查通过。4项真实复测的最终选版仅按 dev 记录核对，未使用 test 分数。



追加批14次尝试均已停止；183个最终源码及 Worker 示例文件哈希核对一致，仅修改上述算法实现并新增1个测试文件。10份数据哈希未变，44份保存的 Snapshot 和255份运行文件/日志未检出运行凭据，Snapshot 未混入缓存。本批 Worker 均为文本 LLM，不从本批推断原生编辑 Worker 的工具隔离覆盖。此前 [M20][M20] 的 RRSI 两轮测量缺口、600秒超时和 SkillOpt/MiniAgent slow no_change 的覆盖边界继续保留，不因追加批通过消除；两个批次的分支验证不要求演化提分。



[T20][T20] 发现 ACE 的 Curator 提示未告知已有 `edit_budget`，首个 1 条预算实验生成 3 条 ADD 后被正确拒绝。修复仅把原有条数上限写入 Curator 提示，继续严格拒绝超预算更新，不改变 ADD 协议或选优规则；新回归测试在旧代码上失败，修复后通过，同配置独立真实复测完成更新。7 个修复后 ACE 实验的实际 Curator 请求均含配置上限。ACE 回归 11 项通过，全量测试 501 项通过、3 项子测试通过、1 项跳过；本地 Ruff 检查和 214 个文件格式检查通过。



本批 21 次尝试均正常收尾，部分覆盖不等于运行错误。原生 1/1/1 用于 ACE/GEPA；EvoHarness 的 SearchQA 使用排序后的原生训练压缩包前 3 条，2Wiki 使用源顺序前 4 条并排除既定 dev/test，held-out 保持不变，NQ 仍为 1/1/1；没有按得分重选样本或强造失败。2Wiki/MiniAgent 跨批次项在第 1 批编译的 topic 版本实际用于后续 3 批训练；第 3 批的过长技能及跨 level 修改被拒，先前合法版本保留。该 Target 未显式读取技能正文，因此版本传递与自主读取分开记录。2Wiki/Claude Code 的最终 test 成功启动新 Skill，但正文保留训练案例和未验证的评分假设，仍标 ✓*；general 编译门槛与泛化效果不从此次推断。



最终核对 183 个源码及 Worker 示例文件只有上述 ACE 实现变更，另修改 1 个测试文件；14 个本批数据文件哈希稳定。46 个保存的 Snapshot 和 328 个运行文件及会话日志未检出运行凭据，Snapshot 未混入缓存，所有本批进程已结束。2 次实际执行原生编辑 Worker 的 EvoHarness 实验通过显式工具边界核对；4 次正常跳过编译的 EvoHarness 没有 Worker 调用，不据此声称编辑隔离覆盖。15 份 ACE/GEPA 选择记录按 dev 最大值及同分保留先选版本核对通过；此前的失败证据保留，原生工具策略不等于候选代码的操作系统隔离。



[PF1][PF1] 的 5 个复测均正常结束：3 个 RRSI 各完成两次候选测量，2 个 ADAS 完成实际变更候选的 dev 评估和 archive 登记，最终 test 均使用选中版本。仅调整实验配置并新增证据，未修改实现，因此未重复全量离线测试。183 个源码及 Worker 示例文件、7 个数据文件哈希不变；15 个保存的 Snapshot 和 116 个运行文件及会话日志未检出运行凭据，Snapshot 未混入缓存，所有本批进程已结束。5 个 Worker 的显式文件工具调用经过边界核对，2 次受限工具请求被阻止，无未核实或成功越界调用；该策略不等同于候选代码的操作系统隔离。ADAS 新增的每个工具、中间件及外部服务路径仍不能从本次候选执行推断为已自主调用。



[QB4][QB4] 发现 RRSI 的 digester 证据被序列化为单行 JSON：NQ 长轨迹触及原生 Read 限制，Grep 又省略长行，短小输出和指标也难以定位。修复仅给 trace.json 增加缩进分行，保留完整内容、只读校验和所有算法规则；新回归测试在旧代码上失败，修复后通过。NQ/Claude Code 在相同数据、模型和预算下独立复测，越过读取阻塞，完成候选测量与最终 test。RRSI 回归 221 项通过，全量测试 499 项通过、1 项跳过，Ruff 检查及 214 个文件格式检查通过；远程 Ruff 工具解析遇网络等待后已停止，实际代码与格式检查在本地对同步文件执行。



本批 11 个实验均已结束。183 个源码及 Worker 示例文件只有上述 RRSI 实现变更，另修改 1 个回归测试文件；7 个数据文件哈希保持一致。35 个保存的 Snapshot 和 252 个运行文件及会话日志未检出运行凭据，Snapshot 未混入缓存，8 次原生 Worker 运行的显式工具调用通过目录边界核对。SearchQA、NQ 的 MiniAgent/RRSI 输出上限错误属于本批 Worker 配置限制；2Wiki/MiniAgent/RRSI 候选被协议和 critic 拒绝，正常退出不等于候选测量通过。EvoHarness 的新技能从单题国籍反馈推广出国家名偏好，未验证其泛化，且 test 未自主读取该技能；这些限制保留在 ✓* 记录中。



[QB3][QB3] 的 10 个独立实验均正常结束，候选实际变化并完成评估、选择或拒绝和最终 test；本批没有修改实现。核对 183 个源码及 Worker 示例文件、7 个数据文件哈希不变，28 个保存的 Snapshot 和 158 个运行文件及会话日志未检出运行凭据，Snapshot 未混入缓存，全部本批进程已结束。8 个原生编辑 Worker 的显式工具调用均通过目录边界核对；此检查不等同于候选代码的操作系统隔离。仅新增运行证据和表格，未重复全量离线测试。



本批 NQ/DarwinX 的候选自主调用了新技能，2Wiki/ADAS 的候选自主调用了新增命令对应的 Skill；其他未发生的扩展调用不算覆盖。SearchQA/SkillOpt 的 train 与最终 test 调用了初始技能，但候选 dev 未调用修改后的技能。两次 DarwinX 均在 screen 被拒绝，未进入 confirmation；两次 SkillOpt 仅验证 fast 更新。NQ/AHE 的候选 train 由 1 降为 0，仍按 AHE 原有规则保留合法编辑并记录逐项反馈；这不是 dev 同分选优变更，也不代表效果改善。



验证顺序已调整为先补能力缺口，再扩展 Benchmark，最后补重复组合。当前能力清单如下；它与组合计数分开，补一个分支不会新增矩阵格子。



| 能力 | 当前证据 | 下一步或限制 |

| --- | --- | --- |

| SkillOpt fast / slow / meta 跨 epoch | 两个 Agent 均完成真实运行，见 [SF1][SF1]；受保护指导区和 meta 传入下一轮已核对 | 本轮最高分同分，未覆盖 slow 被选中后再接受 fast 编辑；Claude Code 使用独立通用初始技能，默认技能目录为空 |

| SkillOpt 多提案合并与排序 | [SM1][SM1] 中 MiniAgent、[CB2][CB2] 中 Claude Code 均完成组内及跨组合并和变更候选评估；Claude Code 还实际执行 rank 选取 1 项编辑 | MiniAgent 的合并结果符合预算，未触发 rank；Claude Code 使用独立通用初始技能，最终 test 未自主调用 Skill |

| OPRO 多步及多候选历史 | [H20][H20] 的8项完成两步、每步2个候选实际评估，以及历史排序、窗口和最终train最优选择 | 固定1题train，未覆盖多题few-shot采样差异 |

| GEPA 多轮种群/父代传递 | [H20][H20] 的6项完成两轮、12次候选筛选和最终dev选优，5项第二轮实际使用新入群父代 | 单dev题不覆盖多任务互补frontier；见[X10][X10]的严格筛选分支 |

| AHE 无debugger编辑 | [H20][H20] Claude Code完成无debugger的变更候选运行，MiniAgent完成正常无变更拒绝 | MiniAgent的该分支未覆盖变更候选执行；原有debugger开启记录保留 |

| EvoHarness 两级编译与原生读取 | 两个 Agent 有编译记录；[ES1][ES1] 补齐两个 Agent 的新技能 Snapshot 传到后续 train batch | 版本传递不等于模型自主读取正文；成功修订、合并与删除仍未覆盖 |

| EvoPrompt DE / GA 最优追踪 | [M20][M20] 补随机 donor；[DE2][DE2] 完成 NQ、2Wiki 两个 Target 的 best donor 两代验证及逐槽选择、最终历代最优追踪；[X10][X10] 修复并复测 GA standard 跨代最佳保留 | DE2 实际观察31次同分保留、1次退步保留，未触发严格提分采纳；不据此声称覆盖所有种群分支 |

| RRSI 候选测量 | [NW1][NW1] 中 Claude Code Target、[CB2][CB2] 中 MiniAgent Target 均用 Claude Code Worker 完成审查、smoke gate、候选测量、选择和 test | 多候选、探索和剪枝仍未测；历史未受限 Worker 记录不构成通用隔离保证 |

| ModularRSI 五模块演化与集成 | 仅离线验证与配置检查 | 当前现成接入需 TerminalBench 的独立 evolution_data_path、五模块文件映射与 Docker；QA 的普通 train 不能冒充独立演化集。Claude Code 也没有可编辑的闭源循环源码 |

| 新 Benchmark 的执行与评分 | QA context 已覆盖；Terminal 完成准备但无容器运行 | 非 QA 先用一个简单算法验证执行与评分；明确语料、搜索、judge 凭据或容器依赖后再扩展算法 |



[SF1][SF1] 是本轮分支验证：两个 Agent 各运行 3 个 epoch，共用各自固定的 1/1/1 数据。所有调用、选择、最终 test 与落盘完成。Claude Code 的通用初始技能仅位于独立 smoke 目录，报告保留全文和用途；未写入默认 harness。未修改项目实现，未重复全量离线测试。历史 [SC1][SC1] 的候选未自主读取限制保留，本轮已有部分候选自主调用 Skill，但最终 test 仍未调用。



10-23 的已完成实验使用 DeepSeek Flash。远程 QA smoke 使用固定来源的数据：SearchQA 保留原生分区；HotpotQA、NQ 从训练数据抽取不同原始记录作为实验 train/dev/test；2Wiki 使用固定验证集文件划分实验分区。远程 HF 网络受限，数据经本地准备后传入，不能据此认定远程自动下载已验证。多数实验每个分区各 1 题；本轮部分能力验证用 3/1/1，EvoHarness/Claude Code 后续批次复测用 4/1/1。新增训练样本按固定来源顺序选取，没有移动 dev/test 样本、按答案筛题或调高失败阈值。OPRO 按 train 选优，dev 只加载、不参与其选择。



[A1][A1] 中的 ACE 同分选新版说明及“ADAS、AHE、EvoHarness 尚未真实测试”属于当时状态，已由 [D1][D1]、[H1][H1]、[E1][E1] 及本表覆盖；历史报告保留。此前新增可选编辑 Worker 原生 hook 示例后的全量离线检查为 498 项通过、3 项子测试通过、1 项可选安装入口检查跳过；该入口检查在更早一轮单独通过。此前 RRSI 分行证据修复后全量检查为 499 项通过、1 项跳过，见 [QB4][QB4]；ACE 预算提示修复后的历史全量结果为 501 项通过、3 项子测试通过、1 项跳过，见 [T20][T20]。最新 EvoPrompt standard 最终选优修复后，全量测试为 511 项通过、1 项跳过，Ruff 检查及215个文件的格式检查通过，见 [X10][X10]。真实复测使用新构建的 wheel。离线检查、原生 hook 探针和两个 Agent 的独立文件编辑探针不增加矩阵中的真实通过格子。



AHE 按 train 验证并保留协议合法的编辑，不执行 dev 最优版本选择；因此本轮 train 同分仍保留候选，不与 dev 同分保留旧版的约定冲突。为确保只用 1 题也执行编辑，smoke 将 `target_score` 设为 1.01，仍限定 `max_steps: 1`。复测未触发收尾补救调用，修复分支由 16 项确定性原生循环测试覆盖。候选代码注释含训练题示例，执行逻辑为通用格式整理；不据此声称泛化提升。



EvoHarness 的 ✓* 表示流式执行、反思、两级技能提交、最终评估和独立原生读取链路通过，新增 [ES1][ES1] 还覆盖新技能 Snapshot 传入后续训练批次。历史生成的 topic skill 保留了具体训练答案示例，多个技能正文还包含训练任务 ID；这与编译提示中不保留个案答案的意图不符，结构与来源校验不能保证语义泛化。原始产物保留，未人工清洗后冒充算法生成结果。Claude Code 正式 test 和本轮后续 train 未自主调用 Skill；独立探针使用显式读技能请求，不能代替自主选择能力验证，也不计为 benchmark 分数。成功合并、修订或删除仍未覆盖。



已完成不依赖 Docker 的算法与 harness 检查，以及 SearchQA、NQ、2Wiki 的 Claude Code 最小 OPRO smoke。RRSI 两个 Target 均通过原生 Claude Worker 完成了候选测量，历史记录见 [NW1][NW1]、[CB2][CB2]，最近三个 MiniAgent Target 的复测见 [PF1][PF1]。DarwinX/Claude Code 也完成候选筛选链路，历史外部训练数据访问与新受限 Worker 的证据边界分开记录。NQ、2Wiki 的 ADAS/MiniAgent 已在 [PF1][PF1] 补齐候选执行与最终 test；不从进程退出码推断完整通过。根据用户要求，HotpotQA/MiniAgent 的 GEPA、ACE 旧格子暂不重复真实 smoke，保留 ✓† 的证据边界。ModularRSI 需要独立演化任务和模块映射，现有 QA 初始化检查未满足其条件；仍记为待验证。Terminal-Bench 环境受阻暂缓，其他未填写的组合不从相邻格子推断结果。



随后补充的 [SQ2][SQ2] 包含 6 个 SearchQA 组合：EvoPrompt 两个 Target，以及 MiniAgent 的 ADAS、AHE、MetaHarness、DarwinX，均为固定原生分区 1/1/1。所有 Target/Worker 调用完成、变更候选实际评估、最终 test 使用选中版本，记录和 Snapshot 未检出运行凭据。EvoPrompt/MiniAgent 与 MetaHarness/MiniAgent 的 dev 由 0 提到 1；其余没有观察到收益。DarwinX 在 screen 同分拒绝候选，未进入 confirmation；其生成的清理函数会破坏 JSON 字符串引号，离线重放已记录，未把被拒绝候选合入源码。ADAS 的笔记工具和 MetaHarness 的上下文工具在本轮未被 Target 调用。此次没有修改项目实现，仅新增真实运行证据和表格记录，因此未重复全量离线测试。



新增 [NQ3][NQ3] 按“能否跑通”验收 6 个 NQ 组合，均为固定页面 context、1/1/1 和单轮预算：EvoPrompt 两个 Target，以及 MiniAgent 的 AHE、MetaHarness、DarwinX 共 5 个组合完成实际变更候选评估、合法选择和最终 test；分数不提高也通过。DarwinX 此次覆盖 screen 和配对 confirmation，未测重组。ADAS/MiniAgent 正常退出，但 30 轮 Worker 未修改文件，正确拒绝空候选，候选加载与评估仍未覆盖，记 △；未增加预算重试。本批全部模型调用正常完成，最终 test 与选中版本一致，记录和 Snapshot 未检出运行凭据。仅更新证据与表格，未修改实现、未重复全量离线测试。



新增 [W4][W4] 验证 6 个 2WikiMultiHopQA 组合：EvoPrompt 两个 Target，以及 MiniAgent 的 MetaHarness、DarwinX 共 4 个组合完成真实变更候选评估、选择和最终 test；DarwinX 覆盖配对 confirmation。ADAS/MiniAgent 未修改文件，AHE/MiniAgent 的清单声明与实际差异不符，均被正确拒绝，候选执行未覆盖，记 △；未加预算或放宽协议重试。全部调用正常完成、最终 test 与选中版本一致，记录和 Snapshot 未检出运行凭据。使用已有固定 validation.parquet、context/answer_text、seed=42、1/1/1；上下文由数据集提供，不需要 Serper，不能据此声称联网搜索已验证。仅更新证据与表格，未修改实现、未重复全量离线测试。



当前观察到的运行预算边界：Claude Code 目录编辑使用 20 轮 MiniAgent Worker 时，MetaHarness、DarwinX 都出现只查阅未修改；30 轮使 MetaHarness 完成，但 DarwinX 仍未产出修改。增加预算不能保证候选有效。SkillOpt 的文本 Worker 出现过一次无效 JSON，严格解析使运行明确失败，同配置独立重试成功；未自动修补模型输出后冒充原始结果。



其他前置条件：BFCL Multi-Turn 当前集成需要 Docker；DeepSearchQA 使用原生 Gemini 评分器，需要独立的 `benchmark.judge.llm`（`gemini-2.5-flash`）凭据，不能用现有 DeepSeek Worker 配置替代；OfficeQA-Pro 需要 `benchmark.corpus_path` 指向公开文档语料目录。这些是源码检查结果，尚未计为真实运行或环境受阻格子。



[PRE1][PRE1] 补充实际统一入口 `--plan` 检查：Terminal-Bench、AppWorld、SWE-bench、BFCL、OfficeQA-Pro、DeepSearchQA 六项均能生成依赖与前置条件计划，未下载数据、创建容器任务或调用模型，不增加通过格子。前四项需 Docker，沿用已有 daemon 不可用记录，未反复重试。远程未配置 HF、Gemini/Google 或 Serper 凭据，也没有 OfficeQA 语料；[OfficeQA 官方数据页](https://huggingface.co/datasets/databricks/officeqa)要求授权访问。真实执行前仍需相应外部条件。



[CB1][CB1] 汇总本次两小时预算内的自主验证：10 次真实尝试，7 次完成所针对的能力链路，2 次正常收尾但未触发目标分支，1 次达到外部 600 秒上限中止。后续 EvoHarness/Claude Code 已补齐跨训练批次传递；RRSI/Claude Code 更换原生 Worker 并澄清审查提示后完成候选测量，历史部分完成记录保留。新增 2 个完成格子，其余是已有组合的分支覆盖。RRSI 修复为 Worker 提供累计差异，critic 澄清归因信息与版本文件内容的区别；未修改公共接口、gate 或同分选优规则。全部新实验均已结束，已核对所有保存的 Snapshot 和运行记录未包含运行凭据。RRSI/MiniAgent 的未落盘调用用量不可追溯，超时不记作通过。



后续每轮 smoke 更新本表对应格子和记录行，附运行目录或脱敏报告，说明 Target、Worker、模型、数据来源、预算、候选是否实际变化、最终选择和失败原因。修复后新建实验复测，保留旧证据；配置、离线测试、真实运行和效果提升分别记录。



[CB2][CB2] 发现未受限 NQ/ADAS Worker 读取了 test 文件，该次记录明确标为无效。随后新增[可选编辑 Worker 示例](../examples/claude_edit_worker/README.md)，通过原生 hook 限制文件工具访问当前工作目录，真实越界探针已通过；它不提供候选代码的操作系统隔离，也不改变默认 Agent。回看三次成功的原生 Worker 实验，两个 RRSI 未发现显式读取数据缓存的调用；历史 DarwinX/Claude Code 则读取了 checkout 外的训练缓存和额外训练行，未发现显式 test 文件读取，但因此标为 ✓* 并保留范围限制。此回看是工具参数筛查，不是完整隔离证明。SearchQA/Claude Code 的 ADAS、MetaHarness 和 DarwinX 生成了技能或子 Agent 文件，本轮未自主调用这些扩展；其版本指令、候选加载与评估路径已验证。



[S1]: smoke-searchqa-skillopt-20261019.json

[Q1]: smoke-qa-20261023.json

[W1]: smoke-twowiki-20261023.json

[A1]: smoke-algorithms-harnesses-20261023.json

[D1]: smoke-adas-20261023.json

[T1]: smoke-terminal-20261023.json

[H1]: smoke-ahe-20261023.json

[E1]: smoke-evoharness-20261023.json



[M1]: smoke-metaharness-20261023.json



[DX1]: smoke-darwinx-20261023.json



[R1]: smoke-rrsi-20261023.json



[EC1]: smoke-evoprompt-claude-20261023.json



[SC1]: smoke-skillopt-claude-20261023.json



[AC1]: smoke-adas-claude-20261023.json



[HC1]: smoke-ahe-claude-20261023.json



[MC1]: smoke-metaharness-claude-20261023.json



[DC1]: smoke-darwinx-claude-20261023.json



[EHC1]: smoke-evoharness-claude-20261023.json



[RC1]: smoke-rrsi-claude-20261023.json



[QC1]: smoke-qa-claude-20261023.json



[SQ2]: smoke-searchqa-batch2-20261023.json


[S3][S3] smoke3收尾SearchQA的4个缺口：{"unsupported": 2, "partial": 2}。其余20格原流程通过记录与覆盖限制保留；公开check-only不计真实smoke通过。
[TN3]: smoke-terminal-network-retry-20261025-03.json
[TE25]: smoke-terminal-evo-mini-retry-20261025.json
[TW25]: smoke-twowiki-closure-smoke2-20261025.json
[NQ25]: smoke-nq-smoke3-20261025.json
[HP25]: smoke-hotpot-closure-smoke3-20261025.json

[TN3][TN3] / [TE25][TE25] Terminal 新增复测原生执行与评分正常，保留原严格 partial 分支覆盖记录；✓*表示流程完成但未执行变化后的版本。
[TW25][TW25] / [NQ25][NQ25] / [HP25][HP25] 各自剩余2格均已由公开启动检查确认缺独立演化数据，记⊘，零模型调用。整批已核验不等于所有组合都支持。

AppWorld 自动准备的下载目录不匹配已单独记录为[公开路径缺口](smoke-appworld-preparation-gap-20261025.json)。当前 AppWorld 真实组合使用公开 benchmark.data_path 的完整原生缓存模式，不冒称默认自动下载路径已修复。

2026-10-25 18:29 CST 核验：[TA25][TA25] 的 AppWorld 已13格通过，ADAS × Claude Code 运行中，另10格待运行。smoke2 正在验证 Terminal EvoHarness × Claude Code；smoke3 的 Terminal MetaHarness × Claude Code 在官方镜像下载断连后有界恢复，保留2个已校验镜像，尚未调用模型。既有失败和重试历史保留。

18:35 CST 补充：smoke2 Terminal EvoHarness × Claude Code 最终 result 已完成、test 原生6/6通过，但 train 缺少 FlashRSI trajectory 和官方评分，整格仍记失败，不能用 test 分数替代完整链路。见[本次原始审计](smoke-terminal-evo-smoke2-20261025.json)。smoke3 的3个官方镜像已校验齐全，正由公开 check-only 自动准备依赖。

SWE 运行性复核（2026-10-25）：ADAS / DarwinX × MiniAgent 的无效候选均未被选中，保留原版本后完成官方最终评分，按用户确认的验收标准计 ✓*；原 strict flow_failed 和候选错误保留。当前 SWE 为21格流程完成、1格 Worker 预算中断、2格原配置缺独立演化数据，详见[复核报告](smoke-swe-runnability-review-20261025.json)。SWE 新增 evolution_data_path 加载入口的离线验证不算真实 ModularRSI smoke，也不改写旧启动拒绝记录。

[TM3]: smoke-terminal-meta-smoke3-20261025.json

19:04 CST 核验：AppWorld19格严格通过，EvoHarness × Claude Code 原生执行/评分完成且无更新，计✓*；RRSI × MiniAgent 在途，3格待运行。smoke3 Terminal MetaHarness × Claude Code 已完成完整候选评估及原生评分，同分保留初始版本，计✓。两台空闲机已分别接 Terminal SkillOpt × Claude Code（smoke2）和 AHE × Claude Code（smoke3），均由原样公开入口执行，未部署本轮本地 SWE 新代码。

[TS2]: smoke-terminal-skillopt-smoke2-20261025.json

[TA3]: smoke-terminal-ahe-smoke3-20261025.json

[TO25]: smoke-terminal-opro-retry-20261025.json

[TD2]: smoke-terminal-darwinx-smoke2-20261025.json

[NU25]: smoke-native-no-update-review-20261025.json

2026-10-25 19:57 CST 本轮核验：AppWorld24格结束，21格严格通过、EvoHarness/Claude无更新但执行与评分完成、2格ModularRSI缺独立演化数据，按运行性计22格通过。默认自动准备目录缺口仍单独保留，当前仅证明公开本地完整原生缓存模式。Terminal SkillOpt/Claude已完成完整候选评估及官方评分；AHE/Claude虽基线原生40轮终止仍有评分，但候选和最终test缺轨迹与评分，记失败，不能套用ADAS/DarwinX的正常回退分类。OPRO/Claude与DarwinX/Claude分别在原机和smoke2运行。NQ和BFCL的4个EvoHarness格子只是按现有原生记录复核为正常无更新，保留旧分支覆盖限制，不算新增4次实验。

smoke3 已用统一公开入口依次检查 OfficeQAPro 和 DeepSearchQA 的共享前置条件，均零模型调用：OfficeQAPro 缺 benchmark.corpus_path，题目授权检查尚未进行；DeepSearchQA 缺默认 Tavily 搜索密钥，独立官方 Gemini Judge 也未配置但校验尚未到该阶段。两项都仍无真实组合通过，48个格子继续待验证。见[OfficeQAPro准备记录](smoke-officeqa-preflight-smoke3-20261025.json)、[DeepSearchQA准备记录](smoke-deepsearchqa-preflight-smoke3-20261025.json)。当前该机等待外部条件，不虚构语料/凭据、不重复派发已通过组合。

2026-10-25 20:20 CST 实查：原机 Terminal OPRO/Claude 已结束且源码不变，候选评估正常完成，但最终 test 缺 FlashRSI trajectory / 官方评分，整格仍记失败，不把 result.finished 或0分当作合法模型答错。smoke2 DarwinX/Claude仍运行，已完成 Worker 与选择记录、正在最后评估；smoke3无活跃实验，仍缺Office语料、DeepSearch搜索/独立Judge配置。下一步优先查反复出现的原生轨迹保存缺口，避免盲目重付费。

[TOP3]: smoke-terminal-opro-transport-retry-20261025.json

[TEH3]: smoke-terminal-evo-transport-smoke2-20261025.json

[TAH3]: smoke-terminal-ahe-transport-smoke3-20261025.json

2026-10-25 20:53 CST 基础设施诊断：DarwinX/Claude已完成原生候选和最终test评分；基线及screen_parent各有一次原生40轮终止，保留✓*预算说明。零模型Docker对照复现连接桥空闲截断：将旧720秒策略缩短为1秒后，sleep3的exec在1.061秒返回0，但标记文件尚未产生，稍后才出现；原生socket及关闭空闲截断的桥均等待3秒并读到文件，见[诊断证据](smoke-docker-transport-diagnosis-20261025.json)。此机制与历史缺轨迹相符，但不伪造已丢失的逐次原始网络事件。

三台机均只修复.cache内私有Docker桥720秒空闲限制，镜像/评分/算法及212、231、253文件源码基线未变。正在各做730秒零模型长连接确认，验证本身不算smoke通过；通过后原机OPRO/Claude、smoke2 EvoHarness/Claude、smoke3 AHE/Claude各自动执行一次有界复测，保持原题目、配置和预算。任一长连接失败或超时则不启动该机付费实验；旧失败和原生轮数终止全部保留。OfficeQAPro/DeepSearchQA仍缺外部条件。

21:01 CST 长连接确认：三台均在私有Docker桥下实际执行730秒，客户端等到命令结束且返回时文件已存在；scratch容器清理成功，零模型调用。见[三机连接修复汇总](smoke-docker-transport-repair-20261025.json)。三台等待器已各自确认后启动公开入口的OPRO/Claude、EvoHarness/Claude、AHE/Claude真实复测；每台当前1运行、0待派发，复测尚未计通过，历史失败保留。

[TRR2]: smoke-terminal-rrsi-retry-20261025.json

2026-10-25 22:12 CST 核验：OPRO/Claude与EvoHarness/Claude复测均已结束且原生轨迹/官方评分完整，保留各一次原生40轮预算终止，计✓*。Evo编译出的新版已在最终test执行，不能沿用旧无更新记录。AHE/Claude最终新版test正常，但候选训练评估在依赖下载阶段遇GitHub SSL_ERROR_SYSCALL、尚未调用候选模型，因此△环境部分覆盖；原strict失败保留，不当成完整通过。原机已据旧RRSI第二次基线缺轨迹/用量的具体证据，在修复连接后接一次原预算RRSI/Claude复测。

AppWorld默认下载工作目录缺口现已在本地独立修复：Docker显式--workdir /world。原生0.1.3.post1路径探针、先失败后通过的缓存回归、25通过/1跳过及本次wheel独立安装后的CLI与资源回归均完成；见[修复验证](validation-appworld-workingdir-20261025.json)。完整默认数据下载尚未在标准共享文件系统Docker主机重跑，不增加真实组合通过数，既有固定源码队列未热替换。smoke3原生镜像内4次安装脚本请求均成功且hash一致，但随后Astral请求仍有HTTP错误，视为网络波动，不据此宣布网络已稳定或无限重试付费AHE。


2026-10-25 22:35 CST 收尾实查：三机均无活跃公开实验。原机 RRSI/Claude 有界复测已结束，两次 baseline 均有原生轨迹、真实 usage 和 reward 记录，但都达到40轮上限，算法报 too many failed trials，最终 test 未执行，仍记×，不加预算重试。smoke2 EvoHarness/Claude 与原机 OPRO/Claude本轮新增✓*；smoke3 AHE/Claude保留候选依赖下载 SSL 受阻的△。本轮小批合计4项结束、0运行、0待派发；OfficeQAPro/DeepSearchQA共48格仍待外部条件。详见[本轮三机状态](smoke-heartbeat-20261025-1342.json)。


2026-10-25 22:46 CST 定时实查：三机均无活跃模型实验，本次新增0通过、0付费运行。最近小批原机2结束/0运行/0排队（OPRO、RRSI），smoke2为1/0/0（EvoHarness），smoke3为1/0/0（AHE）；这些是既有终结记录的再次核实，不重复累计。轨迹/result/error/usage重新读取，冻结源码212/231/253个文件逐哈希未变。OfficeQA语料路径及DeepSearch搜索/Judge凭据仍未配置，AHE网络未有稳定修复证据，三项预算失败不扩大预算重跑。总数保持174通过含限制、1部分、3失败、14配置不支持、48待验证。详见[本次检查证据](smoke-heartbeat-20261025-1442.json)。


[OQP1]: smoke-officeqa-public-smoke2-20261025.json
[OQ24]: smoke-officeqa24-public-smoke2-20261025.json
[DSQP1]: smoke-deepsearchqa-public-smoke3-20261025.json
[DSQ24]: smoke-deepsearchqa24-public-smoke3-20261025.json

2026-10-25 23:49 CST 用户补充服务与数据后：OfficeQA-Pro/MiniAgent/OPRO已完成原生baseline、候选、Worker与test（test accuracy0，流程通过）；DeepSearchQA/MiniAgent/OPRO亦完成搜索/阅读、候选、Worker和test，使用用户明确指定的DeepSeek自定义Judge，保留网页工具失败及custom评分范围，计✓*，不称官方Gemini分数。Office原生缓存133题、697文档、698个数据文件按原清单逐hash核验，来源原目录只读，见[缓存核验](smoke-officeqa-cache-verification-20261025.json)。两台各1完成、1运行（OPRO/Claude）、22待运行，已通过Mini组合不重跑；其余按24格唯一顺序队列推进。新源码229文件独立部署，旧Terminal/SWE固定源码未热替换，原有预算不变；新Agent Worker用公开原生内置资源。Serper/Jina配置与显式自定义Judge是公开能力，见[配置说明](web-research-services.md)及[本轮验证](validation-web-research-services-20261025.json)。


2026-10-25 23:55 CST 新队列进展：OfficeQA-Pro新增SkillOpt/MiniAgent完整通过（baseline/train/candidate_dev/Worker/test及原生评分全部完成、同分保留原版）。OPRO/Claude在最终test达到原生40轮上限，usage完整，但error轨迹仅按规则记0、未执行正常成功评分，保留△预算部分覆盖，见[单独核验](smoke-officeqa-opro-claude-budget-20261025.json)，不冒充完整通过也不加预算重跑。Office当前3项结束（2通过、1预算部分）/SkillOpt-Claude1运行/20待；DeepSearch当前1带限制通过/OPRO-Claude1运行/22待。与23:49快照是同一队列自然推进，不是重跑首项。


2026-10-26 00:04 CST 定时核验：本次新增OfficeQA-Pro/AHE/MiniAgent完整通过与DeepSearchQA/OPRO/Claude Code自定义Judge通过（✓*）。两者原生baseline/candidate/Worker/test状态、usage、指标与终结记录已实查，首个自定义Judge身份保留。OfficeQA SkillOpt/Claude新结束但baseline/candidate_dev/test均达到40轮，train和Worker完成，仍记△预算部分，见[预算复核](smoke-officeqa-skillopt-claude-budget-20261026.json)，不误计正常成功评分或扩大预算重跑。当前Office5结束（3通过、2预算部分）/AHE-Claude1运行/18待；DeepSearch2结束（均custom带限制通过）/SkillOpt-Mini1运行/21待；原机无新队列。两新根源码各229文件逐hash未变、真实公开子进程在位、smoke3转发TCP可达，未改主体代码或再开重复调度器。详见[本次三机检查](smoke-heartbeat-20261026-0000.json)。


[AI26]: smoke-aime2026-24-original-20261026.json

2026-10-26 用户选择扩展AIME2026（1/1/1）：原机已新建独立256文件源码基线和24格唯一公开入口队列，先OPRO/MiniAgent，模型阶段在途，尚不计通过；不需Docker/搜索/Judge。原生公开test题池固定revision、自定义互斥1/1/1，不能当官方未见榜单评估。两旧队列继续，不重复其组合。SWE独立train准备另存[受阻记录](smoke-swe-modular-independent-original-20261026.json)：固定官方版本19008行的image/eval_script/log_parser全部为空，与现成SWE执行契约不符，零模型调用；没有用私有镜像/改题/借heldout绕过。不影响旧SWE有效结果。上文AIME未有真实smoke的文字属于之前离线接入历史，AIME2025、CRUXEval等仍未获本轮扩展授权。

[WB26]: smoke-workbench24-public-original-20261026.json

2026-10-26 01:26 CST 实查：AIME2026 的24格全部结束，22流程通过、2Modular因缺独立演化数据公开校验拒绝。RRSI/Claude的6个Target和8个Worker均finished、原生整数评分/usage完整；原收集器错选同级不完整目录，已只修外部离线审计路径选择，保存旧audit.log和审计历史，零新增模型调用。原机空闲后登记WorkBench24格唯一新队列（原题/原工具/原生状态评分，固定commit及自定义1/1/1、原预算），鉴权预检200后由公开入口自动准备依赖/数据，未替换任何在途源码。Office已8通过/8预算部分/1Worker60轮失败，MetaHarness-Claude运行、6待；DeepSearch已7custom限定通过/1SkillOpt-Claude非法空内容编辑失败/1ACE-Claude40轮部分，EvoPrompt-Claude运行、14待。预算部分没有正常最终评分，不升格通过、不加预算。两份[Office细审](smoke-officeqa-budget-error-review-20261026.json)与[DeepSearch细审](smoke-deepsearchqa-budget-error-review-20261026.json)保留原始状态和错误。

[BB26]: smoke-bbeh24-public-smoke2-20261026.json

[SG26]: smoke-supergpqa24-public-smoke3-20261026.json

[AI26E]: smoke-aime2026-modular-independent-original-20261026.json

2026-10-26 02:00 CST 用户扩大自主检验授权后，已给三机登记顺序衔接：WorkBench24结束后原机自动接AIME2026 ModularRSI两Target独立来源复测；Office24结束后smoke2接BBEH24；DeepSearch24结束后smoke3接SuperGPQA24。外部followup只执行公开预检、等待上一批终结/锁释放/真实进程退出、免费鉴权，然后启动唯一公共队列，不与前批并行付费。新增BBEH/SuperGPQA都已通过首项公开--plan和--check-only，零模型预检不算组合通过。BBEH旧代理HF重定向403只在新批私有配置换loopback33618 VPN后解决，旧日志和零模型准备史保留，主体代码未改。

AIME数据缺口已新增公开evolution_year能力：2026 dev/test仍为原aime2026:22/6，外部train来自固定AIME2025公开题池aime2025:10；完整两池先防重合再选题，真实metadata来源/revision/校验和非伪造。两个Target公开--check-only均通过，Claude显式采用公开三扩展示例的source_dir，Mini保持五模块；新265文件源码独立部署，未热替换在途263/229文件源码。参见[真实数据核验](validation-aime-independent-native-20261026.json)、[最新wheel核验](validation-aime-independent-wheel-20261026.json)。原2格配置拒绝保留在AI26历史；新2格尚未模型执行，表中[—][AI26E]表示排队待复测，绝不提前算通过。

BBEH原生模型执行完成后，首4格的外部收集器曾错误要求OfficeQA专有task_checksum；仅修正QA原生id/问题/参考核对后，零模型重审OPRO两Target与SkillOpt两Target通过，见[收集器复核](smoke-bbeh-collector-review-20261026.json)。原completed_pending_audit与audit.log保留，队列活跃时不覆盖其内存中的plan、不重跑已完成模型；表按独立审计补充显示。

[CX26]: smoke-cruxeval24-public-smoke2-20261026.json

2026-10-26 02:30 CST 定时实查：WorkBench24已结束22流程通过、2Modular缺独立来源；原机已自动接AIME2026独立2025来源的Modular两Target复测，Mini在途、Claude待。BBEH按原生证据及零模型collector-review合并显示15通过、DarwinX/Claude在途、8待，raw首4格completed_pending_audit不重复收费；DeepSearch9custom通过、3Claude预算部分、1SkillOpt空编辑失败，ADAS/Claude在途、10待。Office原24结束状态不变。新登记CRUXEval-O24作为smoke2在BBEH之后的唯一后续，默认原生固定HF数据、literal_output协议、自定义1/1/1，未开始模型；SuperGPQA24仍排在DeepSearch之后。新数据准备或check-only不算真实通过。当前真实运行统计以各JSON更新时间为准；保留原拒绝、失败和预算史。

[M526]: smoke-math50024-public-original-20261026.json

2026-10-26 02:38 CST 续：新增MATH-500作为原机AIME独立2格之后的24格唯一后续，公开--plan/--check-only已通过并自动获取固定原生数据；原生Math-Verify0.9.0已在公开依赖环境就绪，离线收集器绑定该原生环境，不另写评分逻辑。CRUXEval-O同样公开预检通过，等BBEH；均未模型执行，计入16项384格待验证范围。SkillOpt仅针对fast-update的_PatchError做拒绝提案保留当前版本的小修复，5专项测试、38相关回归通过/1跳过，最新wheel独立安装与离线最终评分验证通过，0模型；独立229文件修复根排在smoke3的SuperGPQA后复测一次，不热改原229/265队列。原SkillOpt/Claude/DeepSearch空编辑失败保留，尚未升级通过，见[修复验证](validation-skillopt-invalid-patch-20261026.json)。

[MU26]: smoke-musique24-cachefix-public-original-20261026.json

[HP26E]: smoke-hotpot-modular-independent-smoke2-20261026.json

2026-10-26 03:55 CST 定时核验：AIME独立来源两格已结束，Claude真实通过，Mini在第17次Worker达到60轮上限中断（17Target/16Worker完成，1Worker失败，无final）；数据门槛已解决，保留原两格拒绝及新预算失败。BBEH24收尾21通过/1预算部分/2缺独立数据，前4收集器误判已在无活跃控制器后带原counts和备份合并，零模型重审不重复收费。CRUXEval-O24收尾21通过/1RRSI-Claude原生8192输出token上限失败/2缺数据，保留原错误与usage，不增预算。HotpotQA新增evolution_split，以固定官方train演化、官方validation作下游划分，两完整源池先防ID/规范化问题重复；68相关测试、fresh wheel和两Target真实数据公开check-only通过，Mini真实contrast及Worker已在运行，Claude待，本表HP26E替换原两格最新证据，旧拒绝保留。 本次新增MuSiQue-Ans v1.0，原机MATH-500后自动24格；公开预检发现HF缓存blob无后缀导致JSONL误判JSON的真实产品缺口，先复现2失败再独立修复原生读取，20相关测试和新wheel验证通过。新独立cachefix根已通过同一公开入口真实数据预检，完整19938 train/2417 dev原文件逐SHA核验；原零模型失败根保留，评分/数据未改，尚未模型执行不计通过。见[MuSiQue修复](validation-musique-native-cache-20261026.json)、[真实缓存校验](validation-musique-native-cache-public-20261026.json)及[Hotpot真实数据](validation-hotpot-independent-native-20261026.json)。

2026-10-26 03:50 CST 用户确认smokedoc为31447：磁盘98%（约755MB可用）。核对活跃进程、maps和未来队列项目ID后，保存依赖清单并只删除22个已结束/替代批次的可重建venv缓存，释放18,378,317,824字节，磁盘降至36%且可用约18GiB。当前/排队/控制器/bootstrap/原生审计环境、全部源码/实验/usage/数据/HF与pip缓存/Docker镜像保留，MATH在途继续、当前及后续源码哈希未改。见[清理记录](smoke-smokedoc-disk-cleanup-20261026.json)。未按此前误解清理或归档Smoke文档。

[AI25]: smoke-aime2025-24-public-smoke2-20261026.json

[M526E]: smoke-math500-modular-independent-original-20261026.json

2026-10-26 04:43 CST 本轮实查：MATH-500与MuSiQue首批各22真实流程通过、2独立演化缺口。HotpotQA独立官方train两Target均已完成原生评分、usage和源码审计，原两格拒绝保留历史，最新HP26E均为通过。DeepSearchQA首批结束13custom通过、8Claude40轮预算部分、1空编辑失败、2独立数据缺口；不将无Judge的规则0分算完整通过。原机现验证MATH-500独立geometry/train两格，完整870题与MATH-500完整500题先防重合，70相关测试、新wheel和真实来源/参考评分已验证，不修写原始空答案或降低gate；见[新公开接口](math-independent-evolution.md)和[原生数据核验](validation-math-independent-native-20261026.json)。新增AIME2025的24格由smoke2唯一队列执行，Modular显式使用独立AIME2026来源，属于同一注册benchmark的另一年份范围，模型结果不与AIME2026混算。smoke3继续SuperGPQA；其SkillOpt/Mini又出现原生空append提案，保留失败，在SuperGPQA24和DeepSearch修复复测之后排一次已测试SkillOpt补丁的独立复测，未热替换在途源码。smokedoc清理后本轮仍有约14.6GiB空闲，未清理Smoke文档或实验记录。

[TQ26]: smoke-triviaqa24-public-original-20261026.json

[TA26]: smoke-tau2-airline24-public-smoke3-20261026.json

[MU26E]: smoke-musique-modular-independent-smoke2-20261026.json

[DS26F]: smoke-deepsearchqa-skillopt-invalid-patch-retry-20261026.json

[SG26F]: smoke-supergpqa-skillopt-invalid-patch-retry-20261026.json

[AI25F]: smoke-aime2025-skillopt-invalid-patch-retry-20261026.json

2026-10-26 05:48 CST 实查（本段覆盖此前状态，旧记录保留）：MATH-500独立两格结束，Claude11Target/5Worker全部finished并完成原生评分和usage；Mini第00020-Worker达到8192输出token上限，之前8Target/6Worker完成且失败Worker有usage，无final，不再归因缺独立数据，不增预算。SuperGPQA首批21流程通过/1SkillOpt-Mini空append失败/2独立来源缺口；新修复单格已真实完整通过，但本次Worker返回有效提案，invalid_patch拒绝分支仅由专项回归覆盖，旧空编辑失败保留。DeepSearch修复单格已结束，最终custom Judge完成，baseline和candidate_dev40轮无Judge，按预算部分覆盖展示，不能算完整通过。

本次新增TriviaQA与τ² Airline，各24格。TriviaQA默认全train+validation首次公开check-only在第4/7个train分片仍准备中；无模型时保存原日志、确认仅预检进程组后停止，改用公开dataset.splits选择完整rc.wikipedia validation池、固定1/1/1，源码/原始记录不变。新公开plan/check-only已成功，首项真实baseline/Worker/candidate/test和官方别名EM/F1完成，当前仍等离线审计，未提前计通过。τ²使用公开README和内置原生harness，官方v1.0.1/airline native train自定义1/1/1，独立DeepSeek用户模拟器，原生max_steps8、Task600/1200、Target8/40、Worker原预算。首项外部审计原先只看finished和reward映射误记flow_passed，深查RewardInfo确认MAX_STEPS提前终止规则0、DB/COMMUNICATE未执行，因此保留raw结果并以native-budget-review改记部分覆盖；修正仅外部收集器，后续同类记录不能算完整通过，不加预算重跑。

MuSiQue新增独立evolution_split能力，完整官方train19938与dev2417先按ID及规范化原始问题做全池重叠检查，再抽取1/1/1，仅替换train，保留dev/test与原生context/support评分。共用QA基类逻辑替代Hotpot中的重复实现，算法/gate未改。7项新检查先失败，受影响78项测试、Ruff、新wheel独立安装/CLI及MuSiQue/Hotpot两个模式原生评分/全池重叠检查通过。两个Target公开预检均Ready1/1/1，完整真实数据context及support参考评分3/3、dev/test不变的离线探针也通过，均0模型，不是两格真实通过。新269源根已排在smoke2的AIME2025批次及SkillOpt修复单格之后，旧缺数据记录保留，见[接入说明](musique-independent-evolution.md)、[验证](validation-musique-independent-20261026.json)、[原生数据](validation-musique-independent-native-20261026.json)。smoke2在核对proc与保留依赖清单后只清5个已结束批次的可重建env，实际释放4,673,699,840字节，清后8.25GiB、准备新角色环境后当前约5.7GiB；活跃/后续环境及源码/实验/usage/原始数据/镜像和文档保留。

[SQ26E]: smoke-searchqa-modular-independent-smoke3-20261026.json

[TW26E]: smoke-twowiki-modular-independent-smoke2-20261026.json

[TP26]: smoke-travelplanner24-public-smoke3-20261026.json

[BC26]: smoke-browsecomp24-public-smoke2-20261026.json

[LM26]: smoke-livemathbench24-public-original-20261026.json

[TR26]: smoke-tau2-retail24-public-original-20261026.json

[WS26]: smoke-widesearch24-cachefix-public-smoke3-20261026.json

[BB26E]: smoke-bbeh-modular-independent-original-20261026.json

[TB26]: smoke-tau3-banking24-public-original-20261026.json

[SG26E]: smoke-supergpqa-modular-independent-original-20261026.json

[TQ26E]: smoke-triviaqa-modular-independent-original-20261026.json

[SQ26T]: smoke-searchqa-trivia-modular-independent-original-20261026.json

[SW26R]: smoke-swe-lite-runtime-recovery-modular-smoke2-20261026.json

[AW26E]: smoke-appworld-modular-independent-original-20261026.json

[WS26E]: smoke-widesearch-judge-evidence-model-smoke3-20261026.json

[BB27R]: smoke-bbeh-modular-authorized-retry-original-20261026.json
[MU27R]: smoke-musique-modular-authorized-retry-smoke2-20261026.json

[SQ27R]: smoke-searchqa-modular-authorized-retry-original-20261026.json

[BB27B]: smoke-bbeh-darwinx-budget-retry-20261027.json

[AI27B]: smoke-aime2026-budget-retry-20261027.json
[CX27B]: smoke-crux-rrsi-budget-retry-20261027.json

[M527B]: smoke-math500-budget-retry-20261027.json
[SW27B]: smoke-swe-modular-budget-retry-20261027.json
[WS27B]: smoke-widesearch-opro-cc-budget-retry-20261027.json

[AW27B]: smoke-appworld-budget-retry-20261027.json
[WS27J]: smoke-widesearch-judge-budget-retry-20261027.json
[BC27B]: smoke-browsecomp-opro-budget-retry-20261027.json

[M527T]: smoke-math500-worker-turn-budget-20261027.json
[BC27A]: smoke-browsecomp-adas-budget-retry-20261027.json
[DS27S]: smoke-deepsearch-skillopt-budget-retry-20261027.json

[BC27ACE]: smoke-browsecomp-ace-budget-retry-20261027.json

[BC27E]: smoke-browsecomp-evoprompt-budget-retry-20261027.json
[DS27A]: smoke-deepsearch-ace-budget-retry-20261027.json

[BC27G]: smoke-browsecomp-gepa-budget-retry-20261027.json

[BC27S]: smoke-browsecomp-skillopt-budget-retry-20261027.json
[DS27E]: smoke-deepsearch-evoprompt-budget-retry-20261027.json

[BC27ACC]: smoke-browsecomp-adas-cc-budget-retry-20261027.json
[DS27G]: smoke-deepsearch-gepa-budget-retry-20261027.json

[BC27MH]: smoke-browsecomp-metaharness-budget-retry-20261027.json
[DS27DX]: smoke-deepsearch-darwinx-budget-retry-20261027.json

[DS27EH]: smoke-deepsearch-evoharness-budget-retry-20261027.json
[DS27MH]: smoke-deepsearch-metaharness-budget-retry-20261027.json
[BC27EH]: smoke-browsecomp-evoharness-budget-retry-20261027.json

[OQ27AHE]: smoke-officeqa-ahe-budget-retry-20261027.json
[OQ27OP]: smoke-officeqa-opro-budget-retry-20261027.json

[OQ27ACE]: smoke-officeqa-ace-budget-retry-20261027.json

[OQ27EV]: smoke-officeqa-evoprompt-budget-retry-20261027.json

[OQ27G]: smoke-officeqa-gepa-budget-retry-20261027.json

[OQ27DX160]: smoke-officeqa-darwinx-budget160-20261027.json

[OQ27ACE160]: smoke-officeqa-ace-budget160-20261027.json

[OQ27GEPA160]: smoke-officeqa-gepa-budget160-20261027.json

[OQ27OPRO160]: smoke-officeqa-opro-budget160-20261027.json

[OQ27SK160]: smoke-officeqa-skillopt-budget160-20261027.json

[OQ27R160]: smoke-officeqa-rrsi-budget160-20261027.json

[OQ27MH160]: smoke-officeqa-metaharness-budget160-20261027.json

[OQ27EH160]: smoke-officeqa-evoharness-budget160-20261027.json
[OQ27ADM120]: smoke-officeqa-adas-mini-worker120-20261027.json

[BC28G160]: smoke-browse-gepa-budget160-20261027.json

[BC28ACE160]: smoke-browse-ace-budget160-20261027.json

[DS28MH160]: smoke-deepsearch-metaharness-budget160-20261027.json

[BC28OPRO160]: smoke-browse-opro-budget160-20261028.json

[TB28BM100]: smoke-banking-bm25-opro-mini-steps100-20261028.json

[TB28SK100]: smoke-banking-bm25-steps100-skillopt-miniagent-20261028.json

[TB28ACE100]: smoke-banking-bm25-steps100-ace-miniagent-20261028.json

[TA28OP30]: smoke-tau2-airline-opro-mini-steps30-20261028.json

[BC28DX160]: smoke-browse-darwinx-budget160-20261028.json

[TB28EVOPROMPTM100]: smoke-banking-bm25-steps100-evoprompt-miniagent-20261028.json

[TB28GEPAM100]: smoke-banking-bm25-steps100-gepa-miniagent-20261028.json

[TB28OPROCC100]: smoke-banking-bm25-steps100-opro-claude_code-20261028.json

[TB28SKILLOPTCC100]: smoke-banking-bm25-steps100-skillopt-claude_code-20261028.json

[TB28AHEM100]: smoke-banking-bm25-steps100-ahe-miniagent-20261028.json

[BC28EVO_HARNESSCC160]: smoke-browse-evoharness-budget160-20261028.json

[TA28SKILLOPTM100]: smoke-tau2-airline-steps100-skillopt-miniagent-20261028.json

[TA28ACEM100]: smoke-tau2-airline-steps100-ace-miniagent-20261028.json

[TA28EVOPROMPTM100]: smoke-tau2-airline-steps100-evoprompt-miniagent-20261028.json

[TA28GEPAM100]: smoke-tau2-airline-steps100-gepa-miniagent-20261028.json

[TB28AHECC100]: smoke-banking-bm25-steps100-ahe-claude_code-20261028.json

[TB28ACECC100]: smoke-banking-bm25-steps100-ace-claude_code-20261028.json

[TB28EVOPROMPTCC100]: smoke-banking-bm25-steps100-evoprompt-claude_code-20261028.json

[TB28GEPACC100]: smoke-banking-bm25-steps100-gepa-claude_code-20261028.json

[TA28OPROCC100]: smoke-tau2-airline-steps100-opro-claude_code-20261028.json

[TB28ADASM100]: smoke-banking-bm25-steps100-adas-miniagent-20261028.json

[BC28RRSICC160]: smoke-browse-rrsi-budget160-20261028.json

[TR28OPROM100]: smoke-tau2-retail-opro-mini-native100-20261028.json

[TA28SKILLOPTCC100]: smoke-tau2-airline-steps100-skillopt-claude_code-20261028.json

[TA28AHEM100]: smoke-tau2-airline-steps100-ahe-miniagent-20261028.json

[TA28ACECC100]: smoke-tau2-airline-steps100-ace-claude_code-20261028.json

[TA28EVOPROMPTCC100]: smoke-tau2-airline-steps100-evoprompt-claude_code-20261028.json

[TA28GEPACC100]: smoke-tau2-airline-steps100-gepa-claude_code-20261028.json

[TA28ADASM100]: smoke-tau2-airline-steps100-adas-miniagent-20261028.json

[TA28ADASCC100]: smoke-tau2-airline-steps100-adas-claude_code-20261028.json

[TB28ADASCC100]: smoke-banking-bm25-steps100-adas-claude_code-20261028.json

[TB28DARWINXM100]: smoke-banking-bm25-steps100-darwinx-miniagent-20261028.json

[TB28DARWINXCC100]: smoke-banking-bm25-steps100-darwinx-claude_code-20261028.json

[TR28SKILLOPTM100]: smoke-tau2-retail-native100-skillopt-miniagent-20261028.json

[TR28ACEM100]: smoke-tau2-retail-native100-ace-miniagent-20261028.json

[TR28EVOPROMPTM100]: smoke-tau2-retail-native100-evoprompt-miniagent-20261028.json

[TR28GEPAM100]: smoke-tau2-retail-native100-gepa-miniagent-20261028.json

[TR28OPROCC100]: smoke-tau2-retail-opro-cc-native100-20261028.json

[TA28DARWINXM100]: smoke-tau2-airline-steps100-darwinx-miniagent-20261028.json

[TA28DARWINXCC100]: smoke-tau2-airline-steps100-darwinx-claude_code-20261028.json

[TA28META_HARNESSM100]: smoke-tau2-airline-steps100-meta_harness-miniagent-20261028.json

[TB28MHMW120]: smoke-banking-bm25-meta-mini-worker120-20261028.json

[TB28META_HARNESSCC100]: smoke-banking-bm25-steps100-meta_harness-claude_code-20261028.json

[TB28EVO_HARNESSM100]: smoke-banking-bm25-steps100-evo_harness-miniagent-20261028.json

[TB28EVO_HARNESSCC100]: smoke-banking-bm25-steps100-evo_harness-claude_code-20261028.json

[TR28SKILLOPTCC100]: smoke-tau2-retail-native100-skillopt-claude_code-20261028.json

[TR28ACECC100]: smoke-tau2-retail-native100-ace-claude_code-20261028.json

[TR28EVOPROMPTCC100]: smoke-tau2-retail-native100-evoprompt-claude_code-20261028.json

[TR28GEPACC100]: smoke-tau2-retail-native100-gepa-claude_code-20261028.json

[TA28META_HARNESSCC100]: smoke-tau2-airline-steps100-meta_harness-claude_code-20261028.json

[TA28EVO_HARNESSM100]: smoke-tau2-airline-steps100-evo_harness-miniagent-20261028.json

[TA28EVO_HARNESSCC100]: smoke-tau2-airline-steps100-evo_harness-claude_code-20261028.json

[TA28RRSIM100]: smoke-tau2-airline-steps100-rrsi-miniagent-20261028.json

[TA28RRSICC100]: smoke-tau2-airline-steps100-rrsi-claude_code-20261028.json

[TB28RRSIM100]: smoke-banking-bm25-steps100-rrsi-miniagent-20261028.json

[TB28RRSICC100]: smoke-banking-bm25-steps100-rrsi-claude_code-20261028.json

[TR28DARWINXM100]: smoke-tau2-retail-native100-darwinx-miniagent-20261028.json

[SW28F]: smoke-swe-modular-mini16-worker120-failure-audit-20261028.json

[TA28AHECCW120]: smoke-tau2-airline-ahecc-worker120-native100-20261028.json

[TR28AHECC100]: smoke-tau2-retail-native100-ahe-claude_code-20261028.json

[TR28ADASCC100]: smoke-tau2-retail-native100-adas-claude_code-20261028.json

[TR28DARWINXCC100]: smoke-tau2-retail-native100-darwinx-claude_code-20261028.json

[TR28META_HARNESSM100]: smoke-tau2-retail-native100-meta_harness-miniagent-20261028.json

[TR28EVO_HARNESSM100]: smoke-tau2-retail-native100-evo_harness-miniagent-20261028.json

[TR28EVO_HARNESSCC100]: smoke-tau2-retail-native100-evo_harness-claude_code-20261028.json

[TR28RRSIM100]: smoke-tau2-retail-native100-rrsi-miniagent-20261028.json

[TR28RRSICC100]: smoke-tau2-retail-native100-rrsi-claude_code-20261028.json

[SW28RRSICCW120]: smoke-swe-rrsicc-worker120-20261028.json

[WS28META8192W120]: smoke-widesearch-meta-judge8192-worker120-20261028.json

[BMS28C]: smoke-banking-modular-same-source-20261028.json

[CMS28M]: smoke-crux-modular-miniagent-same-source-20261028.json

[CMS28C]: smoke-crux-modular-claude_code-same-source-20261028.json

[WMS28M]: smoke-workbench-modular-miniagent-same-source-20261028.json

[WMS28C]: smoke-workbench-modular-claude_code-same-source-20261028.json

[AMS28C]: smoke-airline-modular-claude_code-same-source-20261028.json

[TAH28]: smoke-terminal-ahe-target80-20261028.json

[BMS28M]: smoke-banking-modular-mini-same-source-20261028.json

[AMS28MF]: smoke-airline-modular-miniagent-same-source-20261028.json

[NMS28C]: smoke-nq-modular-claude_code-same-source-20261028.json

[NMS28M]: smoke-nq-modular-miniagent-same-source-20261028.json

[TPJ28O]: smoke-travel-json-opro-miniagent-20261028.json

[TPJ28S]: smoke-travel-json-skillopt-miniagent-20261028.json

[AMS28M16384]: smoke-airline-modular-mini-output16384-20261028.json

[TPJ28CO]: smoke-travel-json-opro-claude-code-20261028.json

[TPJ28A]: smoke-travel-json-ace-miniagent-20261028.json

[TPJ28E]: smoke-travel-json-evoprompt-miniagent-20261028.json

[TPJ28G]: smoke-travel-json-gepa-miniagent-20261028.json

[TPJ28CS]: smoke-travel-json-skillopt-claude-code-20261028.json

[TPJ28CA]: smoke-travel-json-ace-claude-code-20261028.json

[TPJ28CE]: smoke-travel-json-evoprompt-claude-code-20261028.json

[TPJ28CG]: smoke-travel-json-gepa-claude-code-20261028.json

[TPJB28MAD]: smoke-travel-json-adas-mini-budget-20261028.json

[TPJB28MMH]: smoke-travel-json-meta_harness-mini-budget-20261028.json

[TPJB28CAH]: smoke-travel-json-ahe-claude-code-sdk-20261028.json

[TPJB28CAD]: smoke-travel-json-adas-claude-code-sdk-20261028.json

[TPJB28MDX]: smoke-travel-json-darwinx-mini-budget-20261028.json

[TPJB28CDX]: smoke-travel-json-darwinx-claude-code-sdk-20261028.json

[TPJB28CMH]: smoke-travel-json-meta_harness-claude-code-sdk-20261028.json

[TPJB28CEH]: smoke-travel-json-evo_harness-claude-code-sdk-20261028.json

[TPJR28MAH]: smoke-travel-json-ahe-mini-rest-20261028.json

[TPJR28MEH]: smoke-travel-json-evo_harness-mini-rest-20261028.json

[TPMSS28MF]: smoke-travel-modular-mini-worker60-failure-audit-20261028.json

[BFMSS28MF]: smoke-bfcl-modular-mini-failure-audit-20261028.json

[BCMSS28CP]: smoke-browse-modular-cc160-audit-20261028.json

[TPMSS28M16]: smoke-travel-modular-miniagent-output16384-group-20261028.json

[TPMSS28CF]: smoke-travel-modular-cc-output8192-failure-audit-20261028.json

[BCMSS28MF]: smoke-browse-modular-mini-worker60-failure-audit-20261028.json
