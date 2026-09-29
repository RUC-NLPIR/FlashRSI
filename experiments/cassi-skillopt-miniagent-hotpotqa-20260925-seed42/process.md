# 中间优化过程

|记录|类型|epoch/step|accepted|score|reason|
|---|---|---|---|---|---|
|00017-decision.json|fast|0/1|True|0.8066666666666666||
|00033-decision.json|fast|0/2|True|0.8166666666666667||
|00048-decision.json|fast|0/3|True|0.83||
|00061-decision.json|fast|0/4|False|0.8033333333333333||
|00076-decision.json|fast|1/5|False|0.8233333333333334||
|00091-decision.json|fast|1/6|False|0.8066666666666666||
|00105-decision.json|fast|1/7|True|0.8333333333333334||
|00119-decision.json|fast|1/8|False|0.8233333333333334||
|00125-decision.json|slow|1/|False|0.8333333333333334||
|00141-decision.json|fast|2/9|False|0.8166666666666667||
|00156-decision.json|fast|2/10|False|0.8333333333333334||
|00172-decision.json|fast|2/11|False|0.82||
|00183-decision.json|fast|2/12|False|0.8233333333333334||
|00188-decision.json|slow|2/|False||invalid_patch|
|00204-decision.json|fast|3/13|False|0.8233333333333334||
|00217-decision.json|fast|3/14|False|0.8333333333333334||
|00231-decision.json|fast|3/15|False|0.82||
|00246-decision.json|fast|3/16|False|0.8233333333333334||
|00252-decision.json|slow|3/|False|0.81||

完整修改、评分和理由见 [decisions.json](decisions.json)，可读版本见 [versions/index.json](versions/index.json)。原始 Worker 对话和逐题轨迹保留在 logs.tar.gz。

## Execution interruptions and recovery

Execution started at commit 39ff52b. At fast step 8 the Worker returned indices [0,1,3,5] for five edits (valid 0-4). Commit 86d115e added rank range/budget validation to the existing same-prompt protocol retry policy (at most two retries). All existing cache files were SHA256-verified unchanged before an audited plan-fingerprint migration; the first protocol retry succeeded. Configurations, frozen data and model budgets were unchanged. Historical error.json and the original attempt remain in logs.tar.gz; the final attempt is finished. See run/evidence/rank-recovery.json and rank-recovery-source.tar.gz in the archive.

All 16 fast decisions and three slow decisions are exported. Four fast candidates were accepted. The epoch-2 slow update was rejected as invalid_patch; the other two slow updates did not improve dev. Rejected updates and raw Worker replies remain in the archive. Test EM decreased from 160/300 to 156/300: 17 improved and 21 regressed, paired difference -1.33 percentage points (bootstrap 95% interval -5.33 to +2.67). This run does not establish a test improvement.

Four target attempts exhausted the unchanged 32768-token budget; all four recovered through existing bounded retries, with matching successful cache keys verified. Failed attempt records and usage are preserved.
