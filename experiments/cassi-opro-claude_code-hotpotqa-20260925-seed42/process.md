# 中间优化过程

|记录|类型|epoch/step|accepted|score|reason|
|---|---|---|---|---|---|
|00042-decision.json|promote|/|True|0.8733333333333333||

完整修改、评分和理由见 [decisions.json](decisions.json)，可读版本见 [versions/index.json](versions/index.json)。原始 Worker 对话和逐题轨迹保留在 logs.tar.gz。
## All candidate training scores

|Candidate|Round|Train EM|
|---|---|---|
|0|0|82.6667%|
|1|1|85.3333%|
|2|1|80.0000%|
|3|1|82.0000%|
|4|1|78.0000%|
|5|2|86.0000%|
|6|2|86.6667%|
|7|2|86.6667%|
|8|2|84.6667%|
|9|3|87.3333%|
|10|3|85.3333%|
|11|3|86.0000%|
|12|3|86.6667%|
|13|4|84.6667%|
|14|4|86.0000%|
|15|4|84.6667%|
|16|4|86.6667%|
|17|5|86.6667%|
|18|5|83.3333%|
|19|5|86.6667%|
|20|5|86.0000%|

Full instructions and snapshot IDs: [candidate-history.json](candidate-history.json). Selection uses training EM only; ties retain earlier instructions.

## Execution and limitations

This is an OPRO HotpotQA/harness adaptation using5 rounds x4 candidates, not the paper default budget. All20 candidates and the initial instruction are exported. Executed at commitfb4d513 with ordinary runner fingerprint unchanged from the prepared86d115e plan; the new MiniAgent recovery script was not used by this Claude Code experiment. The prepared rank-recovery evidence reflects pre-run preparation migration, not a failure of this run.

Target32768tokens/600s/10turns and Worker65536tokens/900s remained unchanged. One target attempt reached10turns and another timed out at600s; both recovered using the existing retry budget. Matching successful cache keys were verified; both failed records and usage remain archived.

Test EM150/300 to157/300 (+2.33pp),16 improved and9 regressed; paired bootstrap95% interval -1.00 to+5.67pp. F1 increased from67.04% to67.63%. The interval includes zero; this single-seed run does not establish reliable improvement.
