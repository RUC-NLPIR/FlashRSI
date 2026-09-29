---
name: hotpotqa
description: Use for every supplied-context question-answering task in this HotpotQA experiment.
---

# Question Answering Skill

Use only the supplied context; do not search externally or rely on outside knowledge.

## Answering Rules

- Return only the requested short answer; do not write a sentence, restate the question, add explanations, Markdown, bold, parentheses, or trailing punctuation.
- Do not infer facts that are not explicitly stated in the supplied context.
- Copy the exact wording from the relevant context for descriptive phrases, named entities, titles, ordinal positions, and numeric/spelled-out forms (e.g., return `four` if the context says `four`, not `4`). For attribute/category questions such as `What style/type/genre of ...?` or questions that already name the requested category or unit (e.g., `what genre of films`, `what type of music`), return only the exact requested value from the context. Do not copy the whole descriptive noun phrase, the entity/category head, or the category noun already present in the question.
- Before finalizing, compare the answer with the wording in the relevant context sentence; exact-match grading may require context wording rather than synonyms.

- For organization, company, distributor, studio, label, or similar named entities, return the full canonical name exactly as stated in the direct evidence sentence, including suffixes such as `Films`, `Company`, `Corporation`, `Inc.`, or `Ltd.`. Do not shorten the target entity's name to the bare headword, even if a shorter form appears in another context block or in an intermediate bridge mention.
- For person questions, use the person's own context block as the canonical name source when the question resolves the person through a bridge mention in another block. If the bridge mention uses a shorter form but the person's own title/introductory sentence contains extra given or middle names, return the fuller form from that own block. If the direct answer relationship is stated in the person's own block with a particular name form, use that form rather than expanding a parenthetical. Include first names, middle names, and quoted nicknames exactly as stated in the canonical source, not from bridge/cross-reference mentions or shorter labels in the question.
- For questions asking "who is/was X" or "what role does X have", return only the descriptive phrase from context that identifies the person, not a sentence containing the person's name.
- If a singular "who" question asks for one person but the context gives a compound phrase such as "produced by X and Y", return only the first named entity unless the question explicitly asks for all or multiple people.
- For location questions, return only the location name as stated, without appending associated venue or organization details unless the question asks for them.

## Procedure

1. Read the question carefully and determine the requested short-answer type (e.g., name, date, place, yes/no, description, comparison).
2. Identify the named entities, bridge clues, and the requested relation or comparison.
3. Treat all supplied context as a single searchable evidence base; locate the relevant paragraphs by title and scan for explicit dates, names, numbers, and relationships. If the question asks about an entity but that entity's own context block lacks the requested information, scan every other context block for mentions of that entity or closely related entities.
4. For multi-hop or bridge questions, use a fact from the first entity's paragraph only to identify the intermediate entity, then read that entity's own paragraph for the answer. When the question asks for a property of that intermediate entity (such as its country, location, or other attribute), prefer the statement in that entity's own paragraph over a conflicting descriptive phrase in the first entity's paragraph. Facts about a target entity may appear inside another entity's description only when the target entity has no own context block or the requested fact is not stated there.
5. For comparison questions, extract the same comparable property or value for each candidate and compare them directly. For yes/no comparisons, answer "yes" only when the context explicitly states the compared attribute for both entities; broad descriptions such as "multi-instrumentalist" do not establish a specific instrument, so answer "no" if explicit support is missing.
6. For birth-year or birth-date questions, look for the relevant context block containing `(born ... <year>)` and return only the requested part.
7. Before answering that something is not stated, verify the requested property under all plausible surface forms and related terms (e.g., area vs. volume, size, capacity); prefer the context's stated value and units.
8. Return only the short answer requested; no extra explanation, sentences, citations, or surrounding text.

## Checks

- Prefer the supplied context over outside knowledge.
- If a term is ambiguous, select the paragraph whose relationships match the question.


## Classification Answer Form

- For classification questions such as `What are X and Y?` or other plural question phrasing, return the singular category noun that the context uses to define each item, not a pluralized form. If the context says each item `is a novel`, answer `novel`, not `novels`, even when the question uses a plural verb such as `are`.


## Resolving Anaphoric and Medium Questions

- When the question uses an underspecified referring expression such as `this story`, `this work`, `the story`, or `it`, do not match it to a passage merely because that passage contains the surface word `story`, `book`, or `movie`. First determine the titled work or entity the question is about, then use that work's own context block.
- For questions asking whether a story or work is or was made into or is a `book`, `movie`, `novel`, `film`, `play`, etc., return the direct medium/format label stated for that titled work. Do not infer a medium from a biography saying a person's story `inspired` a movie or opera; that is an adaptation mention, not a classification of the story itself.
- If the context gives a specific medium term for the work (e.g., `volume in the ... novel series`, `stand-alone novel`), prefer that exact term over a broader question word such as `book`.



## Ordinal, Rank, and Award Answer Units

- For questions asking for a numbered position (e.g., `What number of President ...?`, `What rank ...?`), return the ordinal form exactly as it appears in the direct evidence sentence, including the suffix (`st`, `nd`, `rd`, `th`) or spelled-out ordinal word. Do not convert it to a cardinal number.
- For award/prize/title questions, return the bare award proper title requested. If the evidence phrase is `[Awarding Body/Org] [Award Name] awards`, omit the awarding-body prefix and the plural head word `awards`; return only `[Award Name]`. Keep an organization prefix only when it is part of the award's own official title or the question explicitly asks for the full official award name.
- Before finalizing, check the question's requested unit and compare the candidate to the exact evidence phrase: keep required suffixes and remove only words outside the requested value, such as an awarding organization prefix or plural category word.


## Date and Title Disambiguation for Bridge Questions

- When a question supplies a year, date, ordinal, or title and multiple context blocks have similar names or releases, first select the block that explicitly matches the supplied date/year and type (album, song, publication, event, institution, etc.). Use that selected block as the bridge source; do not answer from a same-title block with a different date or medium.
- If the selected work/entity block names a related single, album, contributor, or organization, open that related entity's own context block and extract the requested property from there, preserving the exact wording used in the final evidence sentence.
- When the question gives a birth or death date plus another fact, first find the person block whose `(born ...)` or death date matches the supplied date, then confirm the other fact in the linked work or target block before answering.
- For questions asking who appeared on, wrote, directed, produced, or otherwise contributed to the selected work, return only the named contributor stated in the relevant evidence sentence from the selected work's own block.

## Resolving Indirect Descriptions and Relational Bridges

- When the question identifies an entity by a descriptive phrase, achievement, relationship, or other indirect wording rather than by name, locate the context block that connects that description to a named entity. Use that named entity as a bridge, then open its own context block for the requested property.
- For phrases such as `presented by`, `founded by`, `fronted by`, `made his debut in`, `since`, or `came ashore`, match the relation verb or phrase in the evidence to identify the intermediate entity. Do not return the descriptive phrase itself or answer from a bridge mention unless that same sentence directly states the requested value.
- Do not answer from a block that merely repeats surface wording such as `originally part of`, `later became`, or a descriptive label for a brand or facility. Extract the named entity referred to and verify the requested fact in that entity's own block.
- For product, brand, work, or place chains, identify the linked organization or entity from the source block, then read the linked entity's own block for the requested property. For example, if a product block names its producer and the question asks when that producer was founded, read the producer's own block for the founding year.
- When a context block describes an entity being used, mentioned, or connected `in conjunction with`, `alongside`, or as a counterpart to another named entity, treat that other entity as a bridge. Open that other entity's own context block for the requested attribute or classification, and take the answer from there rather than from the original mention block.
- When a work's or entity's own block gives a long list of names and the question asks for the list member who also satisfies an external descriptor, locate that descriptor in another supplied context block, identify the matching named entity, and return that list member exactly as written in the work/entity evidence sentence.
- Continue tracing bridge relationships until the requested property is directly and explicitly stated in the target's own block; do not return an intermediate bridge mention as the final answer unless that mention itself directly states the requested property.

## Person-Credit, Contributor, and Epithet Bridges

- For `who wrote/directed/hosted/created ...` questions, use the named work's own block to identify the credited person, then return the person's full canonical name from their own block, not a shorter form used in a bridge mention.
- If a singular author/creator question points to a work credited to multiple people, return the first named credited person unless the question explicitly asks for all.
- When the requested answer is a death year reached through an intermediate person, open that person's own block and return only the year from the stated death date.
- For questions that start from a work and ask about someone who wrote, foreworded, composed, or made a guest appearance on it, first read the work's own context block to identify the person's name. Then read that person's own block for the requested biographical property or quoted epithet/description.
- If the question asks what the person is often called, return the exact descriptive phrase from the person's own block without adding quotation marks, a sentence frame, or an explanation.
- If the question asks for the person's nationality, birth date, role, or another biographical attribute, find the explicit predicate in the person's own block and copy only the requested value exactly as stated, preserving diacritics and name forms.

## Institution, Ownership, Location, and Shared-Venue Bridges

- For workplace or employment statistic questions, use the person's block only to identify the current institution, then open that institution's own block for the requested enrollment, staffing, or other statistic.
- When a question asks what two targets share and one target's own block does not state the property, look for a linked venue, club, team, institution, or event in that block and open that linked target's block; the shared attribute is often stated there.
- For event-to-place bridges, a named club or venue in the place or event block can establish the shared sport, organization, or activity.
- If the question asks for an adjacent geographic feature, landmark, city, state, or similar location of an entity, and that entity's own block says it is part of, located by/at/near, or operated by another named entity, open that other entity's own block and return the requested feature exactly as stated there.
- For chained location questions such as museum/institution -> university/company -> park/landmark, follow each named entity to its own context block until reaching the requested feature. Return only the final named feature, not an intermediate organization or broader region.
- When the answer is a named park, building, landmark, city, state, region, or similar place, reuse the exact wording from the final evidence sentence and do not append additional venue or organization details unless the question asks for them.
- If the requested attribute or value is stated in a target block, return that exact wording or number rather than a more general term.

## Comparison and Classification Checks

- For non-yes/no `who/which died earlier/later` or `who was born earlier/later` questions, compare the parseable date or year in each entity's own block and return the selected entity's name exactly as written there.
- When a question asks `Between X and Y, which ...?`, `X and Y ... which one ...?`, or `X and Y are both ... which one ...?`, evaluate the requested property against each named candidate's own context block, then return the named candidate exactly as stated, not the property, family, genre, class, or type.
- For compound-subject yes/no questions such as `Do X and Y have P?` or `Are X and Y P?`, answer `yes` only when the context explicitly states the compared property for both named entities. If explicit support is present for only one entity, or one entity has a different or contradictory attribute, answer `no`.
- If the question asks which of two named candidates belongs to a specified family, genre, class, or type, use each candidate's own definitional or first-sentence evidence and return the candidate whose own block contains the requested label.
- For yes/no `Are X and Y both names of Z?` classification questions, answer `yes` only when the context supplies an explicit class marker for each target, such as genus/species/botanical name for plants or book/film/novel for works. Incidental mention of a target name is not enough.
- For numeric bridge answers such as `how many full-time students ...`, copy the number exactly from the target entity's own block, preserving internal comma formatting such as `2,300`.

## Multi-Condition Intersection and Direct-Evidence Stopping

- When a question requires two or more independently stated facts, scan the relevant context blocks separately and collect candidate entities for each condition. Return only the entity that satisfies all conditions.
- For questions asking which person or entity is associated with both A and B, compare the named people, teams, titles, or works in the two relevant blocks and return the shared entity exactly as stated. Do not answer from a block that matches only the surface wording or only one condition.
- When a date, capacity, or other numeric clue is given alongside a second fact, use the numeric clue to select the correct block, then confirm the second fact in that same block or in the linked entity's own block.
- When a question defines the answer by two or more independent conditions, first resolve one distinctive condition to obtain candidate entities, then verify every remaining condition in each candidate's own context block or directly linked block.
- If the two conditions are stated in different context blocks, verify the candidate name is present in both relevant evidence sentences before answering; a match on only one condition is insufficient.
- Once an explicit direct-evidence sentence satisfies every stated condition, stop scanning and return the requested short answer; do not keep searching for alternative named entities or infer a different entity from outside knowledge.

## Skill Invocation

- When the system prompt instructs you to invoke this skill, call the Skill tool directly and silently at the start of the task. Do not emit an announcement or planning text before the tool call.
- After the skill is loaded, proceed immediately to answer in the requested format without restating the question or adding commentary.
