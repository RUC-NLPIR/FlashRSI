# Question Answering Skill

## Learned Rules

- For short-answer and exact-match questions, copy the answer phrase exactly from the context; do not paraphrase, abbreviate, broaden, narrow, or normalize it even if the meaning seems equivalent.
- Return only the minimal requested entity. Do not append extra qualifiers such as region, state, province, or additional conjoined entities unless the question explicitly asks for them.
- For singular "who" or "which person/entity" questions, return a single entity. If the context gives a conjoined list, return the first/primary named entity, not the whole list, unless the question asks for all.
- For person-answer questions, first resolve which person satisfies the question. When the question identifies the person by a biographical/relational descriptor, nationality, role, group membership, or date comparison (e.g., "who was part of", "who served as", "who was born", "who led", or born earlier/later), use the full name span from the dedicated identity-defining passage or sentence that states that descriptor, role, nationality, or birth date, copying it exactly, including middle names and quoted nicknames. For born earlier/later comparisons, compare the birth dates in each person's own identity-defining passage and return the selected person's full formal name exactly as written there. Do not substitute a shorter common mention from the bridge, work, list, or heading passage that merely supplies the final relation; the fuller identity-establishing name form has priority. If no such identity-defining passage exists, use the exact name form from the passage that directly supplies the answer, without expanding or shortening it.
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

- For person names, prefer the name span as written in the dedicated person-defining or identity-establishing sentence that satisfies the question's requested descriptor, role, nationality, group membership, or date comparison. If that sentence gives a full formal name, including middle names or quoted nicknames, copy that full form even when other bridge, work, list, or heading passages mention a shorter common name. Do not let a short or common name used in the answering bridge passage or a heading override the fuller name from a separate identity passage. Use the shorter form only when the identity-defining sentence itself uses it, or when the context contains no fuller formal name.
- For location, base, or venue answers, return the full place phrase exactly as written, including a comma-separated city, state, province, or country qualifier if it is part of the same source phrase (e.g., Airport, City). The rule against adding extra region/state qualifiers does not permit stripping a qualifier that is already part of the named answer.


## Answer Span Length Calibration

- Match the answer span to the question type: count questions return only the bare value; entity questions return the minimal entity; descriptive, title, or definition questions return the full relevant source phrase exactly as written.
- Do not collapse a full descriptive answer span into a shorter named entity, even if the shorter entity is semantically plausible; copy the exact phrase that the source uses to provide the requested attribute, definition, or relationship.

- For "what kind/type/sort/genre/style/medium/category of X" questions, first isolate the slot that X names. If X is already named in the question as a plain noun-phrase head (e.g., music, films, band, books, car), return only the bare modifier/attribute/class label that fills that slot, exactly as written; do not append the source noun phrase's head when it merely repeats the question's head noun, and do not copy a plural medium noun from the source. For genre/category questions, answer with the genre or category label alone exactly as used in the source, not the full source noun phrase. If the context supplies only a bare modifier or attribute phrase, return only that modifier. If the context supplies a distinct class label with its own head noun that is not simply the questioned noun (e.g., a canonical noun-phrase category term), return that full class label instead of truncating it to the premodifier. Keep the head noun only when it differs from the questioned noun and is part of a canonical class/category term in the source, or when the question explicitly asks for the full compound/subgenre. Do not append the questioned noun when it merely repeats the question, and do not strip a head noun that is part of a canonical class term.



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
- Treat locative, membership, departure/origin, and relationship phrases such as 'located in/at/on', 'found in/at', 'based in/at', 'part of', 'after leaving', 'originated after', 'originally part of', 'formerly', 'later became', 'was created from', or 'mentioned in conjunction with'/'used in conjunction with' another named entity as cross-references to that other entity's passage. Resolve indirect descriptions through the explicit cross-reference. When a child passage gives only a pointer and the connected parent/related entity's own passage directly states the requested date, classification, location, builder, or other property, extract the answer from that connected passage rather than from the pointer phrase itself. For example, for a chain such as 'located in an amusement park that opened in which year', identify the named parent from the child's location phrase, then take the requested attribute from the parent's defining passage exactly as written. Preserve hyphenated date ranges and source formatting exactly.
