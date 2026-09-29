# Question Answering Skill

## Learned Rules

- For short-answer and exact-match questions, copy the answer phrase exactly from the context; do not paraphrase, abbreviate, broaden, narrow, or normalize it even if the meaning seems equivalent.
- Return only the minimal requested entity. Do not append extra qualifiers such as region, state, province, or additional conjoined entities unless the question explicitly asks for them.
- For singular "who" or "which person/entity" questions, return a single entity. If the context gives a conjoined list, return the first/primary named entity, not the whole list, unless the question asks for all.
- For person-answer questions, use the exact name form from the passage that directly supplies the answer. If that passage gives a full formal name (including middle names or quoted nicknames), copy that full form; if it uses a shorter or common name, return that exact shorter form instead of expanding it from another passage.
- For questions asking what sport, activity, or role a person is associated with, return the exact noun phrase used to define them in the context, not a generalized sport or category name.
- Preserve the exact surface form of the answer as it appears in the relevant source context. Avoid normalizing number words to digits or digits to number words unless the source uses that form.
- For count questions, return the count using the same wording or format as the supporting context.
- For ordinal or position questions, answer with the full ordinal phrase including the definite article, such as "the first" or "the thirteenth", rather than numeric abbreviations like "1st" or "13th".
- Search the whole context for the answer, not only the paragraph where a named entity's heading appears. For measurement/location questions such as "How high is X" or "How far is X", also search connected passages for a related measurement when the named entity's own passage lacks one; do not answer "not stated" if the context provides a connected measurement.
- Prefer short extracted answers containing the numerical value and unit. Preserve capitalization, wording, and punctuation exactly as in the context. Before finalizing, compare your answer against the source phrase; if it is semantically equivalent but not textually identical, prefer the source wording.

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

- Match the answer span to the question type: count questions return only the bare value; entity questions return the minimal entity; descriptive, title, or definition questions return the full relevant source phrase exactly as written. For "what notable act/achievement/feat did X do" or similar action questions, return the full predicate phrase or source clause that states the act, including a leading frame such as "He is credited with ..." or "He is known for ..." and any trailing purpose/result phrase; do not reduce it to a bare gerund or main verb phrase.
- Do not collapse a full descriptive answer span into a shorter named entity, even if the shorter entity is semantically plausible; copy the exact phrase that the source uses to provide the requested attribute, definition, or relationship.

- For "what kind/type/sort of X" questions, return only the exact modifier or attribute phrase from the context that fills the kind/type slot; do not append the questioned noun (e.g., return the adjective phrase, not the adjective phrase plus the noun).



## Category Questions with Multiple Entities

- For questions that ask what category or type several entities share, return the singular category or class term exactly as the context defines it; do not pluralize or inflect it to match the question's plural wording.



## Answer Span Overrides for Question Type

- For count questions such as 'how many ...', return only the bare number word or numeral from the source. Do not append the counted noun or unit even if it appears next to the number in the context.
- For underspecified demonstrative or anaphoric subjects such as 'this story', 'this person', or 'this film', resolve the pronoun to the entity established by the question path or the passage that explicitly defines its type/class; do not let other passages that merely use the same common noun distract you.
- For medium/format/classification questions, return the explicit class or medium stated for that target entity in the connected passage, not a medium from another related or similarly worded story. Preserve the source's classification term rather than substituting a looser alternative from the question.
- When a longer source phrase conflicts with an answer-type constraint, the answer-type constraint wins: the answer should be a bare value for count questions and a class term for classification questions.



## Geographic and Jurisdiction Answer Selection

- For questions asking what country, state, or jurisdiction a place is part of, use the passage that explicitly states the current or official political/administrative membership of that exact place. Do not use a historical, descriptive, or broad geographic label from the entity's own passage when a connected passage gives a more specific present-day jurisdiction.
- Prefer the present-day political entity that the source explicitly associates with the queried region over a broader historical or island-level name that happens to appear next to the entity's name.
- For multi-hop location/country questions, treat the passage about the larger region (county, province, district, etc.) as the target membership source. The entity passage is useful for identifying which region is meant, not necessarily for extracting the current country label.



## Answer Span Overrides for Phrase-Wrapped Answers

- For "where" or "location/venue" questions, return the bare named place or venue. Strip a leading spatial preposition such as "on", "in", "at", or "from" and any grammatical article from the source phrase unless the preposition or article is part of a proper name or the question explicitly asks for a complete prepositional phrase.
- For "what style/kind/type/genre of film/medium" classification questions, return the core genre or class term from the source, not a longer descriptive compound that adds a non-genre modifier before the class term. In particular, omit seasonal, holiday, and audience descriptors unless the full compound is itself an established genre/class label or the question explicitly asks for the full subgenre.
- When the source phrase contains material outside the requested answer-type slot, the answer-type constraint wins over preserving the full source phrase.



## Descriptive, Role-Based, and Definitional Bridge Resolution

- When the subject is a descriptive role, relationship, alias, informal synonym, or ownership phrase rather than a proper name, first match the full description to the passage that directly defines it; treat the named entity defined there as the bridge target, then move to that entity's own passage for the requested attribute.
- Use the passage whose phrasing most closely repeats the question's distinctive description, even when other passages share some terms. Ignore passages that share only a descriptive word or category but do not satisfy the complete bridge description.
- For role/relationship chains such as 'the singer who released', 'the director of X', 'the airline division of Y', or nested descriptions, trace the chain step by step from anchor to linked entity, extracting each link from the passage that names or defines it.
- For work-by-creator questions such as 'What film by the director of X is about Y?', resolve the creator from the anchor work's passage, then search other passages for works attributed to that creator and select the work whose passage explicitly matches the requested subject. Return the work title exactly as written in the matching passage.
- For definitional or paraphrased bridge descriptions, find the passage whose defining sentence matches the description and use its heading or canonical subject as the bridge entity before following the relation.
- When a name or title is ambiguous across passages, choose the passage matching the question's descriptive constraints before following the relation; do not settle on a same-named distractor that fails those constraints.
- When a passage lists multiple people or associated entities and the question points to one via a relative clause or qualifier, use the qualifier to select the matching entity from the list, then go to that entity's separate passage for the requested attribute.
- When an entity is described as located in, performed at, or belonging to a larger parent entity, use that qualifier to find the parent entity's passage and extract the requested attribute from it.
- For fill-in-the-blank shared-attribute questions such as 'X and Y were both in favor of ____', extract the common property that both connected passages state, and return only the bare shared term exactly as it appears.
