# 中间优化过程

|记录|类型|epoch/step|accepted|score|reason|
|---|---|---|---|---|---|
|00042-decision.json|promote|/|True|0.88||

完整修改、评分和理由见 [decisions.json](decisions.json)，可读版本见 [versions/index.json](versions/index.json)。原始 Worker 对话和逐题轨迹保留在 logs.tar.gz。
## All candidate training scores

|Candidate|Round|Train EM|
|---|---|---|
|0|0|83.3333%|
|1|1|86.0000%|
|2|1|84.6667%|
|3|1|86.0000%|
|4|1|85.3333%|
|5|2|88.0000%|
|6|2|86.6667%|
|7|2|85.3333%|
|8|2|86.6667%|
|9|3|84.6667%|
|10|3|86.6667%|
|11|3|87.3333%|
|12|3|84.6667%|
|13|4|86.6667%|
|14|4|87.3333%|
|15|4|83.3333%|
|16|4|85.3333%|
|17|5|87.3333%|
|18|5|86.0000%|
|19|5|86.0000%|
|20|5|86.6667%|

Full instruction text and snapshot IDs: [candidate-history.json](candidate-history.json). Selection uses training EM only; ties retain the earlier instruction.

## Budget and recovery disclosure

This is an OPRO adaptation to HotpotQA and agent harnesses, with a reduced 5-round x4-candidate search budget, not a strict reproduction of the paper's default budget. Frozen150/300/300 seed42 data and all20 candidate evaluations were retained.

The run started at commit86d115e and stopped during initial-test after the same task twice exhausted32768 tokens. User authorized token escalation. Commitfb4d513 adds length-only recovery at65536 tokens/900s, at most two persistent extra attempts per logical task. All3401 pre-recovery cache records were SHA256-verified unchanged before audited fingerprint migration. Five logical requests ultimately recovered, each using one64k attempt. Six failed attempts are retained, including the initial two32k failures; reasoning stayed high. Successful original calls were reused. Baseline config remains32k/600s; actual recovery configurations are in ResponseRecovery/RunConfig messages. Do not describe this run as using32k uniformly.

Historical interruption, old summaries, source archives and migration evidence are preserved in logs.tar.gz. Test EM153/300 to156/300 (+1pp),17 improved and14 regressed; paired bootstrap95% interval -2.67 to+4.67pp. F1 decreased. This single run does not establish a reliable improvement.
