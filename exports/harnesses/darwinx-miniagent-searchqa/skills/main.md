# Question Answering Skill

Apply these rules to every question that supplies context.

## Answer format
- Return only the short answer. No explanation, no citations, no restatement of the question.
- Omit leading phrases such as "The answer is", "Answer:", "It is", "This is", or "The correct answer is".
- Do not add a closing period unless the answer itself requires it (for example, an abbreviation that contains periods).
- Keep the answer as short as possible while still fully answering the question. Most answers are 1-5 words, but return the complete name or phrase when the full phrase is the answer.

## Finding the answer in the context
- Treat every `[DOC] ... [PAR] ...` block as evidence. The answer is usually an exact name, number, or date present in one or more blocks.
- For "who", "what", "which", or "name" questions, return the name or noun phrase the context directly associates with the question.
- Many questions are phrased as a statement that describes the answer (for example, statements ending in "this ..." or "... is this ..."). Identify the described entity and return only that entity.
- For number and date questions, return just the number or date exactly as written in the context.
- If several candidates appear, choose the one the context explicitly links to the question. Do not list alternatives and do not combine names.
- Preserve exact names, numbers, and dates from the context. Do not translate or modernize them.

## When the evidence is partial
- If the context describes the requested entity even indirectly, give the most likely short answer from that evidence rather than refusing.
- Never answer with "not enough information" or a question mark when the context points to a specific entity.

## Final check
- Re-read the question, then confirm your answer is the entity or value asked for and not a related-but-different entity.
- If your drafted answer is a sentence, reduce it to the short phrase that directly answers the question.
