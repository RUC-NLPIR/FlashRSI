Before answering each question, invoke the Skill tool with skill `flashrsi:hotpotqa` and follow that skill.

The final message must be only the requested answer: no labels, quotes, commentary, extra punctuation, or explanation.

In your thinking, draft and check the answer with this general procedure:
1. Resolve the question to the single supplied-context sentence that directly states the requested fact.
2. Draft the shortest verbatim span from that sentence that still fully answers the question. Copy the span character-for-character: same case, punctuation, spacing, and word order.
3. Trim only what the question itself makes redundant: leading articles (unless part of a title), a leading locative preposition, trailing parentheticals or glosses the question did not ask for, and words already given in the question. Do not split a proper name, title, place phrase, appositive, coordinate expression, or an adjective+noun class term (for example, keep `black comedy` or `family sedan` whole when that compound is the class).
4. Do not import a fuller or shorter name, title, or phrase form from a different context sentence or entry.
5. If the question asks for a statement, definition, record, or event, return the complete reporting sentence or clause verbatim, including its lead-in words and final punctuation.
6. If the question asks for a count, return only the numeral exactly as written, with no counted noun or unit unless the question asks for that unit as a standard measure.
7. If the question is yes/no, return only `yes` or `no`, lowercase.

Then verify before the final message:
1. Invoke the Skill tool with skill `flashrsi:answer-verifier`, passing the question and your draft in the tool `args`.
2. Apply the corrected answer returned by that skill, and emit only that answer.

Run this verification pass at most once per question. If a Skill tool is unavailable, apply the checks above yourself and emit only the corrected answer.
