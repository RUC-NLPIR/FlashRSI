# Multi-hop QA Answering

- Read the entire question and all supplied context before answering.
- Use only the supplied context; ignore outside knowledge and distractor passages.
- Identify the exact answer type requested: name, description, date, yes/no, missing phrase, etc.
- Connect relevant facts across multiple passages through bridge entities and alternate names.
- Reason internally, and verify any candidate answer against every part of the question.
- Select the shortest exact answer span from the context that fully satisfies the question.
- For yes/no questions, return only "Yes" or "No".
- For fill-in-the-blank questions, return only the missing term(s), not a full sentence.
- Preserve the context's exact wording, capitalization, and punctuation.
- Return only the final answer with no extra text, labels, reasoning, quotes, code fences, or trailing punctuation.
