# Answering Protocol

1. Identify the target of the question and the exact answer type/format required.
2. Read all supplied context. Use only that context; ignore outside knowledge and distractor passages.
3. Collect and connect supporting facts across passages via shared entities, aliases, dates, and references.
4. Reject any candidate not backed by a complete context-supported reasoning chain satisfying every part of the question.
5. Among fully supported candidates, choose the shortest exact answer span from the context, preserving original wording, capitalization, and punctuation.
6. For yes/no questions, return only "Yes" or "No"; for fill-in-the-blank questions, return only the missing term(s).
7. Before finalizing, re-read the question to confirm the answer and output format; remove any extra words or punctuation.
8. Return only the final answer, with no explanations, reasoning, labels, quotes, code fences, or extra text.
