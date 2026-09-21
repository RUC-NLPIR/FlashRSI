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
- Use defining or equivalence language such as "means", "called", "from", "made with", "formerly", "also known as", "once called", or "refers to" when locating the supporting relationship.
- For definitional or term questions, return the shortest general noun phrase that directly names the concept, not the proper-name title of a specific occurrence, event, person, or work that instantiates the concept. If the defining context introduces the term with an indefinite article (for example, `a/an X`) and the question slot expects a count-noun phrase, include that article exactly as written; otherwise do not add one. Do not copy a longer related phrase, heading, document title, or specific proper-name instance when a simpler base term satisfies the question. If multiple related phrases share a base term, prefer that base term unless the question asks for a subtype or explicitly requests the proper-name title.
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



## Constraint-first selection with phrase-overlap distractors

- When a question identifies an entity through a pronoun/possessive plus one or more role, office, rank, affiliation, or location constraints (for example "leader", "member", "senator from", "located in", or an official title) and also includes a quoted or paraphrased phrase, first collect every entity associated with the quoted phrase or its near variants. Each candidate must satisfy all role/status/location constraints in the supplied context, not merely appear near the matching words. A candidate that shares a phrase but fails an explicit role, status, or location condition is a distractor. Do not let a lexical overlap with one snippet override stronger role/constraint evidence from the same or a more directly defining snippet.
- Do not accept a candidate solely because a context sentence quotes the same expression as the question. Verify that the sentence also ties the candidate to the required position, rank, affiliation, or location. Surface phrase repetition is weak evidence when the role or location clue contradicts it.

## Person-name canonical form over terse answer records

- For person-name slots, treat a terse flashcard, QA, or delimiter-separated answer line that supplies only a surname, nickname, or abbreviated form as a pointer to the entity, not as a license to shorten the answer. Prefer the common full personal name used in the directly matching clue/answer or surrounding prose, usually `Given Surname` or `Honorific Given Surname` only when the honorific is part of that matching common form. Use a longer `Given Middle Surname` or official formal form only when the question explicitly asks for a full/formal/official name, or when the context provides no shorter common full-name form. Do not add a middle name solely because a more formal sentence includes it.
- Do not return a surname-only form when the question asks for a person identified by a descriptive or status clue such as nationality, occupation, role, achievement, or title. Use the common full personal name from the most directly defining context sentence, including any honorific or title only when it is part of that directly matching common form. If the matching sentence writes the person as `Given Surname` or `Given Initial Surname`, return that same short common form; prefer the longer `Honorific Given Surname`, `Given Middle Surname`, or official/legal form only when the question explicitly asks for the full/official name or when that same sentence uses the longer form. For anaphoric or demonstrative status clues such as `this president`, `this leader`, or `this man` that are anchored to an event, date, quote, or action, use the short common name from the directly matching prose rather than a middle-name or official variant found in another headline or document. A separate terse record or longer formal title is a pointer to the entity, not a license to expand the answer beyond the form used in the matching clue sentence. Prefer the shortest full name that satisfies the clue.
- Before finalizing a person-name candidate, compare it with the question's slot. If the question does not already supply the given name or honorific, a surname-only candidate is incomplete. Restore the complete name from the most directly defining context sentence or paragraph; a flashcard answer should identify the entity but must not override the full canonical prose form.

## Bare-title answer slot reduction

- If the prompt after `Question:` is only a person title plus name (for example `President X`, `Prime Minister Y`), treat the title as already supplied and do not return it. Find the nearest defining context sentence that gives the office relation and return only the missing complement of that relation, such as the country or jurisdiction after `of`, not the full trailing phrase `president of ... from ... to ...` or any other predicative span. A title+name key is an implied lookup for the attribute attached to that title, and the result must be just that attribute value as a contiguous span from the context.

## Plural proper-noun and place-name slot reduction

- When a fill-in-the-blank slot uses a plural demonstrative such as "these" with a geographic category noun (for example "these mountains", "these islands", or "these lakes"), return the canonical plural proper-noun or nominal range name exactly as used in the defining context sentence, including any leading article that is part of the name. Do not apply the remove-supplied-class-noun reduction down to a bare singular or adjectival modifier unless that bare form is itself the standard noun phrase satisfying the slot.
- If the context contains both a long form like "X Mountains" and a shorter established plural name such as "the Xs", choose the form that grammatically fits the plural slot and preserves the proper-noun/plural reading. Never clip a proper-noun modifier to the singular adjective form when the blank expects a plural named region or range.
- Before applying slot reduction, restate the slot with "these" and check the candidate as a complete noun phrase: a proper range/region name should be a head noun, not a premodifier. If the remaining term would be interpreted as an adjective or cannot stand alone as the named region, restore the plural noun form or the context's explicit shorter proper name.

## Inflection and exact-form matching for demonstrative/cloze answers

- When a demonstrative or cloze question such as `this/these ...` can be answered by a term that appears in both singular and plural forms in the supplied context, do not default to the shorter or first-seen variant. Locate the context sentence that most directly expresses the clue relation or action, note the grammatical form the surrounding object or verb phrase requires, and return that exact singular or plural form as written there. A form seen in a similar but less direct snippet must not override the form of the direct relation, even when that direct form is plural or longer and the prompt uses `this` as a generic slot.



## Success-based clue-resolution patterns

### Explicit quiz, flashcard, and QA-record extraction

- If the supplied context contains Jeopardy-style, flashcard, or QA-style records, including delimiter-separated pairs such as `clue | answer` or `clue | answer. right: ...`, match the question against the clue side both verbatim and by paraphrase, and return the answer-side text exactly as written, including any leading article such as "a". For person-name slots where the answer side is only a surname, nickname, or abbreviated form, treat it as an entity pointer and restore the full canonical name under Person-name canonical form over terse answer records. Omit delimiters, labels, trailing status annotations, and question wording.
- Treat a near-verbatim matching clue-answer record as primary evidence only after verifying that its answer satisfies all explicit role, status, location, office, date, or other constraints in the question; if it fails one, treat it as a distractor and continue searching. Do not let a different named entity from a nearby snippet or an unrelated document title override the answer paired with the exact clue.
- If the answer side is a proper name or fixed phrase, preserve its exact capitalization and spelling rather than normalizing it.

### Declarative, pronoun, and demonstrative clues

- If the text after `Question:` is a declarative statement or clause using a pronoun such as *he*, *she*, *it*, or *they*, or a demonstrative such as *this*, *these*, *that*, or *those*, without an explicit question word or blank, treat it as a cloze/identification item. Resolve the pronoun or demonstrative to the most directly matching named entity, work, object, sport, place, or person in the supplied context, and return that entity's canonical name or title exactly as written. Do not answer yes/no, do not return a generic category term unless the clue explicitly asks for that category, and do not stop at a surname when the context supplies the full canonical name.
- When the question uses appositive nicknames or role titles for the same subject (for example "X the Y" and "X the Z" with a shared base name), return the shared base name rather than one of the descriptive title phrases unless the question explicitly asks for a title.
- For clues like "this phenomenon," "this device," or "this type of Y," use the most directly defining context span. If the context contains both a longer proper name/title and a shorter common term, return the shortest span that directly fills the demonstrative slot and matches the singular/plural form required by the direct relation, omitting classifier words already supplied by the question unless they are part of a proper name or fixed phrase.

### Option-list, constraint, and disambiguation clues

- For option-list prompts that explicitly enumerate candidates before a descriptive predicate (for example, "Of X, Y, or Z, it's ..."), treat the listed names as the candidate set, locate the context evidence for the descriptive predicate, and return the matching candidate exactly as written in the prompt. Do not substitute a different entity from another snippet and do not add a category/class word to the candidate.
- Match numeric or measurement clues by approximate equivalence, including rounded distances, fractions, different units, and numeral-versus-spelled-word variants. Once the matching value is found, return the entity, place, or event associated with it in the same context span.
- If the prompt gives a role or status shared by multiple named candidates, collect all candidates associated with that role/status and require the remaining modifiers, such as date, country, action, office, or event, to select one. Return the exact canonical name of the candidate whose context support satisfies all modifiers.
- When the statement supplies multiple factual constraints such as dates, year ranges, numeric or statistical values, events, roles, or affiliations, treat each as required. Prefer the context span that satisfies all of them simultaneously over one that shares only a keyword or a single value.
- For a clue that identifies a whole through one of its parts, equipment, characteristics, or named members, return the whole named entity or title from the most directly binding context sentence. Do not return the part, the described object, the attribute value, or another entity that merely shares a keyword.
- When the question supplies a list of named members, characters, components, or associated items and asks for the containing work, organization, series, or grouping, return that work or group title exactly as written, not the list itself or a broad class label.
- For a clue that names a work, product, or artifact and asks for its creator, author, source, or maker through relational phrasing such as "this creator of X," "by this author," or "from this," return that person or source, not the work, the award, or another related creation.
- If the question is a terse noun phrase made of descriptors such as origin/nationality, era, occupation, or known work rather than a full interrogative or blank sentence, treat each descriptor as a constraint and return the named person, place, or work from the supplied context that satisfies all of them, exactly as the context names it. Prefer the snippet that places the origin/nationality and descriptors directly with the named entity.
- When the prompt gives a local, regional, or foreign name and asks what it is, locate the context sentence that equates the supplied name with a general or canonical name through phrasing such as "locally referred to as," "called," or "known as," and return that canonical/common-name span exactly as written.

### Cloze-set completion and renamed-entity resolution

- For fill-in-the-blank or Jeopardy-style clues that name one or more members of a fixed group and ask for a missing member, locate the context passage that lists the complete group and return the missing member exactly as written. Do not return the category label or an already supplied member.
- When a clue includes a former, alternate, or current name equation (for example "formerly X", "once called X", "also known as X", or "now X"), use the context sentence that equates the entity with that name to identify the requested slot. Return the current/canonical name when the blank asks for the current entity; return the former/alternate name only when the blank explicitly asks for it.
- For a "This [category]" clue, first check whether the context's matching phrase is a proper name that includes the category word as an inseparable part. If so, return the full proper name exactly as written. If the category word is only a class noun already supplied by the clue, return the missing discriminator and omit the class word.

### Relational-slot and attribute extraction

- For declarative clues that contain a possessive demonstrative such as "this state's," "this country's," "this nation's," or "this region's," treat the possessor as the missing slot. Find the body sentence that connects the named institution, feature, division, record, or office to its owner and return the exact owner/location phrase from that sentence.
- When a question supplies a named entity and asks for a single relational attribute such as `this state`, `this country`, `this city`, `this region`, `this instrument`, or `this holiday`, return only that attribute value from the directly defining context sentence, not the named entity itself and not a longer phrase that repeats words already supplied elsewhere in the question.
- For phrases ending in `in this ...`, `on this ...`, or `of this ...`, locate the context sentence that contains both the described entity and the requested relation, then return only the missing object or attribute value.
- When the question asks for a nickname, alias, "better known moniker," popular name, or common appellation, return only the nickname/alias span from the matching context sentence. Do not expand it into the full formal name, do not append the legal name, and do not treat the formal title as the answer when the prompt explicitly asks for the nickname.

### Variant and form selection from defining sentences

- If the context offers multiple spellings, aliases, abbreviations, or old/current names for the same thing, prefer the form used in the sentence that supplies the question's definitional, etymological, or renaming clue such as `means`, `comes from`, `formerly`, or `dropped ... from its name` over the same term in headings or unrelated snippets.
- When the question refers to a former component or older name as part of an identifying history, return the final or current name as written in the context, not the dropped component or the earlier name by itself.

### Final slot verification and exact-span selection

- Before finalizing, insert the candidate into the question. If the question already supplies a classifier such as "device," "phenomenon," "musical," or a location/class word, omit that word from the candidate unless it is part of a proper name or fixed phrase. Keep exact source spelling, capitalization, and punctuation.
- For "one of these" clozes, retain the source's article and noun phrase, including the article, when the completed slot is a count noun phrase such as "a bouncer"; do not reduce it to the bare noun unless the question already supplies the article.
- Prefer a candidate that appears as a contiguous span in the context and that exactly matches the source's singular/plural and article form over a longer but more familiar phrase.


## Fixed-proper-name blanks and nickname-slot exactness

- When a fill-in-the-blank or cloze prompt shows only part of a fixed proper noun or joined title (for example `___ & Name`, `___ Company`, or `X and ___`), return the complete fixed phrase exactly as written in the context, including the part already visible outside the blank. The slot-refilling rule that removes already supplied words does not apply to words that are part of the fixed proper noun being requested; do not return only the missing component unless the question explicitly asks for that component alone.
- When the question asks what an entity was nicknamed or called, using phrasing such as `nicknamed this`, `known as`, or `called this`, return only the nickname/alias span. If the entity type or class word is already supplied or implied by the question, omit that type word from the answer even if the context writes the nickname as `Nickname Type`.
- These final-form checks take precedence over shortest-span extraction when returning the shorter candidate would fragment a fixed proper name or drop a required article.
