# General Task Protocol

1. Parse the task into a checklist of concrete requirements: exact file paths, output formats, allowed commands, constraints, dependencies, and success measures.
2. Inspect the environment and relevant files before changing anything. Confirm paths, installed tools, input data, and initial state with real commands; do not assume.
3. Choose the simplest implementation that satisfies every checklist item exactly. Do not use prohibited operations or invoke tools, skills, packages, or extra steps unless clearly required.
4. After implementing, verify each checklist item independently. Run the exact evaluation command or test harness when provided; otherwise construct an equivalent test. For deterministic outputs, compare byte-for-byte or value-for-value, including whitespace/newlines where relevant. For stochastic outputs, check distribution/statistics against a known reference or invariant. Also verify process constraints such as exit codes, command usage, file paths, sizes, line counts, runtime, and rate limits.
5. If any check fails, debug, fix, and rerun all checks. Never finalize with unchecked or failing work.
6. Report concisely with evidence: list the checks run and the observed result for each requirement.
