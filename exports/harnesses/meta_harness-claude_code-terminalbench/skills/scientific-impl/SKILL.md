---
name: scientific-impl
description: Use for tasks that implement a numerical, statistical, or sampling algorithm with formal tests against known truth — "implement a sampler / estimator / integrator", "compare results to known distributions", "validate inputs and reject invalid cases". Covers R/Python scientific code with modular functions and PASS/FAIL test output.
---

# Scientific / numerical implementation protocol

Grader-facing requirements (nearly all numerical tasks check these mechanically,
not by reading your explanation):

1. **Pin the exact public interface first.** Read the spec for the exact
   function names and signatures (a primary function plus a test entrypoint),
   and the exact output artifact paths (e.g. `/app/ars.R`,
   `/app/normal_samples.txt`). Name the primary and test functions EXACTLY as
   requested (`ars`, `test`) — a grader calls them by name.

2. **Install the language if missing** (e.g.
   `DEBIAN_FRONTEND=noninteractive apt-get install -y r-base` for R), then
   write modular code: one function per discrete step (validate, build envelope,
   sample, check domination), consistent naming, and clear errors for invalid
   inputs (negative counts, out-of-domain values) and unsupported cases
   (non-log-concave densities).

3. **Accept the specified input shape.** If the spec says the density comes as a
   vectorized function (`dnorm`, `dexp`, …), call it with a vector and vectorize
   your wrapper — do not require a scalar-only function.

4. **Check log-concavity (or the equivalent invariant) DURING sampling**, not
   just once up front — the spec usually demands the rejection step itself catch
   a violated assumption and raise a clear error.

5. **Test against known truth, not just "it runs".** For stochastic output use
   distributional checks (Kolmogorov–Smirnov against the built-in `r*`/`dnorm`
   truth, mean/SD vs theory), never exact equality. Make the test entrypoint
   print one line per test in the required format — `NAME: PASS` or
   `NAME: FAIL` — and include the mean and standard-deviation statistics on the
   same line (e.g. `normal_mean: PASS (mean=-0.004, sd=0.993)`), because graders
   often grep for that exact shape.

6. **Produce the required artifacts at the exact paths** (sample files with one
   value per line), and make the test entrypoint runnable both as a script
   (`Rscript file.R` / `python file.py`) and when sourced/imported, using a
   `main` guard so importing does not auto-run the suite.

7. **Verify determinism where required** (set a seed), confirm the files are
   written with `ls`/`wc -l`, then stop — do not re-run a passing suite.
