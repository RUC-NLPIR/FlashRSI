# Multi-hop Short-Answer QA

- Read the entire question and all provided context before answering.
- Identify the question’s target entity and the specific relation being requested.
- Trace the chain of supporting facts across multiple passages, including bridge entities and alternate names.
- Require a complete, context-supported chain for any candidate answer, and verify it satisfies all parts of the question.
- Ignore irrelevant or distractor passages.
- Choose the shortest exact answer that fully satisfies the question.
- Return only the final short answer in the requested format, using the context’s wording and no extra text, punctuation, or explanation.
