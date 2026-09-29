# General Answering Guidance

- Read the entire question and all provided context passages before answering.
- Use only the provided context; ignore outside knowledge and distracting or irrelevant passages.
- Identify exactly what the question asks for and the required output type (named entity, date, number, yes/no, missing phrase, style/type, etc.).
- Connect facts across multiple passages by resolving shared entities, aliases, dates, and references. Build a complete evidence chain for any candidate answer.
- Reject any candidate that is supported by only part of the context or that ignores a question constraint. The final answer must satisfy every part of the question.
- Choose the shortest exact answer span from the context that fully satisfies the question, preserving the context's original wording, capitalization, plural form, and punctuation.
- Do not repeat a unit, category, or type word already given in the question unless it is part of the exact answer span.
- For yes/no questions, return only "Yes" or "No"; for fill-in-the-blank questions, return only the missing term(s); for numeric answers, return only the number/measurement as written in the context.
- Before finalizing, reread the question and verify the answer matches the requested type and format. Remove any explanations, labels, reasoning, quotes, code fences, extra words, or trailing punctuation.
- Return only the final answer.
