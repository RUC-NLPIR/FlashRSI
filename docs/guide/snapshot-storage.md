# Snapshot storage

A Snapshot is a versioned resource tree. Its durable representation is a single JSON file, not a directory of loose files:

```text
runs/<algorithm>-<agent>-<benchmark>-<timestamp>/
└── snapshots/
    ├── <initial-id>.json
    ├── <candidate-id>.json
    └── worker.json
```

`worker.json` is the Worker harness version when the Worker has versioned resources. Candidate files use their content address as the filename.

## JSON contents

The current schema is `format_version: 2`:

```json
{
  "format_version": 2,
  "agent_type": "miniagent",
  "root_id": "…",
  "parent_id": "…",
  "component_rules": {"prompt": ["prompts/**"]},
  "files": {
    "prompts/main.md": {
      "content": "<canonical base64 bytes>",
      "component": "prompt",
      "executable": false
    }
  },
  "id": "<sha256>"
}
```

The actual file content is encoded as base64 so arbitrary bytes and executable files can be represented in JSON. The ID is calculated from a canonical serialization of the files, component rules, agent type, parent metadata, and format version. A changed file therefore produces a new ID. Descendants retain both `root_id` and `parent_id`, which makes candidate lineage explicit.

## From JSON to execution

`Snapshot.load(path)` parses and validates the schema, canonical base64, relative paths, component labels, and SHA-256 ID. `Snapshot.check_out()` exports the permitted view to a temporary directory; native harness execution uses the complete candidate tree. After the call, the temporary checkout is removed.

The algorithm's read/write scope is an ephemeral permission view. It controls which files a Worker can see or edit, but it does not change the Snapshot contents or become part of the persisted JSON. Credentials, benchmark data, logs, and runtime state stay outside the Snapshot.

`Snapshot.save(path)` writes through a temporary file, flushes it with `fsync`, and links it into place without replacing an existing file. This keeps a saved version immutable and prevents a partial write from looking like a valid candidate.

For evaluation commands, start with [Evaluate a Snapshot](./evaluation.md). For the resource boundary and candidate lifecycle, see [Framework & Snapshot](../development/framework.md).
