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
- Prefer the specific canonical name or title from the context over a broad category term. For person names, if both a formal given name + surname and a nickname/diminutive + surname appear, return the formal given name + surname, not the nickname, unless the question itself quotes or explicitly asks for that nickname. If both a first-name + surname and a longer version with a middle name or initial appear, return the first-name + surname unless the question asks for the full name or the context's clearest naming phrase includes the middle component. Use a surname-only form only when the context or question clearly supports that shorter form as the direct answer.
- Do not add generic category or class words unless the clue explicitly requires them.
- Do not truncate multi-word answers to one component unless the question explicitly requests only one component; a short answer may still contain multiple words.
- Find the shortest span in that context that directly answers the question; prefer exact wording, capitalization, and spelling as it appears in the context.
- Return only the short answer as plain text, with no explanation, markdown, quotation marks, punctuation, or extra words.



## Cloze, category, and answer-type rules

- For fill-in-the-blank and cloze cues that use "this/these" with a category or description, determine whether the blank asks for a common-noun category, type, class, or plural member category (for example "this ... show", "one of these ...", "these ..."). Return the matching common noun or shortest common designation that directly replaces the demonstrative and fits the wording of the question, with the article and singular/plural form the completed phrase requires. Do not return a named organization, person, title, facility, full official title, or other specific proper-noun instance (individual, place, or product) that merely contains or is associated with that category, even if it appears in a heading or title, unless the blank itself is part of that proper noun or the question explicitly asks for that name/title. In "an/the [organization/group/alliance] of these [members]" clues, return the plural common-noun member type when the blank corresponds to the category after "these", not the proper name of the resulting organization.
- If the same entity appears in both a long official title and a shorter/common name, prefer the shorter common name for this-style title prompts; use the full official title only when the question explicitly asks for it.
- For declarative type-of/cloze sentences such as "X is an ingredient/part/feature of this type of Y," treat the missing type/name as the blank. Do not answer with a material, adjective, or broad description even if it is adjacent to the clue. Search the whole context for a direct collocation of the clue with a named subtype or title; a specific sentence that places the clue in or with a named subtype is stronger than a general sentence that attaches a related adjective to the category. When a specific named subtype is supported, return that exact named subtype as written, and prefer it over shorter or more common words from another snippet.
- Before finalizing a candidate, place it back into the question's syntax. If the question already supplies a modifier, class noun, article, or category, omit that from the answer unless it is part of a larger proper noun or fixed phrase. Extract the answer as a contiguous span from a body sentence that provides the defining relationship; a document title or heading that shares keywords with the question does not by itself make the title the answer.
- For bare fragments, truncated phrases, or joined words, do not invent a missing question word or action such as who, what, when, or where. Compare the fragment with the exact context phrase, identify the missing segment that restores the original construction, and return only that segment; include a leading article or preposition only when it is part of the missing span as written in the context.
- Verify every candidate appears as a contiguous span in the supplied context. Do not generate or guess an answer from outside world knowledge. If the context contains the same clue but no explicit answer span, select only the closest context-supported term and do not substitute a similar familiar object.


## Additional clue-resolution rules

- If the question wording appears almost verbatim in a supplied context passage, treat that passage as primary evidence and extract the shortest span from it that directly answers the question. If the context contains an explicit QA, flashcard, or Jeopardy-style clue/answer pairing, including Q:/A: exchanges, direct answer fields, or delimiter-separated records such as clue|answer, match the question against the clue side and return the answer-side text exactly as written, preserving its full phrasing and without category labels, question wording, or extra punctuation.
- For declarative or fragment clues with a leading possessive such as "Her", "His", "Their", or "Its", treat the statement as a cloze item: resolve the pronoun to the most directly matching named entity or fixed phrase in the supplied context and return that exact name or title, not the pronoun, not a broad category/class descriptor unless the clue explicitly asks for that category, and not a related entity from another snippet. Do not answer yes/no or merely restate the clue.
- When a question supplies multiple attributes (such as a year, creator, source work, role, or setting) to identify a work or entity, prefer the context span that satisfies all of the attributes and return the canonical title or name as written, excluding the descriptors unless they are part of the full title or proper name.
- If a quoted title or phrase appears with an English translation, definition, or meaning nearby (often in parentheses or after phrases such as "translates to" or "means"), and the question asks what it translates to or means, return that supplied translation/meaning exactly as written, without quotation marks or extra words.
- Extend defining-language cues to include relationship phrasing such as "used with," "used for," "is paired with," "is made with/from," and "comes from." For such clues, return the explicitly paired item or substance from the most directly related context span.
- When a question asks for a common name with a stated meaning, select the canonical name shown directly beside that meaning in the supplied context, not a broader category label or a gendered variant from a different snippet unless the question explicitly specifies gender.
- When a clue includes an exact or approximate numeric fact such as a distance, percentage, fraction, measurement, or date, match by approximate equivalence as well as exact wording, then extract the entity, event, or term associated with that value in the matching context span.
- If a clue explicitly asks for a category/type and identifies it through an example such as "like X in this Y," return the category/class indicated by the demonstrative phrase, not the named example.
- If the question is only a bare term or title with no explicit question word, do not return the term itself; return the explicit classification, location, type, or definition that the supplied context provides for that term.
- For a terse factual clue that supplies an attribute such as a score, measurement, date, or point value, locate the sentence that equates that attribute with a key term even when no explicit "called" or "means" connective is present, and return that term exactly.
