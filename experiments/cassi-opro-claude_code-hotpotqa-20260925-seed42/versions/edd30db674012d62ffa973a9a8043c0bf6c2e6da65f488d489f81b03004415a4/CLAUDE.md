# Multi-hop Short-Answer QA

- Read the entire question and all supplied context first.
- Use only the supplied context; do not use outside knowledge.
- Determine the exact target, answer type, and required format.
- Resolve coreferences, aliases, and bridge entities across passages; ignore distractor passages and irrelevant similar-name entities.
- Disambiguate entities by matching every qualifier in the question (dates, numbers, descriptions) against the context.
- For a candidate to be accepted, it must be supported by a complete context chain and satisfy all parts of the question.
- Select the shortest exact answer span from the context that fully answers the question, preserving original wording, capitalization, and punctuation.
- For yes/no questions, return only “Yes” or “No”; for numeric questions, return only the numeric value; for fill-in-the-blank, return only the missing term(s).
- Before finalizing, re-read the question to confirm the answer and format exactly.
- Return only the final answer: no explanations, reasoning, labels, quotes, code fences, extra words, or trailing punctuation.
