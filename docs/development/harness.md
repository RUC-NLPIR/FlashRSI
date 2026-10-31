# Add a harness

Declare the harness resources and implement an Agent adapter that calls its execution entry point. Preserve the harness's own tools and control flow inside that boundary.

## Choose the resource mapping

### Closed or interface-first

Map the stable interfaces the harness exposes: instructions, skills, hooks, service registrations, and settings. Let its SDK or CLI own proprietary execution. [Claude Code](../agent-integration.md) uses this approach.

### Clean open source

Map the source files directly and tag them by role. Load code and resources from the selected Snapshot at execution time. [MiniAgent](../../flashrsi/agents/miniagent) is the simplest complete example.

### Complex open source

Identify the execution surface needed by the experiment and pin an upstream baseline. If you reduce or port it, document the supported behavior and test it against that baseline. The [Codex Python core](../codex-core-extraction.md) is a semantic port of supported paths, with explicit limits.

## Declare the resources

Place `components.yaml` beside the adapter. Match the harness's actual resource layout:

```yaml
code:
  - runtime/**
prompt:
  - prompts/**
skill:
  - skills/**
```

Keep adapter code, credentials, task inputs, and runtime state outside the declared resource patterns. These patterns define component membership; the algorithm separately chooses its observation and editing scope.

## Implement the execution entry

Subclass [`Agent`](../../flashrsi/core/agent.py), declare `name` and `description`, and implement the asynchronous `_run` method. It calls the native harness and returns a [`Trajectory`](../../flashrsi/core/trajectory.py).

| Adapter input | Use |
| --- | --- |
| `self.files_dir` | Selected version's code and resources. |
| `self.config` | Call-local role settings, model, credentials, and execution options. |
| `working_dir` | Task workspace or candidate directory to edit. |

Preserve messages and usage when the runtime provides them. On failure, return an error trajectory with diagnostics; close processes and SDK sessions when the call finishes.

## Register and verify it

Export the adapter from [`flashrsi/agents/__init__.py`](../../flashrsi/agents/__init__.py) and add it to the runner's [`_AGENTS` mapping](../../flashrsi/runner.py). Verify that changing a Snapshot changes the resources actually executed and that concurrent runs keep their configuration and state separate.

For a complete adapter contract, short SDK/process examples, and optional container execution, see [Agent integration](../agent-integration.md).
