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
- Prefer the shortest common form of a name or title supported by the context only when the question is informal or explicitly requests the short/common name. When a descriptive clue identifies an entity by formal status, official recognition, membership, or defining appositive, return the complete canonical/official name exactly as written in the matching context sentence rather than shortening it to a base name. Keep leading feature-word prefixes such as Lake, Mount, Fort, or Saint as part of a fixed proper-noun name; they are not removable category words. In list-style clues that name sibling members in abbreviated form, restore the target member's full canonical context form rather than mimicking the abbreviated list. When the question asks for a name or title, prefer the specific canonical name from the context over a broad category term.
- Do not add generic category or class words unless the clue explicitly requires them.
- Do not truncate multi-word answers to one component unless the question explicitly requests only one component; a short answer may still contain multiple words.
- Find the shortest answer span that directly fills the question slot after applying the reduction rules below. Prefer exact wording, capitalization, and spelling from the context, but do not retain a longer contiguous phrase when the slot requires a shorter base noun, nickname, or modifier and the extra words are not part of an explicitly requested proper name or fixed phrase.
- Return only the short answer as plain text, with no explanation, markdown, quotation marks, punctuation, or extra words.



## Multi-constraint disambiguation for shared markers

- When a question contains a short marker such as a letter, code, symbol, abbreviation, or initial that can identify more than one named entity in the supplied context, do not answer with the first expansion found. Collect every candidate associated with that marker, then check each remaining word or modifier in the question (for example a specific object, version, denomination, type, date range, region, or activity) and return only the candidate whose context support satisfies all of them.
- Before finalizing a candidate, restate the question's concrete constraints and verify that the candidate is associated with each one in the context. Discard a candidate that matches the marker but fails another stated constraint, even if that candidate appears in a definitional or parenthetical expansion such as `X  Name (description)`.
- Prefer the candidate taken from a context span that places the marker directly together with the same specific object, product, class, or activity named in the question. A separate snippet that merely expands the marker to another entity with a generic category phrase should not override that full-object evidence.


## Slot-refilling answer reduction

- Before finalizing any answer, place the candidate back into the question's blank or paraphrased slot. Remove any word that is already supplied elsewhere in the question, including the class/category noun it modifies (for example, type, source, vitamin, power, energy, plant, or organization). Return only the missing discriminator, not the full noun phrase from the context. If the context offers a phrase such as "X Y" and the question already says "this Y," answer with "X" rather than "X Y." Do not delete words that are part of a full proper noun or fixed phrase the question explicitly asks for; remove only supplied category/location/class words outside that name.
- When the missing text is a modifier or classifier of a supplied class noun, prefer the bare modifier/base term from the defining context sentence. Do not append a synonymous head noun such as "power," "energy," "force," or "plant" after that modifier unless the question makes that head noun the blank and does not already supply it as the class word.
- For proper nouns with a base name plus a campus, branch, or location qualifier that is not part of a requested fixed proper noun, when the question already places the location outside the blank through phrasing such as "at X," "in X," "near X," or "X, not Y," return the base proper noun and omit the qualifier. If the context's defining sentence uses a leading article with that base, retain that article in the answer.
- After extracting a candidate, delete from it any word or qualifier the question already provides or semantically supplies, unless it is part of a full proper noun or fixed phrase the question asks for. If the remaining span is still a complete answer, prefer the reduced span; a candidate that repeats a supplied category, location, or class word is over-extracted.


## Bare-term and implied-slot questions

- If the prompt after "Question:" is only a bare entity name, title, or term with no explicit question word or blank, do not return that same entity/term. Treat it as a lookup key: find the nearest context sentence that defines, locates, classifies, or otherwise describes it, and return the specific span from that sentence (such as its country, location, type, or meaning) that directly answers the implied lookup. Do not allow a document title or heading that merely repeats the key to override a body sentence supplying its defining attribute.
- Before finalizing a candidate, insert it into the blank or implied slot and verify the complete proper noun/fixed phrase appears as a contiguous span in the source. Do not truncate multi-word proper names to one distinctive component merely because the shortest-span rule prefers brevity.


## Failure-driven answer-form corrections

- For a bare comma-separated or list-style prompt that names two or more entities and has no explicit question word, treat it as an implied lookup for the shared attribute that ties those entities together in the context. Return only the shared attribute value itself, such as the place, country, organization, source, or type named after a relational phrase like "of," "from," or "in," and do not prepend a role or status word to it.
- If the supplied context uses both a formal given name + surname and a nickname or diminutive + surname for the same person, return the formal given name + surname unless the question itself uses or explicitly asks for the nickname. Do not prefer a shorter nickname merely because document titles or headings use it.
- When the matching context phrase defines a style or type as a descriptor plus a concrete object/head noun, return the descriptor term alone unless the head noun is the actual missing slot or an inseparable part of the fixed term. Do not append structural nouns such as entry, home, house, style, or type to a descriptor when the question already supplies or describes the broader object.


## Quiz-style clues and role-title disambiguation

- For terse clue patterns such as `role/label: "Title"` or `A [role] with "Title"`, treat the role/label as the requested answer type and prefer the context span that directly classifies an entity under that role or that forms an explicit clue-answer/Q&A record with the same clue. A parenthetical title after another entity's description is weaker evidence when it does not satisfy the primary role clue.
- When the supplied context contains quiz-style or Jeopardy-style records, match the question against the clue side as near-verbatim or paraphrase, then return the corresponding answer side exactly as written. Do not extract an associated named entity from an unrelated body sentence if a direct clue-answer or role-defining occurrence exists.
- If the quoted title/fragment in the question appears in multiple snippets, choose the snippet where it is connected to the requested role/class or answer target, not merely a title listed next to a different named entity.


## Slot reduction for demonstrative and nickname clues

- When the question uses a demonstrative slot such as "one of these", "this type", "these", "it", or asks for a nickname/alias after the category or official name has already been supplied, do not carry over extra modifiers or a repeated category noun from the matching context phrase. Return only the base common noun or distinctive nickname/modifier needed to complete the slot. For personal-name clues, return a nickname/diminutive only when the question explicitly asks for it; otherwise follow the formal-name preference in Failure-driven answer-form corrections. For a context phrase "X Y" where the question already implies "Y" through an antecedent or nearby class word, answer with "X" unless "X Y" is a proper name or fixed phrase explicitly requested.
- Before finalizing, remove any adjective, article, or category word already supplied by the question wording or by a pronoun antecedent. For example, if a pronoun or nearby class noun already supplies the type (such as party, chair, or object), omit that class noun from the answer. For common-noun or modifier slots, if a shorter form is supported and completes the slot, prefer that shorter form even when the longer form is a contiguous substring of the context; do not apply this to proper names or fixed phrases unless the question explicitly asks for a component.
- For "one of these" or "like one of these" questions, if the context supports a compound term and its simpler base noun, choose the shortest common noun phrase that identifies the object rather than a more specific compound or technical variant, unless the question explicitly requires that subtype.
