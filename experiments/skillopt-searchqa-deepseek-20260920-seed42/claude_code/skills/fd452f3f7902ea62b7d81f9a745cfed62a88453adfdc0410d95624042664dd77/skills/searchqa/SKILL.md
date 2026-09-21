---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

## Short-answer extraction rules

- Use only the supplied context; do not introduce outside knowledge.
- Read the question carefully and identify the short answer type requested (e.g., name, title, term, or quality).
- For simple fill-in-the-blank, truncated, or cloze-style questions, identify the missing entity from the surrounding context and output only that entity, unless the blank is part of a larger proper noun or fixed phrase; in that case return the full proper noun or fixed phrase exactly as written.
- Match the question's key clues, including demonstrative or descriptive phrases such as "this", "these", "it", "who", or "which", to the most directly related context snippet.
- Use defining language such as "means", "called", "from", or "made with" when locating the supporting relationship.
- For definitional or term questions, return the shortest general noun phrase that directly names the concept in the exact form the question slot requires. If the question supplies or expects a leading article (for example, "an X"), include that article; otherwise do not add one. Match singular/plural, article, and common-vs-proper specificity to the defining context phrase, not to a more frequent plural class form elsewhere. Do not copy a longer related phrase, heading, document title, named subtype, regional population, full official title, or longer proper-noun instance when a simpler base term satisfies the question; if multiple related phrases share a base term, prefer that base term unless the question asks for a subtype.
- Do not repeat words or qualifiers already present in the question unless the question asks for a full proper noun or fixed phrase that includes them.
- Prefer the shortest common form of a name or title supported by the context unless the question asks for the full name; when the question asks for a name or title, prefer the specific canonical name from the context over a broad category term, but do not use a longer form unless the full name is requested.
- Do not add generic category or class words unless the clue explicitly requires them.
- Do not truncate multi-word answers to one component unless the question explicitly requests only one component; a short answer may still contain multiple words.
- Find the shortest span in that context that directly answers the question; prefer exact wording, capitalization, and spelling as it appears in the context.
- Return only the short answer as plain text, with no explanation, markdown, quotation marks, punctuation, or extra words.



## Cloze and fragment answer-form rules

- Before finalizing any short answer, insert the candidate back into the blank or elliptical position. The span should fit the slot exactly: include an article or preposition only when the slot requires it, do not duplicate determiners already present in the question, and keep the context's number, capitalization, and common-vs-proper choice.
- For declarative or fragment clues with a possessive or demonstrative ("Its", "His", "Their", "These"), resolve the pronoun or demonstrative to the object, entity, or concept being described and return that noun exactly as the context names it. Do not return the property, definition, or predicate phrase.
- When the question asks for a category, species, type, class, or group shared by two or more named examples, choose the plural common noun required by the question's grammatical frame and return the exact plural form from the context. Do not output a singular base noun for a multi-instance clue.
- For bare comma-separated terms, list fragments, or truncated prompts without an explicit interrogative, do not restate the fragment and do not return the broad category or group label. Locate the matching context list or phrase, identify the missing or directly targeted token, and return only that token exactly as it appears.
- Prefer the candidate that most directly completes the question over a longer context span that merely shares the concept.


## Additional extraction patterns

- When the prompt supplies multiple identifying attributes such as dates, statistics, roles, titles, or organizations, prefer the context span that satisfies all or the most specific subset of those attributes.
- If a prompt or large fragment appears nearly verbatim in a supplied context passage, treat that passage as the primary evidence. When the context contains explicit clue-answer, QA, flashcard, or Jeopardy-style records (including delimiter-separated pairs such as `cue | answer` or separate answer fields), match the clue side and return the answer-side text exactly as written, without question wording, category labels, or delimiters.
- For quoted-continuation, split-phrase, missing-title or list, crossword-style, or letter-constrained prompts, locate the exact surrounding phrase in the context and satisfy all supplied constraints; return only the missing segment exactly as written, not the entire context line or the words already supplied by the prompt.
- If a demonstrative such as `this` or `that` refers to a common-noun type in a modifier phrase such as `the X type of this`, return the common-noun category to which the demonstrative refers, not the full descriptive headline or title unless the prompt explicitly asks for that full title or proper name.
