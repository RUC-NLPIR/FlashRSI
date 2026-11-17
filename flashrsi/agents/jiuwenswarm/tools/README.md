# Snapshot tools

Add a directory `tools/<name>/` with two files. FlashRSI registers its manifest through JiuwenSwarm's native Process SDK for each run of this Snapshot.

For example, `tools/word_count/tool.json` declares the name, description and JSON Schema presented to the model.

```json
{
  "name": "word_count",
  "description": "Count whitespace-separated words in text.",
  "input_schema": {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"]
  }
}
```

The name must match the directory. Put the implementation in `tools/word_count/run.py`.

```python
import json
import sys

arguments = json.load(sys.stdin)
print(json.dumps({"count": len(arguments["text"].split())}))
```

Each call starts the Target's Python interpreter in the current task workspace. Read one JSON object from stdin and write one JSON value to stdout. Use stderr for diagnostics and a nonzero exit code for failures. A script can resolve accompanying data relative to `__file__`. The runtime environment supplies any required dependencies.

When the evolution algorithm grants write access to the `tool` component, its Worker can add, edit or remove these directories. The selected Snapshot determines the available tool set on each run.
