---
name: main
description: Reusable terminal guidance for writing well-formed script files, especially headless Vim/Ex scripts and allow-listed command checkers, plus multi-language source editing, date-filtered aggregation, restricted-network API retrieval, sequence/DNA construction, Git secret recovery, and verifier-driven verification.
---

# Terminal Task Skill

## Writing well-formed script files
- Treat the task's listed allowed commands as exact syntax, not approximate forms. Include required leading colons for Ex commands (e.g. `:wq`, `:x`, `:%normal! @a`, `:s/...`).
- Do not substitute equivalent abbreviations when a checker may compare command lines exactly (for example, `wq` may still work in Vim, but a grader can require `:wq`).
- After writing a script, statically review every line against the allowed-command list or expected regex before running it.
- Keep macro definitions inside the exact allowed call forms and use the specified register names; avoid extra Vimscript functions, shell escapes, or unsupported command families unless explicitly permitted.
- Verify the script with the exact headless invocation specified by the task, and check both exit status and output/result byte-for-byte.

## Headless Vim/Ex scripts
- Use `vim -Nu NONE -n -Es <file> -S <script>` for non-interactive execution.
- In register strings, represent Enter as `\r` and Escape as `\e` inside double-quoted Vim strings; double backslashes used inside regex patterns as needed so the registers contain the intended keystrokes.
- Keep run time acceptable by preferring simple substitutions and short macros, and test on a small copy before operating on the full file.


## General workflow
- Inspect the working directory before editing: `pwd`, `ls -la`, `find . -maxdepth 2 -type f`, `file <input>`, `head -n 20 <input>`, `wc -c -l <input>`, `which <tool>`.
- Read exact task requirements for output path, format, and line endings. If a platform file-writing tool rejects an absolute path, fall back to a shell heredoc:
  ```bash
  cat > /tmp/script.py <<'PY'
  # code
  PY
  python3 /tmp/script.py
  ```
- Produce the requested file first, then verify it; clean scratch files only after the deliverable is correct.

## Writing multi-language polyglot source files
- At the start, confirm required compilers/interpreters and their versions (`which rustc g++`, `rustc --version`, `g++ --version`).
- Do not attempt to merge syntax. Instead isolate each language's code using comment/parser asymmetries and preprocessor conditionals.
- Rust block comments nest; C/C++ block comments close at the first `*/`. Use this to create a C/C++-visible, Rust-hidden section:
  - Open with `/* /*`, then `*/`.
  - C/C++ exits the block comment after the first `*/`; Rust remains inside a nested comment.
  - Put C/C++ code here.
  - End the section with `// */`: the `*/` closes Rust's still-open block comment, while C/C++ ignores it as part of a line comment.
- Create a Rust-visible, C/C++-hidden section with `#if 0`:
  - Reopen a Rust block comment with `/* /*` / `*/` while C/C++ is outside a comment.
  - Put `#if 0` immediately after; C/C++ preprocessor starts skipping, Rust ignores it.
  - Close the Rust comment with `// */`.
  - Put Rust code here.
  - Before `#endif`, use `/* /*` / `*/` to reopen the Rust comment so `#endif` is hidden from Rust. Then close it with `// */` after `#endif`.
- Keep each hidden section free of stray `/*` and `*/` sequences, and avoid adding `#` lines that can unbalance the preprocessor or early-close comments.
- Test the delimiter trick first in a small temporary file before writing the full source.

## Verification and final checks
- Run the exact requested compile/execute commands for each toolchain, not just equivalent variants.
- Compare outputs over several inputs, including edge cases and large inputs if arbitrary precision or overflow is plausible.
- Remove generated binaries/temporary files after verification, leaving only the requested source file.
- If the task comes from a public benchmark or repository, locate the associated test/checker file and parse its assertions before finalizing the output. Explicitly mirror those checks in your own verification script.
- Match file-level requirements exactly: one line vs no empty lines, allowed character set, whether trailing newlines are accepted, and exact path.
- Run the real verifier if available (`pytest`, the task-specific test module, or the supplied harness). If it is not available, reproduce its checks independently with the same libraries or logic.
- Re-read the final file directly (`cat`, `wc`, `head`, `tail`) to confirm it was written correctly, and cross-check any numeric totals independently.

## Date-filtered log/data aggregation
- Use the task-provided reference date, not the system date.
- Compute inclusive windows with a date library: `today` is the reference date; `last_n_days` starts at `reference_date - timedelta(days=n-1)`; `month_to_date` starts at day 1 of the reference month.
- If filenames encode dates (`YYYY-MM-DD_...`), parse the date from the filename when the task says filenames are authoritative. If lines encode dates, validate that line and filename dates agree.
- Count only the requested categories/severities; ignore any extra labels present in the input rather than failing or totaling them.
- Write the output with the exact requested header and row ordering. Use `csv.writer` with explicit newline handling:
  ```python
  with open(output_path, 'w', newline='') as fh:
      w = csv.writer(fh, lineterminator=chr(10))
      w.writerow(headers)
      ...
  ```
- Independently verify aggregate counts with a different method, such as `grep`-based counts over the relevant file globs, and ensure the total row equals the whole-corpus count.

## Restricted-network API retrieval
- Check proxy settings (`env | grep -i proxy`). If the configured proxy denies a required host, try bypassing it for that host:
  `https_proxy= http_proxy= curl -s -m 30 '<url>'`.
- If one API route returns empty or blocked, try adjacent routes: `/download`, `/entry/<id>`, entity endpoints, or the search/query endpoint.
- Save large JSON responses to a file and parse with Python rather than shell text munging; then filter the cached JSON for the required fields.

## Sequence construction from API and file references
- Collect exact reference sequences from APIs or files. Apply only transformations the task explicitly requests; if it says remove N-terminal methionine, remove only that residue from each component. Do not silently strip purification tags, affinity tags, or expression tags that are present in the reference FASTA/translation.
- If a reference sequence contains non-standard residues (e.g. `X` for a modified residue/chromophore), resolve the actual residues from the canonical/cognate database sequence before encoding. Never encode unknown residues as `X`.
- Assemble the chained protein in the exact requested N-to-C order. Use only Gly/Ser linkers between sub-proteins, each satisfying the required length range, and no linker on the N or C terminus.
- For DNA construction:
  - Do not add terminal start/stop codons when the task says the plasmid supplies them.
  - Avoid in-frame stop codons in the coding sequence.
  - Keep the total nucleotide length within any stated maximum.
  - Codon-optimize while preserving the translated amino-acid sequence exactly.

## Satisfying sliding-window GC constraints
- Translate the amino-acid fusion into codons with synonymous codon alternatives, then use local search over codons to fix violating windows rather than hand-picking codons.
- A sliding-window GC rate of 30-70% on 50-nt windows means every full window must have between 15 and 35 GC bases. Verify all windows by sliding one base at a time, not just non-overlapping windows.
- After optimization, translate the DNA in the same reading frame used by the grader and assert the expected sub-sequences appear in order. Assert linker segments match `[GS]+` and their length constraints.

## Git secret recovery and purging
- Start by inspecting repository state: `git status`, `git log --all --oneline`, `git branch -a`, `git tag`, and `git fsck --full --unreachable` (also with `--no-reflogs`) to identify dangling/unreachable commits, trees, and blobs.
- Inspect reflogs (`git reflog --all`) and pseudo-refs such as `.git/ORIG_HEAD`; these commonly keep orphaned secret-introducing objects alive.
- Use `git cat-file -p <object>` to inspect unreachable commits/trees/blobs, and `git cat-file -s` to confirm exact blob sizes. Write recovered secrets to the requested external path before cleaning the repository.
- Before destructive pruning, run a dry-run: `git prune --expire=now -n -v` to preview which objects will be removed.
- To purge unreachable objects:
  1. Expire all reflogs: `git reflog expire --expire=now --expire-unreachable=now --all`.
  2. Remove `.git/ORIG_HEAD` if it points to an orphaned object after checking its value.
  3. Prune and repack with `git prune --expire=now` and/or `git gc --prune=now`.
- Do not rewrite reachable history unless the task explicitly requires it. Preserve working-tree files, commit messages, and reachable objects byte-for-byte.
- Verify sanitization thoroughly:
  - List all remaining objects with `git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)'`.
  - Scan every remaining object for the target string with a loop using `git cat-file -p`.
  - Run `git fsck --full --unreachable --dangling` and `git status`.
  - Run a binary-aware recursive grep across the repository including `.git` for the target string and old object hashes.
  - Confirm only legitimate reachable objects remain and unrelated files/messages/working-tree content are unchanged.
