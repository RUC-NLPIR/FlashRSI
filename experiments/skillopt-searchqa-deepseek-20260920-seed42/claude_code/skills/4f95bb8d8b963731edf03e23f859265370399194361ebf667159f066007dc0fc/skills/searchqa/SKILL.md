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

- For declarative clues that contain a possessive demonstrative such as "this state's," "this country's," "this nation's," "this region's," "this city's," "this company's," or "this organization's," treat the possessor as the missing slot. Find the body sentence that connects the named institution, feature, division, record, office, seal, flag, motto, symbol, or building to its owner and return the exact owner/location name from that sentence. In clues like "this city's official seal..." or "this city's official motto...," the requested answer is the city/place owner, not the described seal, motto, or symbol.
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


## Short-answer exactness for matched records and direct cloze/Jeopardy evidence

- If the question matches a Jeopardy-style, flashcard, or delimiter-separated QA record, the matched answer side is authoritative and must be returned exactly as written, including surname-only, nickname-only, or common short forms. Do not expand it to a fuller canonical or official name from nearby prose or titles unless the question explicitly asks for a full/formal/official name or descriptive-status form. This overrides the earlier `Person-name canonical form over terse answer records` expansion only for matched QA records.
- For Jeopardy-style or declarative identification clues with a pronoun/possessive or demonstrative (`his`, `her`, `its`, `this`, `these`, `that`, `those`) and no explicit blank, locate the context span that directly expresses the clue relation (event, action, title, or clue record). Return the shortest exact name form used in that direct span, not a longer biographical `Given Surname` or full corporate phrase from a more distant encyclopedic sentence. If the direct span itself is an answer-side record, preserve that answer-side form exactly.
- When a clue presents two or more parallel alternative modifiers for the same missing item, such as `A 'modifier1' class, or perhaps you'd prefer the modifier2`, treat each supplied modifier as already given. Return only the shared head word or base term that can complete every alternative in the context, not the full first compound phrase.

## Bare coordinated names as lookup set for a shared attribute

- If the text after `Question:` is only two or more named entities joined by `&`, `and`, or commas with no explicit blank or question word, do not answer with the relationship between them unless that relationship is explicitly requested. Treat the coordinated names as a lookup set: find the most direct context sentence that assigns a common location, country, region, domain, owner, institution, or class to all of them, and return that shared attribute exactly as written.

## Category and trailing geographic class reduction

- When the question already supplies a class/category or geographic class word after `this`/`these`/`that`/`those` or in the slot (for example `this company`, `this organization`, `this island`, `this river`, `this mountain`, or `this [adjective] [class noun] found in ...`), omit that supplied word from the answer unless it is a fixed leading proper-name prefix such as `Lake`, `Mount`, `Fort`, or `Saint`. If the source has `Brand Category` or `Base GeographicClass` and the question already supplies `Category` or `GeographicClass`, return only the base discriminator exactly as written, even if the longer form looks like a proper or registered name.
- For broad demonstrative category slots, choose the shortest common noun phrase from the directly defining context sentence, including a leading article when the source uses one. Do not substitute a longer regional, subspecies, official, or proper-noun variant from a nearby title or list-style snippet unless the question explicitly asks for that formal or regional name.
- The trailing-class reduction applies only when the same trailing class word is explicitly supplied in the question. Leading fixed-proper-name prefixes remain part of the name.

## Article and number exactness for demonstrative and foreign/local-term clozes

- When the prompt supplies an indefinite article before a foreign/local/defined term, such as `This, an X in PLACE, ...` or `an X is ...`, treat the article as part of the requested answer slot. Locate the direct equivalence or definition sentence (for example `X means 'Y'` or `X (Y in ...)`), and return `a/an Y` using the base common noun exactly as written there. Do not promote a more specific proper-noun or modified form such as `white Y`, `Y of Place`, or an official title unless the question asks for a proper name or title.
- For clues containing a negative or contrast phrase such as `not bananas`, `not X`, or `rather than X`, mirror the grammatical number of the directly related slot and supplied contrast phrase. If the contrast item is plural and the source context supports the corresponding plural form, return that exact plural form as written.
- Exception: for demonstrative plural class-term clues such as `these waves`, `these plants`, or `these [plural category]`, where the requested answer is a general class or phenomenon term rather than a plural named entity or list, do not copy the plural marker mechanically. Locate the defining sentence that equates the examples with a class term and return the base singular/common noun form used there. In these clues, `these`/`those` identifies the set of examples, not the grammatical number of the requested term. If the clue has an explicit plural contrast or plural slot, the plural-contrast rule takes precedence over this exception.
- Before finalizing, insert the candidate into the completed slot, including any required article or number marker. Omitting a required article or using the wrong number is under-extraction; repeating a supplied modifier/category or using a more specific formal form is over-extraction.


## Work-title resolution for container-first clues

- If the text after `Question:` begins with or contains a container phrase such as `In this book`, `In this novel`, `In this film`, `In this series`, `In this play`, or `On this album`, treat the container noun as already supplied. The requested short answer is the title of the matching work, not the named character, event, object, line, or creator mentioned later in the clue.
- Match the remaining plot, character, event, or descriptive details to the context and return the containing work's title exactly as written in the most directly connecting sentence. Do not return the character or event, a heading that names only the character, or a broad class label.
- Before finalizing, insert the candidate into the implied slot `In this [book/film/series] ____` and verify that it names a whole work rather than an already-mentioned person, character, place, or event.

## Category-term answers from plural demonstratives and supplied member examples

- If the text after `Question:` uses a plural demonstrative or category noun such as `these`, `those`, or a `this [category]` phrase and then supplies one or more members through `including`, `such as`, `made with`, or an explicit list, the named members are already supplied clue material. The missing slot is the category/class term grouping those members, not an individual member, not the object made or prepared from them, and not a longer product name derived from the category.
- Locate the context sentence that directly defines the group term by listing or paraphrasing its members, and return that term exactly as written, preserving the singular/plural and article form required by the prompt. For a `this [supplied class]` slot, apply the existing supplied-class reduction and return the missing discriminator. If the same clue is a demonstrative plural class-term clue such as `these waves` or `these plants` and the requested answer is a general class/phenomenon term rather than an explicit plural slot or named list, the Article and number exactness exception for demonstrative plural class-term clues takes precedence and the answer should be the base singular/common noun form from the defining sentence.
- Do not let a frequently adjacent named dish, title, place, or organization override the class term when the blank asks for the category itself.

## Procedural and substitution cloze extraction

- When the prompt is an imperative or conditional how-to clue about what to do when a product, ingredient, or item is unavailable, such as `Try mixing A with B if you run out of this C`, treat the missing slot as the unavailable/replaced item. Locate the context sentence that directly matches the condition through phrases such as `if you've run out of`, `if you don't have`, `out of`, `alternative to`, `substitute for`, or `instead of`, and return the missing item exactly as written.
- Do not answer with the suggested replacement ingredients, the action, the container/product made from them, or a broader class label unless the prompt explicitly asks for that broader entity.
- Treat a sentence that combines the named ingredients/products and the exact condition phrase in the same span as the strongest support. Return the shortest span from that sentence that names the item being replaced or substituted.
- Before finalizing, insert the candidate into the clue's slot such as `this [class]` or `if you run out of this [class]`. Verify that the candidate is the object of the condition, not an ingredient used in the replacement instruction, and preserve the source's exact singular/plural and capitalization.

## Definitional name-by-meaning disambiguation

- When a prompt asks for a name or title by giving a quoted meaning phrase (for example `Common [origin/language] name which means "M"`, `The name of these/this [class] means "M"`, or `[term] means "M"`), treat the quoted meaning as the primary selector and collect every name or term that a context definition or equivalence record pairs with that meaning.
- Apply all remaining prompt modifiers before finalizing: origin, language, gender, common/popular, type/class, singular or collective reference, era, or any other explicitly stated constraint. If multiple context entries share the meaning, discard candidates that match the quoted meaning but fail a stated modifier.
- When the prompt says `these [class]` but the answer is a series, type, or family whose proper name is grammatically singular, return that exact singular proper noun from the definition/equivalence line; do not force a plural answer merely because the wording uses `these`.
- Return the name/title exactly as written in the directly equating context span (for example `Name, M` or `Name means M`), not the quoted meaning, not an etymological component, and not a broad category word. Preserve source capitalization, hyphenation, and spelling.

## Action/event demonstrative person-slot name form

- For prompts such as `In [era], this [person/man/woman] [action] ...` or `This [role] [action] ...`, treat the demonstrative or role pronoun as the blank and locate the context sentence that reports the same action or event relation. The requested answer is the named subject or agent of that direct sentence.
- Return the personal name exactly as it appears in that direct action/event sentence, even if other context paragraphs give a longer or more formal name form with a middle initial or title. Use the longer form only when the question explicitly asks for a formal/official name or when the direct sentence itself supplies that longer form.
- Verify that the candidate fills the slot as the person or agent, not as the object, event, role, or location mentioned in the same clue.

## Demonstrative location slots in event clues

- For prompts where a declarative event contains or ends with `in/from/at this [location class]` (for example `this prison`, `this city`, `this country`), treat the demonstrative plus location class as the blank. Locate the context sentence with the matching event verb or relation (`released from`, `imprisoned in`, `opened in`, `born in`, or similar) and return the named location from that prepositional span exactly as written.
- Do not return the class word or a descriptive adjective. If the source writes the location name with an optional leading article, follow the article form from the direct source span rather than adding an article from a different heading or list entry.

## Pronoun-lead attribute and quoted lead-in completion

- When the text after `Question:` begins with `It's the ...` and supplies a named entity or object plus an attribute/class slot (for example `It's the [attribute] of X` or `It's the [class] of X`), the pronoun refers to the missing attribute, not to the named entity. Find the source sentence that most directly states the relation and return only the attribute value or term exactly as written, omitting the named entity, articles, or classifier words already supplied by the slot.
- When the prompt quotes the beginning of a fixed lyric, slogan, line, or phrase and then asks only for the missing continuation (for example ending in `to this color` or `to this [category]`), complete the slot from the most directly matching source occurrence. If source variants differ by an intervening article or modifier before the target, choose the form that fits the slot's grammar; for an attributive slot, omit the article/modifier rather than returning an ungrammatical phrase. This does not override the existing count-noun article-retention rule for `one of these` clozes.
- Before finalizing, substitute the candidate into the prompt's reconstructed slot; if the result is ungrammatical or repeats supplied words, reduce to the shortest exact source span that fits.

## Visual/structural demonstrative references in text-only contexts

- When a prompt includes phrases such as `seen here`, `shown here`, or says a molecule, object, or other structure is depicted or displayed, treat those phrases as pointing language rather than as part of the requested answer slot. Resolve the answer by the remaining functional or relational predicate in the prompt, such as what the thing is used as, connects, depicts, or produces, and return the canonical term or name from the context sentence that directly ties that predicate to the entity.
- Do not let a visual or structural word in the question select a visually adjacent but unrelated entity from the context. Prefer the context span that satisfies the non-visual predicate exactly, and preserve its exact source wording.

## Short topic/tag titles as directly paired answers for repeated clue bodies

- If a context line carries a short title or topic tag such as a search-ID line, topic label, or single-category title, and the same context line's body repeats the question's predicate with a `this [category]` slot, treat that short title or tag as the directly paired answer and return it exactly as written.
- Use this title/tag answer only when no body sentence supplies a competing canonical attribute for the same slot. In that case prefer the short tag over unrelated document titles and over extra descriptor words copied from the body.
