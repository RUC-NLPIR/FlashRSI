---
name: fpbase-spectral-peaks-read-from-states
description: Use when a task selects or validates donor/acceptor fluorescent proteins by peak excitation or emission through the FPbase API and direct top-level ex_max/em_max reads return None.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [protein-assembly]
---
# Read FPbase spectral peaks from per-state records

FPbase protein records do not expose spectral peaks as top-level `ex_max`/`em_max` keys. Peak excitation and emission are stored per state, so read them from the relevant state object before filtering or validating candidates.

Procedure:
1. Fetch and inspect a record before matching:
   ```python
   p = fpbase_protein(...)  # or requests.get(f"https://www.fpbase.org/api/proteins/{slug}/")
   print(p)
   ```
2. If direct reads are None, inspect the states list:
   ```python
   print(p.get("states"))
   ```
3. Read the relevant/default state, e.g.:
   ```python
   ex = p["states"][0].get("ex_max")
   em = p["states"][0].get("em_max")
   print(ex, em)
   ```
4. Use these per-state values for any candidate scoring or donor/acceptor matching; do not trust top-level keys.

Why: an execution script printed candidates like `('10B', None, None, 33)` because it read top-level `ex_max`/`em_max`; the mCherry record actually stores them as `{"states": [{"ex_max": 587, "em_max": 610, ...}]}`.

Supporting evidence: protein-assembly (this batch).
