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
- Use defining language such as "means", "called", "from", "made with", "term for", "name for", "known as", or "refers to" when locating the supporting relationship.
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


## Surname and family-name slot reduction

- If a question supplies a surname, dynastic name, or family identifier (for example after "this possible", "this", "the", or "a member of the"), treat that final name component as already supplied even when the matching context phrase is a full personal name such as `Given Surname`. Return only the missing given name or discriminator from the most directly defining context sentence; do not output the full two-word name unless the question asks for the complete name or the blank explicitly includes both components.
- Before finalizing a person-name candidate, check whether the final surname/dynastic word appears in the question wording. If it does, delete that component from the candidate even if the full name is a contiguous proper-noun phrase in the context. This supplied-name reduction takes precedence over the general rule to preserve full proper nouns and fixed phrases when keeping the extra word would repeat an already supplied qualifier rather than fill the actual missing slot.

## Implicit-slot answer-type rules

- If the question after "Question:" is a bare list of two or more named entities joined by "&", "and", or a comma with no explicit question word or blank, treat the list as an implied lookup for the shared attribute or classification supplied by the context. Do not return a descriptive relationship phrase such as sibling, parent, founder, maker, or a definition of the listed entities, and do not return either listed entity itself. Extract only the shared value from the nearest context sentence that ties the entities together, especially a location, organization, type, or class word that appears after "of", "from", or "in" and is common to the list.

- If the question is a declarative clue containing a demonstrative pronoun or possessive (for example, "The X from this ...", "This is ...", or "Its ...") and has no explicit blank, first identify what the pronoun stands for. When the sentence asks for the source, origin, or producer of something using phrasing such as "from this", "from it", or "made with this", return the exact source object or entity named in the context, not the product, measured quantity, material, output, or category being described. If the context says a device measures energy emitted by a named source, a source question must return that named source, not the energy or radiation type.

- Before finalizing an implicit-slot answer, restate the implied question and verify the candidate fills the inferred role: a shared-attribute list requires the shared value; a source/origin clue requires the source; a definition clue requires the term. Reject candidates that identify a relationship, property, material, output, or category unless that is the role the implied question actually requests. Preserve the exact source or attribute phrase from the context, including a leading article when it is part of that source noun phrase.

## Quoted-continuation and missing-word answers

- If the prompt contains a quoted phrase that is cut off immediately before the answer slot, locate that exact phrase in the supplied context and return the next word or phrase that completes the quotation exactly as written. Do not answer with the title, author, speaker, source, or other named entity merely because the prompt also says that a work or person "begins", "says", or "writes" the quoted line, unless the blank explicitly asks for that title or name.
- A trailing "this" or "this?" after a quoted phrase is often a slot indicator pointing to the omitted continuation, not a request to name the work or source. When the quoted text is visibly incomplete, complete the quotation from the context rather than extracting a document title or heading that appears nearby.
- Before finalizing an answer to a quotation-based prompt, identify the exact context passage that contains the quoted words, compare its continuation with the words already quoted in the prompt, and return only the missing continuation token or phrase. Do not return the entire quoted line, the document title, or the surrounding context sentence when only the omitted segment is requested.

## Failure-driven slot and variant selection

- For a prompt that is only a category or descriptor plus a bare name, title, or key phrase, treat that key as a lookup target, not as the answer. If the supplied context identifies the key as a tribute, cover, adaptation, translation, or variant of another entity, return the original or source entity to which the key points. Do not return the key's own explanatory label, such as a title that appends a category or class word to the key, when the question instead asks who or what the key is.

- When the context contains multiple proper names for the same entity in different languages or forms, select the name from the context span that most directly matches the question's descriptive class and language. Do not substitute an alternate-language synonym or heading-only form when a matching context sentence supplies the expected form, including any leading article.

- For a fill-in-the-blank slot introduced by "this/these/that/those" plus a class noun, remove the class noun already supplied by the question. If the context phrase filling that slot includes a determiner such as "the," preserve it as part of the answer. Do not include the repeated class noun itself, and do not omit a required article from the fixed phrase.

## Grammatical number and attributive-modifier corrections

- When the question uses a singular demonstrative such as "this fruit," "this type," or "this object," do not change the number of the answer to match that demonstrative. Return the exact noun form that the most directly defining context span uses, including any plural form.
- If the target noun appears both as a singular attributive modifier inside a proper name or title and as a plural or base common noun in a body sentence defining what the thing is, prefer the form used in the defining relation or count-noun context over the title modifier, unless the question explicitly asks for the title or proper name itself. The answer should be a noun phrase that can stand alone as the thing being asked about, not a modifier clipped from a larger proper name.
- Do not singularize a plural answer merely because the question uses a singular class word; likewise, do not pluralize a singular answer unless the source span itself uses that plural form.



## Near-verbatim and explicit clue-answer records

- If the supplied context contains explicit QA, flashcard, quiz, or Jeopardy-style records, including clue/answer pairs separated by colons, pipes, or line breaks, match the question against the clue/question side both verbatim and by paraphrase. Return the matching answer side exactly as written, preserving capitalization, spelling, and internal punctuation, but omit delimiters, labels, question wording, answer markers, and trailing status/score labels or annotations.
- Treat a direct clue-answer record or a near-verbatim context passage as primary evidence. Do not let overlapping phrases in unrelated snippets or a keyword-matching document title override that primary evidence. If the prompt is a near-verbatim clue from a Jeopardy-style or delimiter-separated context record, choose the answer text immediately paired with that clue; do not substitute a different named entity from neighboring snippets unless it satisfies every clue constraint.
- If the question wording appears almost word-for-word in a supplied context passage or clue, extract the shortest span from that passage or record that completes the question. If multiple records match, use the remaining constraints in the prompt to select the correct record.
- When a clue contains a quoted title, lyric, or exact phrase, locate the context record that repeats that phrase; if an answer appears in the same record, return that answer rather than the quoted phrase itself.

## Declarative, pronoun, and descriptive-role clues

- If the text after "Question:" is a declarative statement rather than an interrogative, treat it as a cloze item. Resolve possessive, demonstrative, or personal-pronoun slots such as "his", "him", "this", "that", "these", or "it" to the exact entity, work, or common-noun phrase in the supplied context that satisfies the whole statement. Return that exact referent as written; do not answer yes/no, do not repeat the predicate, and do not return only the pronoun or a broad category word when the context names a specific referent.
- For a declarative clue with a role or descriptor plus an action, creation, award, or event, use the context span satisfying both to choose the proper-noun subject, and do not return the role or descriptor itself unless the question explicitly makes it the requested answer.
- If a declarative clue repeats across multiple documents or snippets, prefer the repetition where the requested class or category appears directly adjacent to the answer candidate.
- For a bare quoted work title, optionally followed by a year or parenthetical, do not return the title itself. If the nearest defining body sentence names a principal creator through relations such as "directed by", "written by", "produced by", or "created by", return that named person or entity. Otherwise use the existing bare-term lookup behavior: return the defining country, location, type, classification, or meaning from a body sentence, not from a heading or title that merely repeats the key.

## Bare-list and comma-separated prompts

- If the text after "Question:" is only a comma-separated or otherwise listed set of names, nicknames, or terms with no explicit question word, do not repeat the listed items and do not settle for a broad category label. Treat the list as an implied lookup for the shared attribute given by the context: the work, show, organization, series, source, place, or title in which those items appear together. Return that shared target exactly as written.
- Prefer a context span that groups the listed items to that target over isolated mentions of individual items.

## Multi-attribute, numeric, and dated-fact disambiguation

- Before finalizing a candidate for a declarative or constrained clue, enumerate the separate constraints stated in the question, such as location, region, organization type, size, date, publisher, edition, creator, or event. A candidate is valid only when the context supports every constraint in the same sentence or directly contiguous clauses, not merely when one lexical item matches in a different entity's snippet.
- When a clue mixes a date or numeric value with other facts such as an event, award, cause, relation, or place, do not pick an entity merely because it shares a surface keyword. Match the exact or near-exact date/numeric value and verify the candidate satisfies every stated condition before finalizing.
- Treat quantity thresholds such as more than X, over X, less than X, at least X, or nearly X as inequalities, not exact values. A context figure satisfying the threshold supports that candidate even if the number differs.
- For creator/work or sibling-work clues, list all works or entities by the same creator that appear in the context. Choose the one whose context sentence contains the full set of event, date, edition, or change phrases from the question. A sibling work that shares only one phrase must not override that full-set match.
- Return the selected title or name exactly as written in that context, including its leading article or fixed phrase if present; do not reduce it to a distinctive fragment unless the question asks for that fragment.
