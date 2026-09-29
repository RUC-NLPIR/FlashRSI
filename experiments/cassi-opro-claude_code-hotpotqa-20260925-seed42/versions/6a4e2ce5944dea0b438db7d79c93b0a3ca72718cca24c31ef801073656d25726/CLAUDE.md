# Multi-hop QA Answering

- Read the entire question and all supplied context passages before answering.
- Use only the supplied context; ignore outside knowledge and distractor passages.
- Identify the requested answer type and format: entity, title, date, number, yes/no, or missing phrase.
- Treat every descriptor and constraint in the question as a required filter, and connect facts across passages via shared entities, aliases, dates, and references.
- For each candidate, build a complete context-supported evidence chain and verify it satisfies all parts of the question; reject partial or unsupported matches.
- Select the shortest exact span from the context that fully answers, preserving original wording, capitalization, pluralization, and punctuation.
- For numeric answers return only the number; for yes/no return only “Yes” or “No”; for fill-in-the-blank return only the missing term(s).
- Do not append units, categories, or words already stated in the question unless they are part of the exact answer.
- Before finalizing, re-read the question to confirm the answer and format; remove explanations, reasoning, labels, quotes, code fences, extra words, and trailing punctuation.
- Return only the final answer.
