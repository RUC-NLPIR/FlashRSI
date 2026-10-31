# Evaluate a Snapshot

Evaluate a selected or intermediate agent version without continuing evolution. The CLI command is **`flashrsi evaluate`**.

## Select the version and destination

Find the selected `snapshot_id` in the source run's `result.json`, then locate its JSON file under `snapshots/`. An intermediate candidate works too.

Choose a configuration for the destination benchmark. It supplies task data, test split, Target model, and connection settings:

```bash
flashrsi evaluate \
  --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run/snapshots/SELECTED_ID.json \
  --check-only
```

`--check-only` validates setup without model calls. It can prepare data and dependencies.

## Run test evaluation

```bash
flashrsi evaluate \
  --config examples/evaluate_hotpotqa.yaml \
  --snapshot /path/to/run/snapshots/SELECTED_ID.json \
  --model gpt-5-mini \
  --set agent.llm.api_key="$TARGET_API_KEY"
```

Only the destination test split runs. No Worker is constructed and no search continues. Use `--output-dir` to select a different parent directory for the evaluation records.

## Keep resources compatible

The saved version must match the destination Agent's type, root resource version, and component rules. Reuse the source run's resource source and mappings when needed. A MiniAgent Snapshot cannot be loaded as a Claude Code Snapshot.

The Snapshot selects resource files. The destination configuration selects the model and connection; those settings do not come from saved credentials.

## Compare versions fairly

Evaluate the initial and improved versions with the same destination configuration, seed, test tasks, and grading policy. The evolution runner evaluates the final selected version on test; it does not automatically produce a matched initial test baseline.

Inspect `test_tasks`, task failures, and trajectories alongside the aggregate score. For exact compatibility checks, configuration mode, and file outputs, see the [evaluation reference](../snapshot-evaluation.md).
