# Question Answering Skill

## Learned Question-Answering Rules

- Return only the requested short answer. When the prompt asks for a short answer or says to return only the answer, output exactly the minimal entity or phrase that directly answers the question, with no explanation, no full sentences, and no extra punctuation unless the answer itself requires it. Do not add extra descriptive terms, full formal names, full titles, articles, parentheses, dates, release years, or quotation marks unless the question explicitly asks for those forms.
- For title/name questions, output the canonical title/name only. If a source shows a parenthetical release year after a title, omit the parenthetical year from the answer unless the year is part of the official title or explicitly requested.
- If the prompt is a declarative clue or fact-like sentence ending with a date or detail, identify the person or entity being described from the context and answer with that person or entity; do not echo the year, number, or detail from the clue.
- Exception for fill-in-the-blank questions: when a blank is part of a multi-word term (e.g., "___ & X"), return the complete canonical term exactly as it appears in the context, including ampersands, capitalization, and suffixes, unless the question explicitly asks for only the missing portion.
- Identify the question focus and constraints: what entity, attribute, or relationship is requested (e.g., names, dates, aliases, slogans, units, superlatives, time, location).
- Identify key clue terms, quoted phrases, or pronouns such as "this X" or "it" in the question.
- Scan all supplied context snippets (e.g., [DOC]/[TLE]/[PAR]), especially document titles and first sentences, for exact or near-exact matches and paraphrases of those clues.
- Treat the question as a missing-entity clue; prefer snippets that use the same wording as the question or state the requested relationship directly (e.g., formerly known as, slogan, equal to). When a context passage mirrors the question phrasing, the answer is usually the adjacent completing text.
- Extract the exact short noun phrase or proper noun from the matching context; preserve the form used in the context, prefer the shortest standard term, and match the specificity level of the question. Avoid over-inferring beyond the context; a semantically correct but longer answer may still miss exact-match grading.
- Ignore snippets that mention only part of the question but do not support the answer.
- When no choices are given, rely on the context passage with the strongest lexical overlap with the question.

