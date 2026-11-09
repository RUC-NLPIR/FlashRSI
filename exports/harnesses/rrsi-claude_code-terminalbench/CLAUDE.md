# FlashRSI Operating Protocol

These rules apply to every task. They are reusable execution safeguards, not task-specific constants.

## 1. Deliver required artifacts early and stop when the contract is met
- Before working, identify every required output path, format, and success check from the task statement and any included tests/checker files.
- As soon as you have a best-effort candidate that satisfies the known requirements, write it to the exact required path immediately, even if you plan to refine it later.
- If the task asks for a single value or file, write the current best value to the required path in the same step as computing it (for example `printf '%s' "$value" > /app/answer.txt`); do not keep investigating while the required path remains empty.
- Do not leave a known-correct or plausible artifact unwritten while continuing to investigate alternatives. Deliver first, then verify.
- Immediately verify the artifact exists at the required path and run the supplied checker/tests when available.
- Continue iterating only after the required artifact exists and is verified, and only if the deadline/turn budget still has room. If the deadline or turn limit is close, stop and deliver the current best artifact.

## 2. Verify against the task's stated contract and supplied checkers
- Treat the task statement and any included tests/checker files as the authoritative contract for required file paths, function signatures, argument order, format tokens, output shape, and measurement method.
- Do not attempt to inspect, invoke, or reverse-engineer the hidden grading harness. Work only from task-provided materials and the public interface those materials specify.
- Test with the same call pattern shown in the task or included tests, not only your own self-tests. Match the public interface and argument order exactly.
- For scripts with well-formedness rules, check the exact required exit/termination token or line, not only byte-for-byte output content.
- For performance tasks, benchmark candidate and reference on the same unmodified data with the same warm-up and alternating-run timing methodology; do not validate on a modified copy or an easier setup.

## 3. Resilient environment, toolchain, and build/install setup
- Run a short preflight at the start: OS/architecture, available tools (`command -v cc gcc curl python3 git`), package sources, and actual input files before choosing an approach.
- Put a strict timeout on every install, clone, and download (`timeout 120 ...` or similar) and use bounded retries with explicit exit conditions. If a source stalls or hangs, do not poll it until the deadline; switch promptly to a reachable mirror, alternate source, or prebuilt/vendored toolchain.
- While a slow install/download runs, continue other useful work and check the result once; do not repeatedly poll the same slow command.
- For transient git/network failures, retry with a shallow or partial fetch (`--depth=1`, `--filter=blob:none`) and then continue; do not let one source block the whole task.
- Ensure required compilers and build tools are present before relying on them (`cc`/`gcc`, cross compilers, `curl`, etc.). Install missing build dependencies early, and if an install is slow, look for an already-packaged or prebuilt alternative instead of waiting out the deadline.
- For Python extension/source packages: prefer an actual install path such as `pip install --no-build-isolation --no-deps .` (or the project's equivalent build backend) instead of only `python setup.py build_ext --inplace`, so the package is importable from the grading environment. Patch removed `distutils` imports to their `setuptools` equivalents before building. Verify by importing the package and running the project's own tests.

## 4. Scope destructive cleanup narrowly and verify preservation
- When sanitizing or recovering, edit only the contaminated working-tree files. Preserve history, baseline refs, tags, and reachable objects unless the task explicitly requires destroying them.
- Do not run history-rewriting commands such as `git filter-branch`, do not delete backup refs, and do not run `git gc --prune=now` merely to remove secrets from working files.
- If a destructive cleanup is blocked or appears unnecessary, re-evaluate necessity instead of forcing it; leaving a harmless unreachable object is better than deleting baseline state.
- Independently verify both the required removal and the required preservation before finishing, using the same checks the task-provided checker/tests will use.
