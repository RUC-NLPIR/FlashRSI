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
- Find the shortest span in that context that directly answers the question; prefer exact wording, capitalization, and spelling as it appears in the context.
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
