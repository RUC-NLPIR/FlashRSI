# Framework & Snapshot

FlashRSI treats an agent as a versioned tree of resources. An algorithm edits a declared part of that tree; the harness runs the complete candidate; the benchmark returns trajectories and scores.

## What a Snapshot contains

A Snapshot is an immutable version of the resources declared by a harness adapter. Files are tagged by role through `components.yaml`, for example:

```text
agent/
├── prompts/       prompt
├── skills/        skill
├── tools/         tool
├── runtime/       code
└── settings/      config
```

Tags describe roles rather than requiring a universal directory layout. A closed harness may expose instructions and settings; a small open harness may also expose its runtime code.

## How a Snapshot is stored

The persisted artifact is one JSON file, normally
`runs/<run-id>/snapshots/<snapshot-id>.json`. It contains the Snapshot schema and the complete declared
file tree:

| Field | Meaning |
| --- | --- |
| `format_version` | Snapshot schema version; the current format is `2`. |
| `agent_type` | Harness adapter that owns the resources. |
| `component_rules` | Path patterns used to assign each file a role. |
| `id` | SHA-256 identifier of the canonical file and metadata payload. |
| `root_id`, `parent_id` | The root version and immediate ancestor in the candidate lineage. |
| `files` | Relative paths mapped to base64 file bytes, component labels, and executable flags. |

Candidate creation starts from a temporary checkout. After an Agent edits the permitted files, `commit`
creates a new Snapshot whose `parent_id` points to the previous version. The complete candidate is exported
again for native harness execution. Credentials, task data, logs, and the temporary editing scope are not
stored in this JSON. `save()` writes atomically and refuses to replace an existing path.

Credentials, benchmark data, temporary logs, and runtime state stay outside the resource version. The run directory stores candidate lineage, changed paths, trajectories, and scores.

## Scoped edits, complete execution

An editing scope selects which resource roles an algorithm can read and change. For example, a skill method edits `skill` files while the candidate still contains its unchanged prompts, tools, and configuration.

```text
Snapshot resources
  ├── scoped view → algorithm → candidate Snapshot
  └── complete candidate → harness → benchmark → feedback

After search: selected Snapshot → held-out test evaluation
```

The complete version is materialized for execution. A skill's score therefore reflects its behavior inside the surrounding agent. Test feedback does not feed back into search.

## Who owns each decision

| Component | Responsibility |
| --- | --- |
| Runner | Load configuration, assemble collaborators, bind environments, save records. |
| Algorithm | Propose changes, interpret feedback, manage memory, select/adopt candidates. |
| Agent adapter | Declare resources and call the selected harness execution path. |
| Benchmark | Load tasks, prepare task environments, grade trajectories. |
| Snapshot | Retain resource versions, scopes, parentage, and file changes. |

The **Target** solves tasks. The **Worker** proposes edits or edits files. Their models and connection settings are independent and are fixed for each execution call.

## Map different harnesses

| Harness shape | Mapping | Example |
| --- | --- | --- |
| Closed / interface-first | Version stable exposed resource interfaces. | Claude Code instructions, plugins, hooks, and settings through its SDK. |
| Clean open source | Map native files directly and tag their roles. | MiniAgent prompts, skills, tools, and Python code. |
| Complex open source | Reduce the runtime surface or port supported behavior against a pinned baseline, document limits, then version that implementation. | Codex's Snapshot-local Python core, based on a fixed Rust baseline. |

The Codex integration is a semantic port with explicit coverage limits. See [its migration boundary](../codex-core-extraction.md) before making equivalence claims.

## Extend one boundary at a time

- [Add a benchmark](./benchmark.md) to introduce tasks and grading.
- [Add a harness](./harness.md) to version and execute another agent.
- [Add an algorithm](./algorithm.md) to implement a different search policy.
- [Python API](../usage.md#python-api) to assemble an experiment directly.
