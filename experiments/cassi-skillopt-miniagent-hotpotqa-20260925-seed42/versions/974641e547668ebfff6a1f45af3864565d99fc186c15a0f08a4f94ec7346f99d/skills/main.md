# Question Answering Skill

## Learned Rules

- For short-answer and exact-match questions, copy the answer phrase exactly from the context; do not paraphrase, abbreviate, broaden, narrow, or normalize it even if the meaning seems equivalent.
- Return only the minimal requested entity. Do not append extra qualifiers such as region, state, province, or additional conjoined entities unless the question explicitly asks for them.
- For singular "who" or "which person/entity" questions, return a single entity. If the context gives a conjoined list, return the first/primary named entity, not the whole list, unless the question asks for all.
- For person-answer questions, use the exact name form from the passage that directly supplies the answer. If that passage gives a full formal name (including middle names or quoted nicknames), copy that full form; if it uses a shorter or common name, return that exact shorter form instead of expanding it from another passage. For birth-date or age comparison questions (e.g., "Who was born later/earlier?"), the candidate's own biographical passage that states the birth date is the passage that directly supplies the answer; copy the full formal name span directly attached to that date, including middle names and quoted nicknames, rather than a shorter heading or bridge mention.
- For questions asking what sport, activity, or role a person is associated with, return the exact noun phrase used to define them in the context, not a generalized sport or category name.
- Preserve the exact surface form of the answer as it appears in the relevant source context. Avoid normalizing number words to digits or digits to number words unless the source uses that form.
- For count questions, return the count using the same wording or format as the supporting context.
- For ordinal or position questions, answer with the full ordinal phrase including the definite article, such as "the first" or "the thirteenth", rather than numeric abbreviations like "1st" or "13th".
- Search the whole context for the answer, not only the paragraph where a named entity's heading appears. For measurement/location questions such as "How high is X" or "How far is X", also search connected passages for a related measurement when the named entity's own passage lacks one; do not answer "not stated" if the context provides a connected measurement.
- For measurement, height, distance, and location questions such as "How high is X?" or "How far is X?", copy the full source phrase or sentence that states the measurement, exactly as written. Do not reduce it to a bare number and unit unless the context itself presents the measurement as a standalone value-and-unit phrase and the question requests only that value. Before finalizing, compare the answer against the source sentence; if a full sentence contains the requested measurement, prefer copying that full sentence over a semantically equivalent shorter span.

## Multi-hop QA over supplied context

Use only the supplied context and return only the requested short answer.

1. Parse the question for the starting entity, requested attribute/relationship, expected answer type, and explicit constraints. Resolve ambiguous names using full titles or qualifiers.
2. Locate the context passage(s) that refer to that entity. Avoid similarly named distractors and irrelevant passages that share terms but do not complete the answer chain.
3. For bridge questions, follow the relational clue from the first passage to the next (e.g., "played by", "owned by", "operated by", "located in", "awarded to", parenthetical role descriptions), then extract the requested answer from the connected passage.
4. For comparison questions, extract the same attribute/category/property for each candidate (e.g., type/class/court/industry/profession). Use only explicitly stated facts: answer yes only when the context explicitly says both candidates share it; otherwise answer no. For which-has-more/list/count comparisons, use the explicitly stated counts, lists, or members.
5. Verify that the final answer is directly supported by the connected context passage.
6. Return only the requested short answer (name, date, title, yes/no, or brief phrase). Use exact context wording for dates and proper nouns, and do not add explanation, full sentences, or markdown unless asked.


## Named Entity Span Boundaries

- For person names, prefer the name span as written in the passage that establishes the requested relationship. A short or common name used in the answering passage is the answer; do not replace it with a longer formal name from a separate introductory passage or heading.
- For location, base, or venue answers, return the full place phrase exactly as written, including a comma-separated city, state, province, or country qualifier if it is part of the same source phrase (e.g., Airport, City). The rule against adding extra region/state qualifiers does not permit stripping a qualifier that is already part of the named answer.


## Answer Span Length Calibration

- Match the answer span to the question type: count questions return only the bare value; entity questions return the minimal entity; descriptive, title, or definition questions return the full relevant source phrase exactly as written.
- Do not collapse a full descriptive answer span into a shorter named entity, even if the shorter entity is semantically plausible; copy the exact phrase that the source uses to provide the requested attribute, definition, or relationship.

- For "what kind/type/sort/category of X" questions, return the canonical class/category term that fills the question slot. If a dedicated category/definition passage gives a standard class label matching the question head, prefer that exact class label over a longer self-description in the target entity's own passage, even when the longer phrase is in the target's defining sentence. When the question supplies the head noun and the standard class term is premodifier plus head noun, return that full canonical class term, not just the premodifier. If the context supplies only a bare modifier/attribute phrase, return only that modifier. If the context supplies a distinct class label with its own head noun, return the full class label instead of truncating it to the premodifier. Do not append the questioned noun when it merely repeats the question, but do not strip a head noun that is part of the canonical class term.



## Category Questions with Multiple Entities

- For questions that ask what category or type several entities share, return the singular category or class term exactly as the context defines it; do not pluralize or inflect it to match the question's plural wording.



## Answer Span Overrides for Question Type

- For count questions such as 'how many ...', return only the bare number word or numeral from the source. Do not append the counted noun or unit even if it appears next to the number in the context.
- For underspecified demonstrative or anaphoric subjects such as 'this story', 'this person', or 'this film', resolve the pronoun to the entity established by the question path or the passage that explicitly defines its type/class; do not let other passages that merely use the same common noun distract you.
- For medium/format/classification questions, return the explicit class or medium stated for that target entity in the connected passage, not a medium from another related or similarly worded story. Preserve the source's classification term rather than substituting a looser alternative from the question.
- When a longer source phrase conflicts with an answer-type constraint, the answer-type constraint wins: the answer should be a bare value for count questions and a class term for classification questions.



## Award and Honor Span Selection

- For "what award/honor/prize did X win/receive" questions, return the standalone award title itself. Do not copy an organizational/agency/sponsor prefix that merely modifies the award unless the source treats that prefix as part of the official award name (e.g., "Academy Award" keeps "Academy"; an organization's "Coach of the Year" award returns "Coach of the Year").
- When the source phrase has the pattern "ORG + Award Name" and the same sentence or context elsewhere treats the Award Name as an independent award title, return the standalone Award Name.
- This award-title constraint overrides the general exact-source-wording preference when the source phrase embeds an organizational prefix.



## Multi-hop Bridge and Candidate Resolution

- For "Between X and Y, which ... has property P?" or similar two-option selection questions, check each option's own context passage for an explicit statement of P. Return only the option whose passage directly satisfies the condition, preserving its title or name exactly as written there. Do not answer yes/no unless the question asks that. When comparing more than two named candidates, evaluate each against its own defining passage and return the one whose passage explicitly states the requested property.
- Do not let related passages about species, subtopics, works, or members of the candidate's category override the candidate's own defining statement when determining which candidate satisfies the requested property.
- When the start entity is identified by a descriptive qualifier, property, or characteristic rather than by a proper name, first use that qualifier to select the intended entity, then move to the connected passage that states the relation and extract the requested answer from the sentence that directly supports it. If a shared-association passage names multiple people, select the person whose own passage explicitly supplies the requested attribute.
- When the question includes an explicit identifying property as a constraint (e.g., a capacity, date, distance, or count), use that exact value to identify the correct candidate among multiple same-type passages; if several passages mention the same attribute label, take the value from the resolved target passage, not from a distractor of the same type.
- For quoted or underspecified titles, songs, or aliases used as bridge clues, locate the passage that states the relation and resolve it to the linked target entity; then retrieve the requested attribute from that target entity's passage.
- For nested multi-hop questions, trace the chain in order: resolve the first entity from its attributes, use its passage to find the linked work/entity, then read that linked entity's passage if needed before extracting the final answer. Treat relational phrases and intermediate descriptors as bridges even when they are not proper names (e.g., 'conducted the premiere of', 'inspired by', 'based on', 'directed/starred in', 'previously', 'originally part of'), and continue following the explicit relation chain until the requested attribute is reached; do not stop after one hop.
- Answer only the final requested slot. Do not return an intermediate entity or the anchor entity when the question asks for the last relation, sibling, parent, child, date, or attribute in the chain. When a relative clause identifies an entity, resolve the relative clause to that intermediate entity via the linking passage, then open the intermediate entity's passage for the requested attribute.
- For questions asking what sport, activity, role, category, class, country, state, or larger parent entity two or more named entities share, return the shared class/activity or official parent phrase exactly as the context defines it, as a singular category/class term even if the question uses plural wording or a broader synonym. For role-description questions, locate the passage that explicitly mentions both the role and the association, then return that passage's subject as the answer.
- For shared-entity and nested-role overlap bridges, identify the passage that names the overlap. If the question asks which person appears in both entities/works, return the common person. If it asks for the role/character played by A in a work that also involves B, find the work passage mentioning both and extract A's role exactly from that passage.
- For questions asking what an object or place is locally called, known as, or referred to as, return the introduced label exactly as written rather than substituting the generic object name or category.
- When a passage refers to an entity by an abbreviation, acronym, degree initials, or short label and the question asks about that entity type, first locate the passage whose heading or defining sentence provides the full canonical term; then answer from that canonical term's passage. Use the context around the abbreviation to choose among possible expansions, and do not treat the abbreviation itself as the final answer unless the question asks for it.
- If a passage says an entity was 'originally part of', 'located on', 'formerly', 'later became', or 'was created from' another named entity, treat that as a cross-reference to the other entity's passage. Resolve indirect descriptions through the explicit cross-reference, then extract the requested date, location, builder, or other property from the passage that defines the cross-referenced entity. Preserve hyphenated date ranges and source formatting exactly.



## Who-Was Alias/Description Questions

- For questions like "Who was [person]?" or "Who is [person]?" where the named target is a stage name, pen name, alias, or popularly known name, and the relevant context introduces them with a pattern such as "[Birth/legal name], more popularly known as [Alias], is/was a [defining descriptor]", return the exact defining descriptor phrase that follows "is/was a" (e.g., nationality, role, occupation, or class), not the birth/legal name or the alias itself.
- If the question explicitly asks for the person's real name, birth name, legal name, or full name, then return the name span instead.
- Do not apply this descriptive answer override when the question type expects a bare named entity (e.g., "Who was the director of X?", "Who founded X?"). In those cases continue returning the person name according to the person-answer rules.



## Subsidiary, Division, and Organizational Unit Bridges

- For questions asking about an attribute of a subsidiary, division, brand, or other named operating unit, treat a parent-entity passage that names the X division, Y or its X unit, Y as a cross-reference to the named unit's own passage. Open that unit's dedicated passage and extract the requested attribute (base, crew base, headquarters, location, date, etc.) from there, exactly as written.
- Do not answer from the parent passage if it only names the unit but lacks the requested property. The unit's own passage is authoritative for its own facts.
- For base/crew/headquarters location questions, return the full place phrase exactly as written in the unit passage, including a comma-separated city and state/province or airport name when the source presents it as the same phrase.

## Creator, Family, and Descriptive-Clue Bridges

- When the question identifies an entity through a creator/director/author or a family relation such as the director of X, or the father/mother/son/daughter of X, first resolve the intermediate person from the named entity's passage. Then open the candidate work or person passage that explicitly connects that intermediate to the requested descriptor or topic.
- For questions like what work by the creator of X is about Y, select the work whose own passage mentions both the creator and the subject Y, and return that work title exactly as written. Do not answer with a thematically related work that only shares the subject.
- For a chain such as X was the father of the Y who had property P; what is P?, resolve Y in X's passage, then read Y's own passage for P. Return the publication, role, title, or entity from Y's passage exactly as written, not an intermediate.

## Temporal Constraint and Person-to-Place Bridges

- When a question includes a temporal constraint such as during the last year of X's service/term, the year X ended, after X left, or while X held office, read X's own passage for the start/end date or period that defines the constraint. Use that date or period to select the connected event or entity passage, then extract the answer from the sentence that directly supports that connection.
- When another passage says a person or entity served in, worked in, studied at, lived in, or was based in a place, treat the place mention as a bridge to that place's dedicated passage. Extract the requested status, capital, population, location, or other fact from the place passage exactly as written.
- This expands the existing cross-reference rule: the linked entity's own passage is authoritative for the final attribute, whether the pointer comes from a parent, child, work, event, or person passage.

## Event-Venue Bridge Resolution

- For questions where an event is used as an intermediate pointer to a venue or host organization (e.g., 'who is the head teacher of the school where [event] is held?' or 'what is the [attribute] of the place where [event] takes place?'), first locate the event's own passage and identify the explicit location/host phrase such as 'held at', 'takes place at/in', or 'held in'.
- Then open the named venue's or host organization's own passage and extract the requested role, official, or attribute exactly as written there. Do not answer from the event passage itself or substitute a different entity that merely shares a word with the venue.

## Year-Specific Award and Festival Bridge

- When a question names a time-stamped or numbered award, prize, or festival edition, first resolve that exact edition's passage and identify its winner, honoree, recipient, or associated work there. Do not use the general award page, another edition, or a different year's winner.
- If the question then asks for an attribute of that winner or associated person/work, open the winner's or associated entity's own passage and extract the requested attribute from that passage.
- Preserve the attribute exactly as written in that passage, including digits versus number words and full date or title formatting.

## Multi-Constraint Intersection Bridge

- When a question asks for an entity satisfying more than one explicit condition from different passages, keep every condition active and require the final candidate to satisfy all of them. First collect candidates satisfying the anchor relation (collaboration, membership, nomination, award, etc.), then check each candidate's own dedicated passage for the remaining condition.
- Do not accept an entity that satisfies only one condition, and do not let a nearby passage that shares a keyword but lacks the required condition override the candidate's own passage.
- For nested conditions such as a work tied to a person who won a different award, resolve the inner person/condition first, then open that person's passage to identify the requested outer work or title.

## Relative-Clause and Publication Resolution

- When a question identifies a named publication, magazine, venue, organization, or work by a relative clause about an associated author, contributor, or work (e.g., 'which has published works from authors such as...'), do not extract the requested property from the associated person's passage.
- Instead, locate the named publication's, venue's, organization's, or work's own defining passage and read the requested founding date, format, location, or other property there.
- This keeps indirect descriptive clauses from overriding the target entity's own explicit characteristics.

## Organizational Partner and Licensor Bridges

- Treat relation phrases such as 'partnered with', 'in partnership with', 'licensed by', 'licensed from', 'published by', 'developed by', 'owned by', and 'subsidiary of' as bridge clues to the related organization's own passage. Open the related organization's passage and extract the requested location, base, or other attribute exactly as written there.
- For questions asking where a company's partner or licensor is based, do not answer from the project or product passage if it only names the relation; use the partner's dedicated passage for its base or location.

## Measurement Attribute and Unit Mismatch

- For questions asking how much area, space, or size a structure covers, search the whole context for the target entity's explicitly stated measurement, even when the source labels it differently (for example, volume, floor area, capacity, or height) or when the measurement appears in a related entity's passage.
- Do not reject a measurement merely because the question uses a different dimension word such as 'area' while the context states 'volume'. Prefer the exact source measurement phrase and unit, including value ranges with units, rather than answering 'not stated'.
- This whole-context measurement rule extends the existing measurement guidance and does not override bare count/date question behavior.

## Qualitative Scope and Reach Comparisons

- For comparison questions phrased with vague comparatives such as 'which operates more widely/broadly', derive the comparison from each candidate's own defining passage: global, multinational, worldwide, international, or multi-country wording beats local, single-city, state, or regional wording. Return only the candidate whose passage explicitly states the broader geographic or operational scope.
- If one candidate's passage limits its operations to a specific city or region while the other describes global or multinational operations, choose the latter. Do not answer yes/no. Preserve the selected entity name exactly as written in its own passage.

## Same-Name Candidate Disambiguation

- When a question uses a name shared by multiple context passages, select the passage that explicitly mentions the unique associated work, role, event, or relation supplied by the question. Do not choose a same-name passage merely because it shares the surface name.
- Once the correct entity is selected via the question-specific association, follow the bridge relation from that passage to the connected passage and return the requested final attribute, using exact source wording.

## Date Component Extraction

- For questions asking what year, month, or day an event occurred or a person was born, return only the requested date component exactly as written in the source. For example, for 'what year was X born?', return only the year from the full source date, not the complete 'born Month Day, Year' phrase.
- Do not expand a year answer into a full date, and do not return the full date when the question asks only for a component such as 'year' or 'day'.

## Location and Jurisdiction Span Granularity

- For questions that ask what county, state/province, country, town, or other administrative jurisdiction an entity is in or part of, return only the requested jurisdiction phrase exactly as written from the relevant place or administration passage.
- Do not include a full city-plus-region location phrase and do not append higher-level qualifiers when the question asks for one specific jurisdiction. This granularity rule overrides the general full-place-phrase preference when the question explicitly names the administrative unit being requested.
- For open location questions such as 'Where is X located?', continue to return the full source location phrase exactly as written.

## Requirement and Process Span Selection

- For questions that ask what a named degree, program, qualification, or similar category typically requires or includes for completion, trace to the passage that defines that specific degree, program, or qualification and copy the exact source phrase stating the requirement, such as a gerund phrase like 'writing a thesis'.
- Do not reduce the process phrase to a bare noun or change its form, and do not take an incidental 'typically requires' statement from an unrelated passage that happens to use similar wording.

## Count, Rate, and Member-List Comparisons

- For questions that compare which of two or more named entities has more members, parts, issues per year, or another countable property, evaluate each named entity only against its own defining passage. Use explicit count phrases, member lists, or conventional size/frequency labels stated there for that entity.
- Resolve conventional group-size and frequency terms to counts/rates only when the passage itself uses that term for the target entity: 'trio' = 3 members, 'quartet' = 4, 'quarterly' = 4 issues per year, 'monthly' = 12 issues per year. Do not infer a count from unrelated passages that merely mention the entity or similar names.
- Return only the candidate name that satisfies the comparison, copied exactly as written in that candidate's own defining passage. Do not append the count, unit, or explanation.

## Pointer and Former-Name Relations

- Treat departure, origin, rebranding, replacement, and former-name phrases such as 'after leaving', 'originated after', 'originally known as', 'formerly known as', 'changed their name to', and 'replaced' as bridge cross-references. Identify the named prior, original, rebranded, replacement, or parent entity from the phrase that directly states the relation.
- If the requested attribute is that cross-referenced entity's own property (for example, its name, date, or classification), open that entity's own passage and extract the property exactly as written there. If the question asks what entity was left, replaced, or originally named, return the specific entity/name from the sentence stating that relation rather than the current title or a broader category.
- This extends the existing cross-reference rule for 'originally part of', 'located on', 'formerly', 'later became', or 'was created from' without replacing it.
