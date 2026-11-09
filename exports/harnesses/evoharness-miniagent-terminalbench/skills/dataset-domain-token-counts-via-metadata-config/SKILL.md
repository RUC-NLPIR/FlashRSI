---
name: dataset-domain-token-counts-via-metadata-config
description: Use when a HuggingFace dataset task asks for token counts or filtering by a named domain and the dataset has multiple configs, only one of which contains domain and token-text columns.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [count-dataset-tokens]
---
# Use the metadata config for domain-filtered token counts on OpenThoughts-style datasets

When a dataset task asks for domain-level token counts, do not assume the `default` config has the needed columns. Inspect the available configs and load the one that actually holds domain labels and reasoning/solution text.

Procedure:
1. List configs before loading:
   ```python
   from datasets import get_dataset_config_names
   print(get_dataset_config_names("ryanmarten/OpenThoughts-1k-sample"))
   ```
2. Read the dataset card or README for documented configs and domain groupings.
3. Load the config with the domain and token-text columns, often `metadata`, instead of `default`:
   ```python
   from datasets import load_dataset
   ds = load_dataset("ryanmarten/OpenThoughts-1k-sample", "metadata")
   ```
4. Map README category names to the actual metadata domain values. For example, a `Science` category usually corresponds to `physics`, `chemistry`, and `biology`; do not search for a literal `science` domain value.
5. Validate before counting:
   ```python
   print(ds["train"].column_names)
   print(ds["train"].unique("domain"))
   ```

Why: on `ryanmarten/OpenThoughts-1k-sample` the `default` config only has `system` and `conversations`, while `domain`, `deepseek_reasoning`, and `deepseek_solution` live in the `metadata` config. Counting tokens by domain from `default` returns no domain labels and can silently count the wrong text.

Supporting evidence: count-dataset-tokens (this batch).
