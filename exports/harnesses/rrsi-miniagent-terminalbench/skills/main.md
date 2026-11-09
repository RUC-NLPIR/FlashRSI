# Task solving

Read the question and any supplied context carefully. Identify the requested
entity or value, check the supporting evidence, and answer concisely. Follow any
explicit output-format requirements. Describe tool use only when it actually
occurred, and distinguish supplied evidence from assumptions.

## Completion protocol

Before any long setup or analysis, extract the deliverable contract from the
question: the exact output path(s), file name(s), function/interface signature,
required commands or format, and expected data representation. Write a minimal
valid deliverable to the required path as early as possible, then refine it.
Never leave the only passing candidate in a scratch or temporary location.

When validating, use the exact grader-equivalent command or check when one is
available, not a self-selected or normalized variant. Match the verifier's exact
expectations: do not strip, reorder, or "improve" requested sequences, argument
orders, file formats, or required syntactic components.

Before finishing, verify every required artifact exists at its exact path and
re-check the contract. If anything is missing or mismatched, fix it before the
final answer. Bound setup and analysis time; if prerequisites are consuming too
much of the run, switch to a simpler path that still produces the required
deliverable.
