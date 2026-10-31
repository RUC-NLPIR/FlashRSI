# Add an algorithm

Implement your search policy in `Algorithm.evolve`. Use the shared resource and evaluation operations, while keeping proposal, feedback, selection, and memory decisions in your method.

## Declare its scope

Subclass [`Algorithm`](../../flashrsi/core/algorithm.py) and declare `evolve_scope` and `observation_scope` using the Target's component names. Use `{"*"}` only when the method is intended to operate on every declared component.

The constructor receives the method configuration and `target`, `worker`, and `benchmark`. It applies the scope and loads task splits. Check method-specific requirements in `_check`.

## Implement the search loop

```python
async def evolve(self):
    # Observe training evidence and the current resource version.
    # Ask the Worker for a proposal or a candidate file edit.
    # Commit permitted changes and evaluate the candidate.
    # Apply the method's own admission and selection policy.
    # Return the selected Snapshot.
    ...
```

Use the existing [algorithm implementations](../../flashrsi/algorithms) as executable examples of checkout, rollout, grading, and records. The runner assembles dependencies and evaluates the selected Snapshot on held-out test tasks; it should not acquire your method's search policy.

Keep test feedback out of proposal generation and selection. If a method uses dev feedback, state exactly how and when it influences candidate adoption.

## Configure and register it

Add the class to [`flashrsi/algorithms/__init__.py`](../../flashrsi/algorithms/__init__.py) and the runner's [`_ALGORITHMS` mapping](../../flashrsi/runner.py). Add a YAML example that chooses an appropriate Worker and exposes the method's budget and search parameters.

Document the edited resources, feedback, adoption rule, termination condition, and differences from the upstream method. Validate key state transitions with deterministic offline cases, such as rejected edits or ties in candidate scores.

Start with [OPRO](../../flashrsi/algorithms/opro/__init__.py) for scored instruction search, or [ModularRSI](../modular-rsi.md) for a broader module-based workflow.
