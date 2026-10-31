# Add a benchmark

Add tasks and grading behind the benchmark interface. Choose the environment path according to what the tasks need; keep agent resources separate from task data and verifiers.

## Choose an integration path

| Path | Use it when | What to provide |
| --- | --- | --- |
| Harbor / environment runtime | Tasks need a container, verifier, repository, database, or simulator. | Native task package, environment setup, execution binding, and reward mapping. |
| Raw files / local runner | Tasks can be loaded from text, JSONL, documents, or a local simulator. | Task loader, source metadata, split policy, and deterministic grading where possible. |

SWE-bench Verified, AppWorld, and BFCL have native integrations of their own; Harbor is not required for every container task. Start from the closest existing adapter in [the benchmark tree](../../flashrsi/benchmarks).

## Implement tasks and grading

Subclass [`Benchmark`](../../flashrsi/core/benchmark.py). Its two required methods are:

```python
def load(self):
    # Return train/dev/test tuples of Task objects.
    ...

def grade(self, trajs):
    # Return trajectories with the primary metric attached.
    ...
```

Declare a stable `name`, a description, metadata, and `primary_metric`. `load()` must also retain its split mapping in `self._splits` so the `train`, `dev`, and `test` properties work. Each `Task` needs a unique `task_id`, a question, and any ground truth, environment reference, or source metadata needed by the adapter.

`Trajectory` is immutable. Grading returns updated records with finite numeric metrics, typically via `dataclasses.replace`. Define how errors and missing answers contribute to the primary score.

## Bind an environment when needed

Environment-backed tasks carry `Task.env`. The runner binds the environment executor to the Agent. The harness still uses its ordinary execution interface and returns a `Trajectory`; the benchmark owns task packages, state, and verification.

Use the [Harbor notes](../terminal-bench.md) and [harness / benchmark boundary](../benchmark-harness-boundary.md) as references. Archive collected artifacts before removing temporary task environments.

## Register and document it

Export the adapter from [`flashrsi/benchmarks/__init__.py`](../../flashrsi/benchmarks/__init__.py) and add its name to the runner's [`_BENCHMARKS` mapping](../../flashrsi/runner.py). Add an example YAML and a configuration-index entry with the source revision, metric, split counts/policy, dependencies, services, and supported track.

Verify loading and grading offline with small fixtures. For environment integrations, also verify the native execution and verifier path; distinguish those runs from tests that only check interface compatibility.
