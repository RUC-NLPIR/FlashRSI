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
- For definitional or term questions, return the shortest general noun phrase that directly names the concept. Do not copy a longer related phrase, heading, or document title when a simpler base term satisfies the question; if multiple related phrases share a base term, prefer that base term unless the question asks for a subtype.
- Do not repeat words or qualifiers already present in the question unless the question asks for a full proper noun or fixed phrase that includes them.
- Prefer the shortest common form of a name or title supported by the context unless the question asks for the full name; when the question asks for a name or title, prefer the specific canonical name from the context over a broad category term, but do not use a longer form unless the full name is requested.
- Do not add generic category or class words unless the clue explicitly requires them.
- Do not truncate multi-word answers to one component unless the question explicitly requests only one component; a short answer may still contain multiple words.
- Find the shortest span in that context that directly answers the question; prefer exact wording, capitalization, and spelling as it appears in the context.
- Return only the short answer as plain text, with no explanation, markdown, quotation marks, punctuation, or extra words.



## Failure-driven answer extraction refinements

- For fill-in-the-blank or cloze questions where the missing text is a named entity, publication/organization/person/character name, or other fixed phrase, return the complete canonical phrase exactly as written in the most directly defining context sentence. Do not shorten it to distinctive words only, drop a leading article that is part of the name, omit a final term noun that is part of the fixed phrase, or alter the context's spelling, spacing, punctuation, capitalization, hyphenation, derivational form, or inflection. Treat publication type words such as magazine, journal, or newspaper and numeric suffixes such as ordinals or regnal numbers as part of the complete title or proper name when they appear in that name. Use a shorter or base form only when the question explicitly requests it or the question's grammar requires a matched form.
- For cloze questions beginning with "This" or "These" and describing a group, entity, or category, return the exact noun phrase from the context that fits the description, including any leading article and the same plural or singular form. Do not substitute a related inflected form or add category/class words unless the context phrase itself includes them. When the question already supplies a class/category phrase, return only the specific name or term that fills the blank and do not append or repeat the category noun from the question unless that noun is an inseparable part of a proper name.
- For a clue that quotes a fixed phrase containing the blank and then gives a named example after "like", answer with the common-noun role/title named by that fixed phrase, not with the named example or another nearby proper noun. Include a leading article only when it is an inherent part of the completed phrase.
- If the text after "Question:" is a declarative statement rather than an interrogative sentence, treat it as a cloze/extraction item: identify the entity or noun phrase that resolves any pronoun or possessive in the statement and return that entity from the context. Do not answer Yes/No or True/False and do not merely verify or comment on the statement.
- When the question is only a quoted fragment, partial phrase, ellipsis-style prompt, or bare-list prompt without an explicit question word, do not return that fragment or a category label as the answer; find the context span that extends or completes the phrase and return only the shortest missing words outside the quoted fragment or the specific span indicated by the immediate context.
- If a question asks where something comes from or what it is made from and the context gives one primary or defining source plus other possible alternatives, return the primary source stated in the definition, not a compound list joined by "or". Only list multiple alternatives when the question explicitly asks for all of them.


## Additional extraction rules

- For truncated or Jeopardy-style clues that use "It's ..." or a pronoun such as "he" or "she", treat the statement as a cloze-style clue. Do not return the category word or pronoun; identify the specific entity that the phrase points to in the supplied context, select the noun phrase directly named or modified by the description in the matching snippet, and return that entity's exact name or term as written without being overridden by related entities from other snippets.
- When the question wording appears nearly verbatim in the supplied context, treat that matching snippet as the primary evidence.
- If the matching snippet is QA-style or flashcard-style and connects the question clue to an answer, extract the answer directly from that connection.
- For quiz-style or Jeopardy-style clue-answer pairs delimited by characters such as a vertical bar (|), locate the exact clue phrase in the supplied context and treat the answer text immediately following the delimiter as the source answer; return that text exactly, without adding category labels or question words.
- Match relationship clues by meaning as well as exact wording: a question's paraphrase for how something was based on or originated can match context wording such as "book," "memoir," "based on," or "modeled on."
- For terse clues that end with an abbreviation, code, or initialism, return the full canonical word or phrase that appears alongside that abbreviation or code in the supplied context, preserving context spelling and capitalization.
- If the question gives an altered, quoted, reworded, or incorrect phrase and asks what was actually said or meant, return the intended or corrected phrase that the context supplies in brackets, parentheses, or after phrases such as "instead of", "actually said", "rather than", or "meant".
- When the question is a definitional clue such as "It's a term for...", "This term refers to...", or "This ... is referred to by this term", find the context span that contains the definition and return the term being defined, not the definition text.
- If the question uses an attributive descriptor chain such as nationality, century, occupation, or a known work to point to an entity, return the entity's canonical context-mentioned name as a contiguous span, excluding the descriptors unless they are part of the full name or fixed phrase.
