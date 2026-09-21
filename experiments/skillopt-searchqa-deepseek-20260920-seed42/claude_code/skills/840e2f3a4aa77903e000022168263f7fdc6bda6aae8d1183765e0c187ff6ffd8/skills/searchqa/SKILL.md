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


## Company/organization name reduction from paraphrased industry-class slots

- If a demonstrative identification slot uses a paraphrased industry or category phrase (for example `this satellite radio company`, `this restaurant chain`, or `this software firm`) and the supplied context gives a longer company/entity name that repeats the same descriptive category words as part of its official-looking name, treat those repeated category words as supplied clue material.
- Remove the redundant industry/classification suffix from the candidate even when the source capitalizes it inside the name. Return only the shortest distinguishing proper-name portion that can complete the slot: `this satellite radio company` should get `X`, not `X Satellite Radio`, unless the question explicitly asks for the full official, corporate, or legal name or for a full fixed title.
- Do not let the fact that the longer form is a proper noun in the source override the supplied-category reduction. A fuller corporate/descriptive name is over-extracted if its tail restates the question's class words.
- Preserve source capitalization and spelling of the retained proper-name portion.

## Bare named-person/entity lists prefer a single named common attribute over third-party relations

- When the text after `Question:` is only a bare conjunction/separator list of named entities (for example `Name1 & Name2`) with no explicit question word, blank, or category noun, collect every context span that assigns the same simple attribute to all listed names: a place/location, affiliation, country/region, team, company, owner, parent, or other named attribute.
- Prefer the shortest single named attribute value from a direct context sentence, especially when that value appears as the location/affiliation complement in the entities' own source names or titles (such as `X of Place` / `Y of Place`). Return that value exactly as written and do not include the preposition or class word unless it is part of a fixed name.
- Do not return a relational clause into a third named entity (for example `siblings of Person Z`, `children of Person Z`, or `members of Group G`) when the prompt does not explicitly ask for that relationship. A family or membership relation is evidence for identifying the named list, but the implied answer slot should be the common named attribute itself.
- If multiple common attributes are supported, prefer a named place/location or institution complement over a predictive relationship clause, and prefer the shortest source span that directly pairs all listed names with the same attribute.

## Original/base title over altered, punning, or derived forms

- When the question states that a modified, punning, adapted, or derived title or phrase was created by changing or replacing one word or segment of an original (patterns such as `changed "X" to "Y" in this original title`, `a spoof/adaptation of TITLE`, or `taken from TITLE`), treat the modified/derived form as supplied clue material, not as the answer.
- Locate the context sentence that explicitly equates the modified form with its source through relation words such as `changed ... to`, `taken from`, `based on`, `adapted from`, `derived from`, or `also used as`, and return the original/base title or phrase exactly as written in that sentence.
- Do not return the modified/pun form, the adaptation title, or a heading/list item that only displays the modified title. A derived form containing the changed word is a distractor when the question asks for the original/canonical title.
- If the question uses `this` plus a category word such as `title`, `original title`, `source work`, or `work`, use that category to select the base title from the defining relation, not the adapted counterpart that co-occurs in the same context.
- Before finalizing, restate the relation as `Altered form was created from this original ___` and verify that the candidate is the source/base form, not the altered or derived form.

## Matched quiz/flashcard answer-side reduction for supplied class heads

- When an exact or near-verbatim Jeopardy-style, flashcard, delimiter-separated QA, or quiz record matches the question, use the matched answer side to identify the target, but before finalizing insert it into the question's explicit or implicit slot. If the question already supplies a class/category head noun through a demonstrative such as `this [class]`, `that [class]`, or `these [class]s`, remove that same class/category word from the answer side. Exact answer-side precedence protects terse proper names, person names, and work titles; it does not justify repeating a class word that is already present in the question.
- When the reduced answer completes a singular definite or count phrase, supply the article required by the completed slot (`a`/`an` for an indefinite singular count phrase, `the` for a definite singular/plural phrase), using the closest source/prose form of the completed phrase when available. Do not leave an ungrammatical bare modifier if the completed slot requires an article.
- If the matched answer side is entirely uppercase or stylized only because of quiz/flashcard formatting, normalize it to the prose case used in the surrounding context while keeping the reduced span.
- Example pattern: a question asks for `this [class]` and a matching answer side is `[modifier] [class]`; return the missing discriminator plus any required article, not the full `[modifier] [class]` phrase.
- Before finalizing, replace the demonstrative with the candidate and verify that the class word is not repeated. Preserve spelling and capitalization after case normalization.

## Pronoun-resolved Jeopardy and cloze clues prefer the shortest directly attested name form

- If a declarative or Jeopardy-style clue uses a personal or possessive pronoun (`his`, `her`, `their`, `he`, `she`) or an informal demonstrative pro-form and does not explicitly request a full/formal/official name, resolve the pronoun to the identified referent and return the shortest well-attested name or title form used in a context span that directly mirrors the clue predicate.
- This applies especially when the supplied context contains a category-labeled quiz line without an answer side. Treat that quiz line as ordinary cloze evidence, then use a nearby title, heading, or directly matching body sentence that pairs the same predicate with a short name form (for example `Name defeated at X`, `Name's final defeat at X`) as the answer form.
- A longer canonical form in a separate summary or lead sentence (for example `the defeat and second abdication of Full Given Surname`) is supporting evidence for identity, but it must not override the shorter predicate-matching form unless the prompt explicitly asks for a full/formal/official name, an office-holder title, or another status requiring canonical completeness.
- Before finalizing, restate the completed clue as an answer line. If the source's most direct answer-like phrase, title, or heading supplies a shorter name, keep that shorter form exactly as written. Do not expand it merely because a fuller form appears elsewhere in the supplied context.

## Full fixed name completion for conjunction and ampersand blanks

- When a fill-in-the-blank or cloze prompt supplies one member of a fixed proper noun joined by `&`, `and`, or another coordinating conjunction (for example `___ & Y`, `X & ___`, `___ and Y`), treat the blank as part of a fixed proper name or partnership title, not as a removable class/location word.
- Locate the source context span that contains the complete fixed phrase and return the entire proper noun exactly as written there, including the already supplied member and the conjunction. Do not reduce the answer to only the missing component.
- If the context contains both `&` and `and` forms, prefer the full source form whose conjunction and spelling match the prompt's supplied surroundings.
- Slot-refilling reduction removes only supplied category, location, or class nouns outside proper names. It must not remove the supplied tail/head of a fixed proper noun or official partnership title.
- Preserve exact capitalization, spelling, punctuation, and spacing from the selected source span.

## Exact orthographic form for acronym and initialism expansions

- When the question supplies a short marker, acronym, or initialism and asks what feature or term it names, locate the context sentence that directly expands or equates the marker with its long form (for example the phrase immediately before a parenthetical initialism, or a definition line of the form `long form (MARKER)`). Return that direct expansion exactly as written in that same sentence.
- If the context contains multiple orthographic variants of the same term, such as an open compound `X in Y` and a hyphenated compound `X-in-Y`, prefer the variant from the directly defining or equating sentence over variants in unrelated headlines, titles, or later snippets.
- Do not normalize hyphenation, spacing, capitalization, or punctuation between variants. Exact-match evaluation depends on returning the exact source form.
- This applies to definitional acronym or initialism lookups; it does not override exact answer-side precedence for matched Jeopardy-style, flashcard, or delimiter-separated QA records.


## Supplemental success-derived clue-resolution patterns

### Inverse possession and favorite-object slots return the owner/person
- When a declarative or cloze clue supplies a named object, tool, device, item, or creation as `the favorite X of this [role/descriptor]`, `the X of this [person/place]`, or another inverted possession relation, treat the supplied object as clue material. Locate the context sentence that directly assigns that object to its named owner, user, or associated person, and return the owner/person exactly as written.
- The slot is the missing possessor/owner, not the object and not a broader category word. Use all role, period, place, or action modifiers in the question to select the correct person. Prefer the context snippet that directly pairs the object with the same descriptors, such as `[Person] had a [thing] that was known as the '[name]'` or `[Person] ... his favorite [thing]`.
- This extends the existing creator/source and possessive-team rules to generic favorite-item, instrument, apparel, weapon, or possession pairings. Preserve exact source spelling and capitalization.

### Impostor and assumed-identity slots return the person whose identity was borrowed
- If a prompt names a person and says that person gained access, became infamous, or inspired a work by `posing as`, `claiming to be`, or `convincing others they were` `this [role]'s [relative]`, or describes an `ersatz/spurious [relative]` of an unnamed person, the missing slot is the borrowed identity, not the impostor or the relative label.
- Locate the context sentence that directly ties the named impostor to the assumed identity through wording such as `posing as [X]'s son`, `convincing them he was [X]'s son`, `the ersatz son of [X]`, or similar, and return the identity-holder `X` exactly as written.
- If multiple spellings appear, use the spelling from the most directly defining sentence or the dominant prose form. Do not return a co-mentioned alternative relative or a person who merely appears nearby.
- This refines the possessive-demonstrative rule: in a possessive relative phrase such as `this actor's son`, the possessor is the missing slot because the relative and the impostor are already supplied as clue material.

### Inverse named-for/honoree resolution when the named object is supplied
- When the prompt supplies a named object, place, studio, award, or institution and says it is `named for`, `named after`, or `named in honor of` a missing person or descriptive slot such as `this late journalist`, `this [role/nationality]`, or `her`/`him`, the missing slot is the honoree/person, not the named object.
- Find the sentence that directly states the naming relation and return the person's canonical name exactly as written there, following the person-name canonical-form rule unless an exact matched quiz/flashcard answer side takes precedence.
- This is the inverse of the existing reverse-naming rule: when the honoree is supplied and the named entity is missing, still return the named entity; when the named entity is supplied and the honoree/person is missing, return the person.

### Bare descriptive common-noun prompts are implied lookups for the defining equivalent term
- If the text after `Question:` is only an article plus a descriptive common-noun or class phrase, such as `An Anglican parish priest`, `A ...`, with no explicit question word, blank, or demonstrative slot, do not return that input phrase, a broader class label, or a heading that merely repeats the phrase.
- Treat the phrase as clue material for an implied equivalence lookup. Locate the directly defining or classifying context sentence and return the shortest specific equivalent role/title/term from that sentence, for example from wording such as `is usually called`, `is also called`, `is`, or a definitional appositive.
- If the context gives two coordinate equivalents, prefer the one from the sentence that directly defines the full supplied phrase and matches every qualifier; when both are equal, return the first direct equivalent spelled exactly in that defining sentence. Do not add a class word already supplied in the prompt unless it is part of the fixed term.
- This extends the earlier bare-term and implied-slot rule to descriptive common-noun prompts. It does not apply to bare proper names, bare comma-separated named-entity lists, or titled-work lookups.

### Name-meaning and translated-name reverse lookup
- When the prompt states that `the name of this/these [class] means/translates to` a quoted or described word, treat the meaning as already supplied clue material, not as the answer.
- Locate the context span that directly pairs a proper name or headword with that meaning through language such as `means`, `literally`, `translates to`, `in [language]`, or a dictionary-style definition under the name. Return only the named entity, base term, or proper name exactly as written in that span.
- Do not return the quoted meaning, the language, the class/category word, or a different named entity that shares the language but has a different meaning. Prefer the body sentence that contains the exact meaning relation over a distant heading or unrelated definition.

### Presentational copular-definition clues return the predicate noun, not the named brand/place
- If the text after `Question:` is a declarative presentational clue that provides a quoted or descriptive definition of an object and then says it is a `mainstay`, `specialty`, `type`, `example`, or `fixture` of a named brand, chain, region, or institution, treat the named brand/place as supplied clue material. Resolve the missing slot to the base common noun or noun phrase that is directly predicated of that definition in the source.
- Use the source sentence that most directly defines or identifies the object by the same purpose, composition, or presentation, such as `[Brand]'s [answer] may be ...` or `[answer] is ... made with ...`. Return that common-noun head exactly as written, without the named brand/place and without repeating ingredient or class words already supplied by the prompt.
- Do not answer with the brand, chain, place, ingredient list, or a broader category term unless the prompt explicitly asks for the brand or category. This refines the existing definitional shortest-span rule for copular presentational clues.

### Definitional `This phrase describes ...` glossary slots
- If the text after `Question:` is a definitional gloss such as `This phrase describes X`, `This term describes X`, `A phrase for X`, or `The term for X is ...`, treat the descriptive clause as clue material. Find the supplied context sentence that defines a headword/term with that exact or paraphrased description and return only that headword/term phrase exactly as written.
- Do not return the descriptive clause, a neighboring legal label, a document title, or a generic class noun when the source explicitly gives the term as a headword. A context line of the form `Headword definition, <definition>` supports returning the headword, not the definition phrase or a nearby longer title.
- Keep the source's spelling, hyphenation, and capitalization for the headword.

### Multi-sense dictionary gloss prompts
- If the text after `Question:` is a definitional prompt that supplies two or more gloss senses joined by `or`, `or to`, or a comma, treat all listed senses as required matching constraints, not as answer material.
- Collect the supplied dictionary or glossary entries and select the headword/base term whose single entry lists all of those senses. Do not answer with a term that satisfies only one sense or with the gloss words themselves.
- Return the exact base/heading form from that defining entry, and do not switch to a plural or inflected variant unless the direct entry uses that form. This is a refinement of the dictionary-gloss rule for conjoined sense prompts.

### Ignore trailing clue-length and page annotations on quiz-style prompts
- If the text after `Question:` ends with a parenthesized integer or short clue metadata such as `(15)`, `(6)`, or `(5,2)`, and the question is otherwise a full declarative/cloze clue, treat the parenthetical as answer-length, page, or point metadata rather than an answer constraint. Match the clue body against the context and return the entity named by the body.
- Do not return the number, the page, or a context snippet merely because it contains the same number unless the question explicitly asks for that numeric attribute.
- Exception: keep parenthetical years when they are part of a bare titled-work lookup (`Title (Year)`) asking for a creator/director, as covered by the existing bare titled-work rule.

### All-caps flashcard and quiz answer sides normalize to prose case
- When a matched Jeopardy-style, flashcard, delimiter-separated QA, or quiz record has an answer side that is entirely uppercase because of flashcard/quiz formatting, and nearby prose, titles, or body sentences supply the same proper name in normal prose case, return the normal prose form rather than the all-caps string.
- This refines exact answer-side precedence only for letter case. Keep the matched answer side's terse surname-only, nickname-only, abbreviated, and short-title forms exactly as given, including article and number. Do not expand the answer or import a different form from a distant snippet.
- If no nearby normal-case prose form of the same answer exists, preserve the answer-side capitalization exactly.

### Instructional conditional slots
- When a question is phrased as a tip, recipe, or how-to conditional such as `Try mixing X with Y if you run out of this [category]`, `If you don't have this [category], use X`, or `When this [category] is unavailable, ...`, match the supplied-context sentence that states the same practical condition or substitution rather than a topically related sentence.
- Locate the exact procedure span, usually containing `run out of`, `don't have any`, `out of`, or `instead`, and extract the missing object/item noun exactly as written there. Apply supplied-class-word reduction: if the question already says the category noun, return only the missing discriminator.
- Do not return the substitute ingredient, the product named in the tip, or an instruction word. Prefer the most directly matching procedure sentence over document titles or general list paragraphs.

### Possessive property and formula facts as implicit class clues
- If the text after `Question:` is only a declarative property/fact statement whose subject is a possessive pronoun such as `Its`, without an explicit question word or blank, treat the statement as a definitional lookup key, not as a yes/no proposition and not as a formula to return.
- Locate the supplied context sentence that presents the same property or formula as the defining attribute of a category or named entity, and return the base common noun or canonical name that is the subject of that defining sentence, exactly as written.
- Do not return the formula, equation, value, or property words already supplied in the clue.

### Demonstrative place-slot resolution from a dated event or causal relation
- When a declarative or cloze prompt has `this [place class]` together with a dated event or causal relation naming a person, work, or later outcome (`... inspired Y`, `... led to Y`, `... created Y`, `... after the X riots`, etc.), treat the date, participant/outcome, and place-class word as required constraints.
- Locate the body sentence that directly binds the place to that event/causal relation, not a nearby document title or snippet that merely repeats some of the same keywords. Return only the place proper noun exactly as written in that directly supporting sentence.
- Do not return the person, work, outcome, year, or a larger/smaller region unless the prompt asks for it. Omit the supplied place-class word (`neighborhood`, `city`, `district`, `region`, etc.) when extracting.
- Prefer the shortest place name from the same directly binding sentence. Preserve exact source spelling and capitalization.

### Transport-connector geographic clues with numeric lengths
- When the prompt gives a physical connector such as a causeway, bridge, or tunnel, an approximate length or distance, and says it connects or links `this [nation/territory/place]` with a named neighbor or mainland, treat the connector, length, and named neighbor as supplied clue material.
- Match the length approximately across fractions, decimals, and units. Return the place or nation named as the connected entity in the same context span that pairs the connector, length, and neighbor, not the already supplied neighbor and not the connector itself.
- Prefer the sentence or title that directly states both the connector and the candidate place, such as `A [length] causeway connects this [place-class] with [named neighbor]`. Do not select a place solely because it appears elsewhere near a similar connector or length; require direct binding of the connector and named neighbor to the candidate.
- Preserve the place name's exact source spelling and capitalization.

### Fixed-title component completion for descriptor-prefixed proper-name blanks
- When the prompt is a fill-in-the-blank fixed proper name with an optional short descriptor before a colon and a missing component inside an institutional, organizational, or work title, treat the words around the blank as a contiguous template.
- Find the source title or heading that contains the full fixed proper name verbatim or near-verbatim, and return only the missing template component exactly as written there. Do not answer with a broad domain or class word merely because it describes the entity's area of activity.
- Do not include punctuation, the preceding descriptor text, or words already supplied in the prompt. If multiple source forms contain the surrounding words, prefer the span whose surrounding template most closely matches the post-colon phrase.

### Author/year/plot-constrained work-title selection
- When a clue supplies multiple narrative constraints for a created work, such as named groups/characters, a setting, and an author/creator plus a year or medium (`... in this [year] [author] [novel/film/album]`), treat each named group, setting, author/creator, year, and medium as a required constraint.
- Locate the context span that ties the same work title to the author/creator and year, and also supports the described groups/action/setting, then return that work title exactly as written. Prefer the title from a sentence or title line that satisfies all constraints simultaneously over a work that shares only the author, setting, or year.
- Do not return the author, a character group, the setting, or a different work with only a partial keyword match. This extends the existing work-title completion rule beyond award/achievement constraints to ordinary plot, cast, and setting constraints.
