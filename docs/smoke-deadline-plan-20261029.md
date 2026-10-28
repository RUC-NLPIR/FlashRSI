# Smoke 今日排期

**新截止：北京时间2026-10-28 23:59（用户已确认，覆盖原10-29截止）。**

按用户清单集中验证19类；AIME两年分别记，所以原清单20个数据范围，当前472/480格通过、剩8。另含TravelPlanner24格，新增SpreadsheetBench 2计划24格，重点范围合计待验证35格；未将SpreadsheetBench2准备计入原624格实跑总表。

| 机器 | 当前 | 后续重点 |
| --- | --- | --- |
| smoke2 · 37411 | BFCL同源Modular/Mini Target16/Worker120/输出16384 | 旧8轮/Worker60失败已审计；CC原生安装未ready仍不派 |
| smoke3 · 38944 | 无模型 | 有据准备重点缺格，原Terminal配置未恢复不冒称ready |
| smoke4 · 33746 | 新Browse同源Modular组，先Mini Worker120/输出16384，再CC240/7200 | 旧CC160/4800结束partial，缺usage未知保留；新一项非通过即停 |
| smoke5 · 36791 | Travel同源Modular/Mini已通过，CC Worker输出16384新配置 | CC旧8192输出失败已审计；仅Worker16384，Target40/Worker60保持 |

- 11:30—13:00：并行预检同源缺格、Travel原生格式问题、SpreadsheetBench2数据和评分依赖。
- 13:00—20:00：条件齐备组合唯一顺序队列；不重复通过格，任务结束即原生审计接续。
- 20:00—22:30：只做有证据的一次恢复及可及时完成的组合。
- 22:30—23:59：终结、审计与逐项验收；保留真实失败，不用准备冒充模型通过。

LiveMath按用户验收口径列“下载访问条件例外”，不挡本次交付；原24格无模型记录保持。题型同属竞赛数学，但不能由MATH500通过推断LiveMath原生Judge/GPass已实跑。

SpreadsheetBench2当前源码已有Harbor接入并修复评分容器构建入口，尚无真实容器/模型结果。官方数值任务需Docker及LibreOffice重算与原生评分；Visualization另需Windows Excel/WPS COM及glm-4.6v。先证明依赖与原生评分可用，再唯一派模型，不能保证今天全24格通过。

Office/Deep/Wide/Retail降为非重点，保留已有记录，不继续追预算。Modular旧独立来源限制已由用户取消，现用普通train/dev/test并保留train ID隔离；24格旧⊘仅为历史状态。保护原生评分/回复/heldout、1/1/1/seed及usage，缺usage未知非0。

[重点范围与容量核算](smoke-focus-20261028.json) · [逐格状态](smoke-deadline-plan-20261029.json) · [历史总表](smoke-matrix.md)
