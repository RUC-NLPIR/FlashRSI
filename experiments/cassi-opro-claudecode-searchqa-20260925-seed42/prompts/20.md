# Coverage-First Answer Extraction

For every task with supplied context:

1. Read the entire prompt and all context before answering.
2. Use only the supplied context; do not use outside knowledge.
3. Identify what kind of answer the prompt asks for: person, entity, place, date, phrase, category, etc. Resolve pronouns, possessives, and clue-style phrasing to the exact referent.
4. Treat every modifier, descriptor, date, number, role, location, title, quoted word, and listed item as a hard constraint.
5. Candidate selection:
   - Find all context spans that might be relevant.
   - Remove any candidate that conflicts with or fails any hard constraint.
   - Do not choose a candidate merely because it shares a word or phrase with the prompt; it must satisfy all of the prompt's facts.
6. From the remaining candidates, choose the shortest exact contiguous span that satisfies the full prompt. Never merge separate spans or add alternative names.
7. For people and entities, output the shortest complete name form actually present in the context, without titles, honorifics, party/state labels, roles, or parentheticals unless the prompt explicitly asks for them. If only a surname is present, do not invent a first name.
8. Output only the chosen span. Preserve exact spelling, capitalization, punctuation, and word order.
9. Do not add quotes, labels, citations, document names, explanations, formatting, or extra whitespace.
10. Follow any explicit output-format instruction exactly; otherwise return the bare answer.
11. If no single context span satisfies every hard constraint, output only: Unanswerable
