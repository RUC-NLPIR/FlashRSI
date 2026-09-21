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



## Constraint-first selection with phrase-overlap distractors

- When a question identifies an entity through a pronoun/possessive plus one or more role, office, rank, affiliation, or location constraints (for example "leader", "member", "senator from", "located in", or an official title) and also includes a quoted or paraphrased phrase, first collect every entity associated with the quoted phrase or its near variants. Each candidate must satisfy all role/status/location constraints in the supplied context, not merely appear near the matching words. A candidate that shares a phrase but fails an explicit role, status, or location condition is a distractor. Do not let a lexical overlap with one snippet override stronger role/constraint evidence from the same or a more directly defining snippet.
- Do not accept a candidate solely because a context sentence quotes the same expression as the question. Verify that the sentence also ties the candidate to the required position, rank, affiliation, or location. Surface phrase repetition is weak evidence when the role or location clue contradicts it.

## Person-name canonical form over terse answer records

- For person-name slots, treat a terse flashcard, QA, or delimiter-separated answer line that supplies only a surname, nickname, or abbreviated form as a pointer to the entity, not as a license to shorten the answer. Locate the full canonical personal name in the surrounding prose or titles, such as `Honorific Given Surname`, `Given Surname`, or `Given Middle Surname`, that satisfies the question's identifying clues, and return that full canonical form exactly as written.
- Do not return a surname-only form when the question asks for a person identified by a descriptive or status clue such as nationality, occupation, role, achievement, or title. Use the full name, including any leading honorific or title when it is part of the canonical context form, even if a terse clue-answer record supplies only the surname or an informal short form.
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


## Container phrases with plural demonstratives

- If the text after `Question:` is a declarative or Jeopardy-style clue of the form `the [container] of these/those [plural category]` or `these/those [plural category] formed/joined/became a [container]`, treat the absent referent after `these`/`those` as the implied blank. The requested answer is the plural noun phrase naming the members or constituents, not the proper name of the container organization, unless the question explicitly asks for that organization's name.
- Locate the context sentence that says the members formed, joined, belonged to, or were represented by the container, and take the plural common-noun term for those members from that sentence. Omit origin, nationality, or other modifiers already supplied in the question unless they are part of a fixed plural proper name; otherwise return the bare plural member term exactly as written.
- Before finalizing, insert the candidate into the reconstructed slot `the [container] of these ___`. If the candidate names the container itself and makes the slot ill-formed, discard it and choose the plural noun that can directly follow `these`/`those`. This check overrides general proper-name or title preference when the question's grammar requires a plural membership term.


## Person-name granularity and fixed-title headword retention

- Match answer granularity to the question type rather than applying a global shortest/longest rule. Recurrent failure modes are over-expanding a person name when the question already supplies part of the name or uses a work-attribution clue, and over-reducing a fixed proper-name title by stripping a terminal headword.
- Before finalizing a person-name answer, treat any personal-name component already present in the question as supplied and outside the blank. If the clue says the target is `named [GivenName]`, `first name [GivenName]`, `known as [Nickname]`, or otherwise includes the person's first/given name or nickname, return only the missing surname or remaining name component exactly as written in the matching context span. Do not return the full `Given Surname` or `Given Middle Surname` canonical form when it repeats the supplied component.
- For Jeopardy-style or work-attribution clues identifying a person through a named work, painting, composition, style, or artifact (for example `Artist whose most famous painting ... is ...`, `composer of ...`, or `author of ...`), return the person-name form used in the exact matching attribution, quiz/flashcard answer, or defining context sentence. If that evidence writes the surname only or a short common name, return that exact form rather than expanding it to a full `Given Surname` or `Given Middle Surname` found elsewhere. This overrides the earlier Person-name canonical form over terse answer records rule for these clue types. The earlier full-name rule still applies to formal/official-name requests and non-work descriptive/status clues where the question does not already supply a name component.
- If the question includes only a surname and the context supplies a fuller form, follow the existing full-canonical-name rules; the supplied-component reduction applies only to components already stated in the question.
- For named scales, indexes, measures, instruments, and analogous fixed titles, the terminal headword (`Scale`, `Index`, `Measure`, etc.) is part of the fixed proper-name title, not a removable class word. In a demonstrative clue such as `this standard wind scale` or `the numbers on this standard wind scale`, return the full canonical titled form from the context, including `Scale` and preserving source capitalization. Do not apply the `X Y` + `this Y` slot-refilling reduction to strip `Scale` just because a descriptive phrase includes the genus word. This overrides the earlier Slot-refilling answer reduction and supplied-class rules for fixed proper-name titles.
- Before finalizing, classify the target as (a) a person identified by a work/quiz clue, (b) a named title/scale/index, or (c) a bare discriminator blank. Apply shortest/longest and supplied-word reduction rules only within the correct class; do not mix forms across classes.
- Verify the candidate completes the slot without adding a supplied given name, middle name, nickname, title, honorific, or removable headword, and preserve the exact spelling and capitalization of the remaining component from the source.


## Source/derivative and indefinite-function selection overrides

- If the text after `Question:` is only a bare entity name, title, or term with no explicit question word or blank, treat it as a lookup key. First search the supplied context for an explicit derivation, adaptation, source, or equivalence relation attached to the key, such as `adaptation of`, `adapted from`, `re-telling of`, `based on`, `inspired by`, `version of`, `remake of`, or `from`; if such a relation directly points from the key to another named entity, work, or source, return that source/original entity exactly as written, not the key itself and not a genre/type classification of the key. If no such source/derivation relation exists, then find the nearest context sentence that defines, locates, classifies, or otherwise describes the key, and return the specific span from that sentence (such as its country, location, type, or meaning) that directly answers the implied lookup. Do not allow a document title or heading that merely repeats the key to override a body sentence supplying its defining attribute or source relation. This overrides the earlier Bare-term and implied-slot questions rule where that rule would otherwise return a type/classification for a source/derivative key.
- If the text after `Question:` is a short phrase combining a broad class word (genre, medium, role, product category, etc.) with a named entity, and the supplied context identifies that named entity as a tribute, cover, adaptation, remake, local variant, or derivative of another named entity, return the source/original entity exactly as written. The descriptor words such as `tribute`, `cover`, `band`, `version`, `adaptation`, or the broad class word supplied in the prompt are not the answer; they modify or classify the already named derivative. Find the defining context relation (for example `Derivative is a tribute/cover/version of Original`, `Derivative | Original Tribute/Cover`, or `Derivative (Original-Cover version)`) and return only `Original`.
- If the context offers both a full descriptor phrase (`Original Tribute/Cover`) and the source alone, prefer the source-alone span. Do not let a title or heading that repeats the full descriptor override a body line isolating the source.
- If the text after `Question:` is an indefinite noun phrase that describes a product or class by function or use, first locate a general/common-noun term that the context explicitly defines as performing that same function in the relevant setting, such as a sentence of the form `Term(s) do/curtail/reduce Y` or `Term is applied to Z`. Return that general term exactly as written rather than any specific named ingredient, remedy, brand, or member that merely shares the function or use words.
- When a prompt uses an indefinite article or bare class phrasing, it is asking for the class or product itself; do not substitute a concrete example. Surface lexical overlap with the descriptor words (such as a property or body location) on a named example is weaker than a direct definitional sentence for the general term. Prefer the term predicted by the definitional relation and verify it corresponds to the function and usage in the clue.


## Attribution, colon/dash, and reverse-possessive clue parsing

- If the text after `Question:` joins a role/status/category phrase to a named object, work, ship, publication, or place with a colon, semicolon, or em dash, treat each side as a separate constraint on the same target entity. Locate the context sentence that connects one entity to both constraints and return that entity's canonical name or completing span exactly as written. Do not return either side alone, a heading, or a broad class label.
- If a declarative clue uses a pronoun or possessive such as *him*, *her*, *this author's*, *this creator's*, *this writer's*, or *this artist's* and attributes a quoted title, nickname, label, or list of works to that person or source, resolve the pronoun/possessive to the named person, not to the quoted title, nickname, publication, or genre. Return the full canonical personal name from the context sentence that directly supplies the attribution or work list.
- If a declarative clue reports that a source or publication has called/nicknamed/termed *him* or *her* with a phrase, resolve the pronoun to the named person. The quoted phrase is evidence for locating that person, not the answer itself; unless the prompt explicitly asks for the nickname or label, do not return the quoted phrase or the source name.
- For fixed-recipe or definitional slots of the form `with this [flavor/color/material/type] [class]`, locate the definition sentence that lists the fixed components. Return only the modifier of the missing class exactly as written, without returning the already named component or repeating the supplied class noun.
