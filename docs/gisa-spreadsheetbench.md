# GISA and SpreadsheetBench V1

Both adapters use the fixed packages in [RUC-NLPIR/FlashRSI](https://huggingface.co/datasets/RUC-NLPIR/FlashRSI/tree/5976205472dde244a54652715aec9b3bcc721fc7). They keep task resources and reference answers outside the evolvable harness Snapshot. Changing algorithms or evaluating a saved Snapshot uses the existing runner and [evaluation command](snapshot-evaluation.md).

| Registry / HF config | train | dev | test | Runtime |
| --- | ---: | ---: | ---: | --- |
| `gisa` | 120 | 53 | 200 | Docker, model endpoint, search service |
| `spreadsheetbench` | 399 | 110 | 400 | Python 3.12+, Docker Compose, Harbor, LibreOffice |

These are FlashRSI experiment partitions, not a claim to reproduce an upstream leaderboard protocol. `spreadsheetbench` is V1; the existing `spreadsheetbench2` adapter remains separate.

## Start an experiment

Copy [gisa_opro.yaml](../examples/quickstarts/gisa_opro.yaml) or [spreadsheetbench_opro.yaml](../examples/quickstarts/spreadsheetbench_opro.yaml) to a sibling `*.local.yaml`. Fill in Target and Worker `model_name`, `api_key`, and `base_url`. For GISA, also fill in `benchmark.retrieval.api_key` for Serper; the shared bridge also supports Tavily or a compatible JSON search endpoint, and direct page reading or Jina.

From the project root:

```bash
python scripts/run_experiment.py --config examples/quickstarts/gisa_opro.local.yaml --plan
python scripts/run_experiment.py --config examples/quickstarts/gisa_opro.local.yaml --check-only
python scripts/run_experiment.py --config examples/quickstarts/gisa_opro.local.yaml
```

Use the SpreadsheetBench configuration path for the spreadsheet run. The launcher installs dependencies, resolves and verifies the HF files, binds the task adapter, runs evolution, and tests the algorithm's selected Snapshot. `--check-only` does not execute models or prove that container builds will succeed. Docker must already be available; model and search credentials are supplied by the user.

The examples select three instructions in total using `limit: 3`. Remove `limit` to use the full fixed splits. Keep `split: auto`; do not add `split_counts`. See [HF prepared data](hf-prepared-data.md) for sampling and cache behavior.

## GISA

The adapter decrypts questions at load time using the upstream canary scheme. Keep plaintext questions and their execution traces out of public exports. Reference CSVs remain on the host; human reference search traces are not downloaded or exposed to the Target.

The Target uses its native shell to call the task-local search/read client. Its final answer must contain a fenced TSV block with a header. Item, set and list answers use one column; table answers use the requested columns. The [official evaluator](https://github.com/RUC-NLPIR/GISA/blob/8b05d80811f8f474d154e35496fc620807adf3f4/eval_script/run_evaluation.py) is downloaded from a pinned commit and checked against SHA-256. No judge model is needed. The primary metric is `global_em`; the official item/set/list/table metrics are also retained per trajectory. Model output is always parsed as text, never as an evaluator-host filename.

Train and dev contain stable questions. Test contains **50 stable and 150 live** questions. Each Task preserves `metadata.question_type`; report the two test groups separately when comparing models. Live references reflect the pinned dataset version. The adapter supplies the harness with web access; it does not replace the harness with GISA's reference ReAct agent or page-summary model. GISA is licensed under Apache-2.0; cite its [upstream repository](https://github.com/RUC-NLPIR/GISA).

## SpreadsheetBench V1

Train/dev use the Full collection's remaining 512 instruction IDs; test uses the 400 Verified IDs. Their workbook case counts are **1196 / 336 / 400**. Every instruction keeps all of its cases in the same split. Three records have empty instructions: train ID `55877`, and dev IDs `55224` and `55457`. They are skipped before sampling; their IDs and reasons are recorded in benchmark metadata as `excluded_tasks`. The runnable pool is **399 / 110 / 400** instructions (**1193 / 330 / 400** cases), while the original HF files and manifest counts remain unchanged.

Each case runs in a fresh Harbor task with only that case's input workbook. The Target saves an output workbook under `/logs/artifacts/`. A separate verifier image contains the reference workbook, answer ranges, and the [pinned upstream evaluator](https://github.com/RUCKBReasoning/SpreadsheetBench/tree/49b73a94775fb489063f60ca1865e3a650079a79/evaluation). LibreOffice recalculates workbooks before the official cell comparison. Missing or invalid outputs receive zero. Formula behavior follows LibreOffice, rather than claiming Excel parity.

The primary `reward` is the official **hard restriction**: an instruction passes only if all its cases pass. `soft_restriction` records the fraction of passing cases. Case conversations and usage are retained in the instruction trajectory, while the cases execute without sharing conversation state. Reference workbooks and cell values do not enter the solver image or Worker feedback.

The HF package preserves all 400 Verified records, including upstream exclusion notes for IDs `56225` and `56274`. This adapter evaluates the published pool without silently dropping either record, matching the pinned evaluator's iteration over all supplied records. The notes remain in `Task.metadata.upstream_exclude`; disclose the evaluated ID set when comparing against results that exclude those records.

Workbook archives are downloaded only for selected splits; each selected archive is verified against the manifest. The evaluator files are small downloads from GitHub. Docker layers and LibreOffice installation packages are fetched during container builds, not bundled into HF. Dataset and evaluator provenance are available in the [upstream repository](https://github.com/RUCKBReasoning/SpreadsheetBench); the data is distributed under CC BY-SA 4.0.
