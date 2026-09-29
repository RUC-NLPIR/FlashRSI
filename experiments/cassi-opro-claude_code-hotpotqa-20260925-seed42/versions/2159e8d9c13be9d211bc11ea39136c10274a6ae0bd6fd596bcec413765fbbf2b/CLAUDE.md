# Answering Guidance

- Read the whole question and all supplied context before answering.
- Use only the supplied context; do not use outside knowledge.
- Identify the question’s target and the exact answer type/format required (e.g., entity name, date, number, yes/no, missing phrase).
- Connect facts across passages through shared entities, aliases, dates, and references; ignore distractor passages.
- For each candidate answer, require a complete context-supported evidence chain and verify that it satisfies every part of the question.
- Choose the shortest exact span from the context that directly answers the question, preserving original wording, capitalization, plurality, and punctuation.
- If a literal value is not stated but the question refers to a named entity in the context, return that entity name; do not output meta-answers such as “not stated.”
- For yes/no questions, return only “Yes” or “No”; for numeric or date questions, return only the value as written; for fill-in-the-blank questions, return only the missing term(s).
- Do not add units, categories, or question words unless they are part of the exact answer span.
- Before finalizing, re-read the question to confirm the answer matches the target and format, then remove explanations, reasoning, labels, quotes, code fences, extra words, and trailing punctuation.
- Return only the final answer.
