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
- If the prompt after "Question:" is only a bare comma-separated list of named entities (for example country, person, or product names) with no explicit question word, blank, or category noun, do not return the list itself or the broad group that contains them. Treat the listed names as a lookup set: locate the most direct context sentence assigning a common attribute (such as location, country, affiliation, class, or owner) to all of them, and return that shared attribute exactly as written. Do not return the relationship between the listed entities unless the prompt explicitly requests that relationship.
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


## Plural demonstrative category-member extraction

- When a declarative or Jeopardy-style clue says that a series, issue, publication, exhibition, collection, or other container is `on`/`of`/features a `these`/`those` slot and then names two or more concrete examples, the named examples are supplied clue material, not the answer. Resolve the plural demonstrative as the implicit blank: find the context sentence that classifies or lists those examples as members of a plural common-noun category, and return that plural common noun exactly as written.
- Do not return the container itself, the medium, the issue/series title, or the otherwise prominent collection when the blank asks for the class of the named examples. A context phrase of the form `commemorative issue featuring five [category]` is evidence that the container is not the missing slot; the slot before the named examples must be the member category they instantiate.
- Before finalizing, restate the clue as `a [container] on/of these ___ from ... features X and Y` and insert the candidate. If the candidate names the container rather than a plural noun that can directly follow `these`, reject it and choose the plural member term from the directly classifying sentence.

## Direct clue-span form over distant canonical expansions

- For demonstrative or informal identification clues such as `This man ...`, `... star in this ...`, `this show/book/team ...`, `this behind-the-scenes look ...`, and similar pronoun/possessive prompts that do not explicitly ask for a full/formal/official name, prefer the exact name or title form from the context sentence that directly satisfies the clue predicate over a longer or more formal form found in a distant heading, lead paragraph, or encyclopedic sentence.
- For person clues, if the directly matching sentence or nearby title uses a nickname, short given-name form, or abbreviated personal-name form, return that exact form rather than expanding to a longer formal given name or adding a middle name/title from another snippet. For work/title clues, if the directly matching sentence uses a short established title rather than the full official title, return that short title exactly as written.
- Only expand to a full canonical/official name, honorific, or complete title when the prompt explicitly asks for the full/formal/official form or when the direct matching span itself uses that longer form. This overrides the earlier canonical-name and full-title preference in informal demonstrative/pro-form clue types.

## Simple base term and article for physical-definition slots

- If a definitional slot describes a physical shape, object, symbol, or graphic element with wording such as `Term for the circle that encloses ...`, `the ... that ...`, or `a ... used to ...`, prefer the shortest direct common-noun definition from a glossary or defining sentence over a longer modified technical term. A direct definition of the form `X - circular shape used to contain speech` supports returning the base term `X`, not the compound `speech X`, `word X`, or `dialogue X`, unless the question explicitly asks for that subtype.
- When the completed slot is a singular count-noun phrase and the source defines it with an indefinite article, retain the article in the answer even if the question does not explicitly supply it. Do not treat the article as removable unless the slot already includes it.

## Emphatic-narrowing over broad-source lists for source/material clues

- When a clue asks what an entity comes from, is made from, or consists of using a broad container phrase such as `these animals`, `this material`, or `this plant`, do not stop at the first coordinate list in a general source sentence. Continue to the context sentence that uses a narrowing or emphasis cue about the source (`particularly`, `especially`, `mainly`, `chiefly`, `primarily`, or `in particular`) and return the focused span after that cue exactly as written.
- If a general sentence lists several candidate sources but a defining or equivalence sentence singles one out with one of those cues, prefer the singled-out span over the coordinated list. The intensifier is context evidence for selection; do not include it or the broad category-word in the answer unless the question explicitly asks for a full phrase.
- This overrides any tendency to take the first, longest, or most complete coordinate span from a general list when the question does not explicitly ask for all members.

## Bare titled-work lookups prefer principal creator credit over medium/type

- If the text after `Question:` is only a work title followed by a year in parentheses (for example `Title (Year)`), do not answer with a generic medium or type word such as `film`, `book`, `song`, or `painting`. Read the title+year as a lookup key for the principal credited creator or director named in the context.
- Locate the most directly defining context sentence or title line that ties the work to its creator or director through phrases such as `directed by`, `produced by`, `written by`, `painted by`, `by`, or a credit in the same title, and return that person's canonical name exactly as written.
- The year in parentheses is part of the key and does not make the medium/type the requested attribute. This overrides the earlier `Bare-term and implied-slot questions` rule for bare titled works only when the context supplies a specific principal creator/director credit; other bare terms should still use the nearest defining attribute.

## Quoted catchphrase, slogan, and title-fragment association lookup

- If the text after `Question:` is only a quoted phrase, slogan, catchphrase, lyric snippet, tagline, or title fragment with no explicit question word or blank, do not first classify or describe the phrase itself. First search the supplied context for a named work, series, franchise, brand, organization, or person to which the phrase is directly attached.
- If the phrase appears as the component after a colon or dash in a compound title (for example `Main Title: Phrase`, `Main Title - Phrase`, or an installment subtitle), return the main title exactly as written from that context, excluding the quoted subtitle and any add-on words already supplied by the question. This form of association is stronger than a body sentence that says the phrase is a type, medium, year, or description.
- If the context defines the item containing the phrase as `based on`, `adapted from`, `associated with`, `a spinoff of`, or `from` a named original/source series or work, return that original/source named entity exactly as written, not the derived item and not the genre/type/medium of the derived item.
- Do not return a broad category, class, genre, date, or descriptive phrase when a directly associated named main title or source work is present. Use description only when the supplied context contains no explicit title association or source relation.

## Singular demonstrative class slots with plural source forms

- When the question uses a singular demonstrative class noun such as `this fruit`, `this crop`, `this animal`, `this food`, `this berry`, or `this product`, do not treat the singular `this` as requiring a singular answer. Identify the source span that directly defines or identifies the referent and return the exact count form used there.
- If that direct source span uses a plural count noun for the referent (for example a quantity or list such as `million berries`), return that plural form exactly as written. A plural source form is not over-extraction and must not be singularized merely because the question says `this`.
- Apply supplied-class-word reduction only to remove the class word already present in the question. If the question supplies `fruit`, remove only `fruit` from a multiword source phrase; do not switch the remaining noun between singular and plural.
- Before finalizing, restate the clue with its demonstrative class slot and verify that the chosen form comes from the most directly defining source sentence rather than the surface number of the demonstrative.


## Additional success-based clue-resolution patterns

### Dictionary-gloss and definitional headword extraction

- If the prompt is a dictionary-style gloss such as `It's in dictionaries as ...`, `defined as ...`, `a/the term for ...`, or `meaning ...`, treat the definition words as clue material rather than as the answer. Locate the supplied context sentence that defines a headword with those words and return that headword/base term exactly as written, not the explanatory definition, an inflected example, or a document title.
- For common-noun or onomatopoeic senses, prefer the exact base/heading form from the defining entry. Do not switch to a plural or inflected variant merely because a nearby example sentence uses it.

### Category-labeled Jeopardy records without paired answers

- If the supplied context contains a Jeopardy-style line or record of the form `CATEGORY: Clue` with no delimiter-separated answer side, do not require an answer record and do not return the category label as the answer. Treat the text after the category label as an ordinary `this/these` identification or cloze clue: match its descriptive predicates against all context snippets, return the named entity, work, or title that satisfies them exactly as written, and use the category label only as an additional class/scope constraint.
- A separate document title or heading that names the satisfying entity can support the answer even when the exact clue is not followed by an answer side, provided it matches all clue constraints.

### Reverse naming and eponym extraction

- If the text after `Question:` identifies an entity with a `This [category] was named for/in honor of [person or reason]` clause, the supplied person or reason is already given, so the missing slot is the named entity itself. Locate the context span with `named for`, `named in honor of`, `for whom the X was named`, or an equivalent eponym relation, and return the named entity's name or title exactly as written. Do not return the honoree, source descriptor, or a category word.
- When the clue supplies only a first name of the honoree, do not answer with a fuller person name; return the entity that bears the honoree's name, using the context's eponym sentence.

### Quoted-key and quoted-fragment lookup

- For quoted title fragments, subtitles, taglines, or source-relation phrases covered by the preceding failure-priority title-fragment association rule, do not use this section; return the associated main title or source entity as described there.
- If the text after `Question:` is only a quoted nickname, slogan, or epithet with an optional leading article and no other predicate, and it is not used as a title fragment/subtitle in a compound title or source-relation clue, treat the quoted phrase as an already-supplied lookup key. Locate the context sentence that directly equates the key with an owner, holder, or meaning through `known as`, `called`, `referred to as`, or an appositive, and return that owner/entity or defining attribute exactly as written. Do not return the quoted key itself, and do not let an unrelated informal use of the same phrase override the direct equivalence.
- Preserve the answer form used in the direct sentence, including any article or number present there, rather than copying the article or quoting punctuation from the prompt.
- If a clue quotes a partial name or shared component of a larger proper noun or fixed phrase (for example a terminal route, service, or category word), and that component is not a title subtitle or source-relation phrase covered by the preceding failure-priority rule, treat the quoted fragment as a pointer. Locate the context sentence that places it inside the full proper noun or fixed phrase and return that full phrase exactly as written; do not apply slot-refilling reduction to remove the quoted word.
- If a clue supplies a descriptor or class word alongside a quoted fragment, the missing answer is the complete entity span whose canonical context form contains the fragment, not the fragment itself and not a broader category label.
- When the context offers both a compound form and a shorter base term for the same slot, and the question already supplies the modifier plus a different class word, prefer the shortest base term that directly completes the slot unless the base term is part of a fixed proper noun or phrase explicitly asked for. Preserve the exact singular/plural, spelling, and capitalization of the selected source span.

### Work-title completion for `this [year/medium]` slots

- When the prompt supplies a person/creator, an award/achievement/event, and a demonstrative title slot such as `this [year] movie`, `this [year] book`, `this [year] album`, or `this [medium]`, treat the person and the achievement/event as required constraints. Locate the context sentence that attributes that same achievement/event to that same person for a particular work and return that work's title exactly as written in that sentence.
- Do not return the person, the award, or a different work that merely shares the year or medium. Prefer the sentence that satisfies all supplied constraints simultaneously.

### Short title/tag answer lines for directly matching clue bodies

- If a context line with a short title, tag, or search-ID label has a body that repeats the question's predicate with a `this ...` slot, treat that title/tag as the directly paired answer and return it exactly as written. Use it when the same line is the most direct match, rather than substituting an unrelated heading or body span.
- For a person slot, use a terse title/tag or answer-side short form directly when that same directly matching line supplies only the short form and the prompt does not ask for a full formal name. If the prompt asks for a full canonical name, restore the full canonical form from the same directly matching context or the closest direct defining sentence rather than importing a longer name from a separate background paragraph.

### Possessive team, franchise, and organization-owner slots

- For declarative or Jeopardy-style clues in which a possessive demonstrative or possessive noun is directly followed by a supplied member, team, title, nickname, or institution name (patterns such as `this city's [team]`, `this state's [institution]`, or `[member] and this city's [member]`), the member is supplied clue material and the possessor location or organization is the blank.
- Locate the context sentence that directly pairs the named member with its owner, parent, home city, region, or affiliate and return only that owner or place exactly as written, without repeating the member name or the class/category word already supplied.
- Do not return the already-mentioned member, team, franchise, or another sibling member; the slot asks for the possessive or ownership attribute, not the listed entity.
- If multiple places or owners could be associated with the supplied member, require remaining modifiers in the clue, such as league, arena, period, sponsor, or paired member, to select the one supported by the same context span.

### Acronym and initial-slot expansion

- When a question asks what a specific letter or ordinal position in an acronym or initialized name stands for, locate the supplied context where the acronym is expanded into a full named entity or place name, often in source titles, headers, or body sentences. Count the initials in the acronym as written, align the requested ordinal letter with the corresponding component of that expansion, and return only that component exactly as it appears in the context.
- Do not answer from an unrelated occurrence of the same initial elsewhere. Prefer the context span that places the acronym together with its full expansion, and use that expansion to identify the ordered component. If the needed component is part of a proper place or entity name, return that component alone, not the whole expansion or the acronym.

### Error-tolerant matching and fraction-versus-ordinal cues

- Treat minor spelling, typographical, or OCR-style errors in the question as near-equivalent to the correct source wording; do not fail over a small lexical mismatch when the main relation and content words match the context.
- When a proportion is expressed as a spelled-out or numeric fraction such as `1/5`, match approximate percentage forms such as `20 percent` or `21 percent` in the surrounding context. Treat a same-word ordinal such as `fifth` in a phrase like `a fifth group` as an order marker, not a proportion, unless the question explicitly asks for sequence position.
- Prefer the context span that explicitly pairs the target entity with the percentage or fraction value, and return the entity associated with that numeric value exactly as written.

### Restoring truncated quiz and flashcard answer sides

- If a matched Jeopardy-style, flashcard, delimited QA, or quiz record has an answer side that is truncated, initial-only, or ends in an ellipsis or incomplete proper name, treat the fragment as a pointer to the full named entity. Locate the complete canonical title, proper name, or fixed phrase elsewhere in the supplied context, such as an expanded title, heading, or body sentence, and return that full form exactly as written.
- Do not return the truncated fragment itself. This applies to proper names, event names, titles, and fixed phrases, not only to person names. Preserve the source capitalization, punctuation, and spelling of the complete form.

### Inferring larger administrative units from place hierarchies

- When a prompt names a person or entity and a county, town, city, or nearby feature and asks for the larger administrative unit such as `this state`, `this country`, or `this region`, locate the context span that supplies the full place hierarchy or nearby-place relation, for example `X in County, State`, `X, City`, or `X near City`. Return the larger unit from that hierarchy exactly as written, not the county, city, or nearby feature already supplied in the prompt.
- If the direct entity has no location sentence, prefer a directly related entity or family member in the same context whose stated birthplace, state, or capital city is the only supported candidate satisfying the prompt. Do not return a place merely because it appears nearby; verify the relation ties it to the entity or clause in the question.


## Exact answer-side precedence for matched quiz/flashcard records

- When the question matches a Jeopardy-style, flashcard, delimiter-separated QA, or quiz record, the matched answer side is authoritative and must be returned exactly as written, including surname-only, nickname-only, abbreviated, or common short title forms.
- Do not expand a complete terse person answer to a fuller canonical name from nearby prose, headings, or body sentences just because that fuller form appears in the supplied context. Expand only when the prompt explicitly asks for a full/formal/official name or when the answer side is truncated/ellipsized rather than a complete short answer.
- This overrides the earlier `Person-name canonical form over terse answer records` and any full-title/canonical expansion when an exact clue-answer match exists. Keep the answer-side capitalization, spelling, article, and number exactly.


## Short-form and base common-term precedence for broad demonstrative, class, place, and count-noun slots

- When a declarative or Jeopardy-style identification clue has a broad class slot such as `this [class] found in X`, `this [class] was a relative of ...`, or a plural geographic slot such as `these mountains`, `these islands`, or `these lakes`, collect all context forms that identify the same referent and prefer the shortest established common/quiz-style form that grammatically completes the slot.
- Do not substitute a longer formal, regional, or taxonomic variant when the slot is a broad class noun or plural feature noun. For a `these [plural feature]` slot, prefer the context's shorter established plural nickname over a longer `X [Feature]` form. For a `this [class]` slot with a locational or relational predicate, prefer the base common noun over a proper/regional modifier, unless the prompt explicitly asks for a formal, official, species, or subspecies name.
- For count-noun demonstrative slots such as `one of these`, `shaped like one of these`, or `a back shaped like one of these`, choose the shortest general object/category noun that directly completes the slot. If the most directly illustrative source span uses a modified or compound phrase, such as a multi-word object term with a restricting modifier or a technical/compound variant, but the same document or a nearby source span uses a simpler base common noun for the same object, return the base term rather than the over-specific compound. The narrowing modifier is a specific subtype and is only needed if the question itself asks for that subtype or uses a distinguishing contrast.
- Preserve the article that belongs to the short form: the indefinite article for a singular count-noun slot such as `a back shaped like one of these`, and the definite article on a plural nickname or common-noun quiz answer. Do not drop the article merely because a longer variant appears without it.
- Use the direct relation to identify the entity, but do not let the direct sentence's longer co-referential name override the short answer form. Before finalizing, insert the candidate into the original slot; if a shorter common count-noun phrase or short established form from the supplied context is sufficient, prefer it over the more specific compound or longer formal variant, even when the longer form appears in the sentence that first triggered the match.
- This rule takes precedence over formal-name/canonical-name expansion for these broad demonstrative class, plural place, and `one of these` count-noun slots. Only expand to a formal/technical/compound form when the prompt explicitly asks for that subtype, full formal name, or official title.


## Truncated person-event or entity-event fragments as attribute lookups

- If the text after `Question:` is a named entity immediately followed by a preposition/predicate fragment such as `Name for [event/crime/activity]`, `Name in [event]`, or a run-together phrase with missing spaces or punctuation, do not answer with another person who was involved with that named entity. Treat the fragment as an incomplete lookup sentence and reconstruct the missing slot from the context sentence that directly predicates or locates the named entity together with the event/activity keyword.
- Prefer the shortest attribute complement from that same sentence or span, for example a date, century, era, place, status, or institution, that completes a plausible reading of the fragment. Return that complement exactly as written.
- Only return a co-participant, accuser, opponent, plaintiff, or associated actor when the fragment explicitly asks for that role, such as `who sued X` or `who accused X`, or when the named entity is the object of an explicitly stated action whose agent is the requested slot.


## Exact class and economic-share constraints over nearby superlative keywords

- When a product, crop, or trade clue supplies multiple economic descriptors such as `accounts for a third`, `makes up X percent`, `leading source of income`, `main export`, `principal export`, or `leading export`, treat each descriptor as a separate required constraint. Collect every candidate associated with any of them in the supplied context.
- Do not select a candidate only because it appears near `leading export`, `main export`, or another superlative if the same context assigns it a different share than the question's fraction/proportion, or if the candidate fails the requested common class noun (for example a fruit crop, cereal crop, beverage crop, or root crop). A single lexical cue is not enough when other stated constraints remain unsatisfied.
- For crop/product categories, prefer the candidate whose conventional class matches the question's everyday category term over a candidate that only technically or botanically falls into that class while the context classifies it under a different market or commodity class. Do not reason from marginal botanical inclusion to override the explicit class word.
- If no single context span contains both the numeric share and the qualitative income/export role, prefer the candidate that satisfies the class term plus the qualitative economic relation over one that satisfies only one headline superlative with an incompatible or missing share.
- Before finalizing, restate the key constraints of the clue: category/class, numeric share or rank, and income/export role. Verify the chosen candidate is directly supported by the same context span or the most directly defining span for all constraints. A candidate that repeats only one cue is a distractor.


## Informal participant-led work/title clues prefer the shortest directly matching body title

- When the text after `Question:` is an informal demonstrative work/title clue that names one or more participants, creators, or stars and supplies a descriptive predicate (for example `X and Y star in this ...`, `X presents this ...`, or `this behind-the-scenes look at a ... show`), collect every title form associated with those participants and that predicate in the supplied context.
- Prefer the shortest established title form from the body sentence that directly co-locates the named participants and the descriptive predicate, such as `"Short Title" stars X, Y ... It is a ...` or `... the [predicate] series "Short Title"`. Return that form exactly as written, preserving its capitalization, spelling, and punctuation.
- Do not replace that directly matching short title with a longer official, full, or formal title from a document heading, title line, lead paragraph, or separate encyclopedic sentence merely because the longer form is more complete or appears earlier. The full official title is only correct when the prompt explicitly asks for the full, formal, or official name, or when no shorter established body-title form directly satisfies the participants and predicate.
- Before finalizing, restate the clue as `A and B star in this [class/predicate]` and verify the candidate is the span used in the directly matching body sentence. A candidate that adds a trailing subtitle, parenthetical, or official-title extension is over-extracted for these informal demonstrative clues.

## Bare comma-separated lists in quiz/archive lines take record precedence over shared-attribute lookup

- If the text after `Question:` is only a bare comma-separated list of named entities and that same list appears as a leading entry in a Jeopardy-style, flashcard, quiz, or archive/record line in the supplied context, do not immediately apply the shared-attribute lookup rule and answer with a broad class, location, or category such as the group name that contains all listed entities.
- Treat the list as record/clue material. Prefer the first listed entity from that leading record line as the short answer, exactly as written there, unless another part of the same record explicitly pairs a different listed entity with the clue or answer slot.
- Only fall back to returning a shared attribute or common category for a bare comma-separated list when the supplied context contains no such direct list/record pairing. A separate list, heading, or classification sentence that merely groups the listed entities does not override the leading record-line candidate.

## Product/class-definition clues over example and ingredient matches

- When the question is a terse noun phrase that defines a product, treatment, tool, or other class by a property and a function (for example an `An [property] [used/applied to do X]` pattern), first search for a source sentence or title that assigns that same property and function to a general class term (for example `[Class] reduce/control/prevent X` or `[Class] are applied to ...`). Return that general class term exactly as written.
- Do not return a specific example, ingredient, home remedy, brand, or proper-noun item that merely shares the property or function and appears near the same body site. Such examples are evidence for the property, but they are not the requested term unless the clue asks for a named example, recipe, or ingredient.
- The rule against adding generic category or class words does not apply when the missing slot itself is the category/class term. For a definitional phrase, the general common-noun category from the directly defining context span is the short answer.
- Before finalizing, restate the clue as `What is the class/term for [this]?`. If the question defines a type rather than asks for a specific named instance, reject named instances even when they satisfy the same property, and preserve the class term's exact spelling and capitalization from the source.

## Inflection from negative contrasts and current quiz-line evidence

- When a cloze, fill-in-the-blank, or Jeopardy-style clue contains a negated contrasting noun after `not`, `not a`, `not an`, or an equivalent contrast such as `this [class], not [contrast]`, treat the grammatical number and count form of that contrast as part of the slot. If the supplied context supports the target in the corresponding plural or count form in a direct defining sentence, list, table, or entry, return that exact form as written; do not singularize merely because the slot wording says `this [singular class]`.
- In flashcard, quiz, or QA lists where the current clue has no visible paired answer side, do not borrow an answer side from an adjacent or nearby line simply because both lines share a category, class, or descriptor word. An adjacent answer side is a distractor unless its own clue matches the current question. Search for a direct definition, list, or separate context span that satisfies the current clue, and take the answer form from that span.
- If a nearby quiz-answer line for a different clue conflicts in singular/plural form with a direct source listing or definition for the current clue, prefer the direct source span for the current clue. Preserve exact count, capitalization, spelling, article, and punctuation from the chosen span.



## Additional success-verified clue patterns

### Parent-organization and institutional-owner slots

- When a declarative or Jeopardy-style clue supplies named people, teams, players, members, or other units and asks for the owning organization, institution, or parent body through patterns such as `this organization's Hall of Fame`, `this institution`, `this chain`, or a similar possessive/relational slot, treat the named units as clue material, not the answer. The blank is the owning organization or parent body, not the hall, branch, members, or a broad category term.
- Locate the context span that directly ties the named units to the institution and any stated founding year, membership criterion, or ownership relation (`is part of`, `operated by`, `a unit of`). Return the parent organization name exactly as used in that span. Do not expand a short organizational form to its full official expansion unless the prompt explicitly asks for the full/formal/official name.
- Do not return the named entity or branch itself.

### Work-title completion by achievement/record, performer/character, or source/description constraints

- When a clue supplies an achievement, first/record, or statistical milestone plus a demonstrative or relative medium/network/studio/genre title slot such as `from this [network/studio/genre] [movie/book/album/show]`, treat the achievement/record and medium/network/studio/genre as required constraints. Locate the sentence assigning that achievement or record to a specific work/title and return that title exactly as written.
- When a prompt supplies credited performers or actor names plus a character/role they play, a medium word, and a demonstrative or year slot, treat the performers, characters/roles, and year/medium as mandatory constraints. Locate the line that directly places the same performers or characters together and matches the year/medium, and return the title exactly as written there.
- When a prompt identifies a work through a demonstrative title slot and supplies a year/medium, a source/basis relation (`based on`, `adapted from`, `inspired by`, etc.), and a description, plot event, or subject, treat all three as required constraints and return the title from the context span that satisfies all of them.
- Do not return the medium, network, studio, soundtrack, person, actor, character, source author, achievement phrase, or another work that shares only some constraints.

### Bare indefinite definitional gloss to headword

- If the text after `Question:` is only a singular indefinite definitional gloss beginning with `A ...` or `An ...`, treat it as a dictionary/glossary look-up clue. Locate the supplied context entry whose definition directly matches the gloss and return that entry's headword/base term exactly as written, not the explanatory definition, an inflected example, or a document title.
- For common-noun senses, prefer the shortest base term from the defining entry or sentence over a longer modified technical term unless the prompt explicitly asks for that subtype. Preserve any article only when it is part of the direct source answer form.

### Clause-embedded quoted slogan/nickname and pronoun resolution

- When a clue embeds a quoted slogan, campaign phrase, nickname, or tagline inside a conditional or pronoun clause, treat the quoted text as supplied clue material, not as the answer.
- Resolve the pronoun or demonstrative by locating the context sentence that directly equates the quoted phrase with a named person, candidate, brand, organization, or other entity, and return that named entity's canonical context form exactly as written. Do not return the quoted phrase, the object carrying it, or a generic class word.

### Comma-separated ALL-CAPS flashcard and glossary records

- If a supplied context line resembles a flashcard or glossary entry with the clue/term first and the answer directly after a comma or semicolon, treat that line as a paired QA record. Match the question against the pre-comma/pre-semicolon clue both verbatim and by paraphrase, and return only the post-delimiter answer side exactly as written in that line.
- This includes uppercase or title-style flashcard text. Preserve the answer side's exact wording, singular/plural, and capitalization; do not search for a fuller canonical form unless the answer side is truncated, initial-only, or a terse person form governed by the person-name rules.
- Do not apply comma-separated QA parsing to ordinary prose sentences where the comma-separated item is not an answer to the question's nearest preceding clause.

### Abbreviation- or code-tagged phrase and slogan prompts

- If the prompt after `Question:` has the form `Phrase: ABBR` or `Slogan: CODE`, with no explicit question word or blank, treat both parts as supplied clue material. The abbreviation or code is not an answer side and not the requested return.
- Resolve the abbreviation or code to its full proper name or short established name using the supplied context, then locate the context span that directly associates the phrase with that named entity, place, brand, work, or organization. Return that named referent exactly as written, without adding the code or repeating the phrase.
- If multiple entities share the phrase, use the abbreviation or code to select the one whose full name expands to or denotes that code. Do not return a broad class word, a document title that merely echoes the phrase, or the code itself.

### Named-exemplar role and class extraction

- When a demonstrative or cloze prompt identifies the missing entity only as `this person`, `this type of person`, `this position`, `this role`, or similar and then gives a named example with `like <name>`, `such as <name>`, or `for example <name>`, do not return the named example itself.
- Treat the named example as a pointer to the role, office, rank, occupation, or common-noun class it occupies in the supplied context. Locate the context span that explicitly assigns that role or class to the named example, and return that role or class word exactly as written, omitting any words the question already supplies.
- Return a proper name only when the prompt asks for an individual identifier or when the context supplies another named entity satisfying the full predicate.

### Bare cast/member/character lists prefer the containing work, series, or team title

- If the text after `Question:` is only a bare comma-separated list of names, and no direct quiz/archive/record-line pairing exists under the bare comma-separated list quiz/archive record-precedence rule above, and the supplied context presents those names as cast members, characters, regular members, or components of a named work, series, organization, team, or group, do not stop at the shared class/descriptive noun and do not return the list itself.
- Locate the most direct context sentence or document title that binds the listed names to their containing title and return that containing work/series/team/group title exactly as written.
- Use the existing bare comma-separated list shared-attribute fallback only when the listed names are not governed by that quiz/archive record rule and are not characters/members of a single named container, or when the prompt explicitly asks for a common attribute such as location, nationality, class, or owner.

### Partial-title and title-adjacent completion

- When the prompt supplies a quoted or near-quoted fixed title prefix and then asks for the entity or place that completes the title, treat the supplied prefix as clue material.
- Locate the context sentence or title line that contains the full fixed title `Prefix + X` and return only the missing completion `X` exactly as written. Do not return the full title, the supplied prefix, or a broad class noun unless the question explicitly asks for the full fixed title.
- Prefer the source form used in the direct title/defining sentence; if the context contains both a short title and a longer subtitle, use the form that directly supplies the missing completion slot.

### Group-perspective and reciprocal rename clues

- When the question has the form `[Group/region speakers] refer to [X] as this`, `[Group] calls [X] this`, or `[Group] know/say [X] as this`, locate the context sentence that uses the same group-perspective expression.
- Return the span that fills `as Y` or the group's label for the supplied entity exactly as written, preserving any article and capitalization. Do not return the reciprocal label used by another group, the source entity itself, or a broader formal/canonical name unless the prompt explicitly asks for it.
- If the context provides both directions, select the direction whose subject matches the group named in the prompt.

### Shared head-noun completion from alternate-modifier Jeopardy/quiz clues

- When a Jeopardy-style, category-labeled, or quiz clue supplies two alternate modifiers or examples before or after a single missing common-noun head, locate the context spans that attach both modifiers to the same head noun and return only that head noun exactly as written.
- Treat any already supplied class noun as clue material; do not return it and do not return one of the modifiers or the broad class alone.
- Prefer the shortest base common noun from the direct context span that fits both alternatives, preserving exact singular/plural, capitalization, and spelling.

### Work-title-plus-secondary-credit clues resolve to the principal creator

- When a declarative clue names a work or collection and identifies its creator through a secondary known work, nickname, or credit phrase such as `this "X" author` or `the "X" writer`, treat the named work and the secondary identifier as clue material.
- Locate the context span that directly attaches the named work and the secondary identifier to the same person, and return that person's name exactly as used in that directly matching span.
- Do not return the work title, the secondary known work, or a generic role noun. Prefer the short/familiar full personal name used in the direct sentence over a longer formal birth name in a distant heading unless the prompt explicitly asks for a full/formal/official name.
