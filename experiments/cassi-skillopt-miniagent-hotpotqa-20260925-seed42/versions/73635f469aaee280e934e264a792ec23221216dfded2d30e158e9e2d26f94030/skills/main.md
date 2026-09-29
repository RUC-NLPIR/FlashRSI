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

- For person names, prefer the name span as written in the prose sentence that supplies the requested relationship. If that sentence uses a full formal name including middle names, copy that full form even if the passage heading or a later mention uses a shorter common name; do not use the heading as the answer span. Only prefer a short or common name when the answer-supplying sentence itself uses that short form, not merely because a heading or alias is shorter.
- For location, base, or venue answers, return the full place phrase exactly as written, including a comma-separated city, state, province, or country qualifier if it is part of the same source phrase (e.g., Airport, City). The rule against adding extra region/state qualifiers does not permit stripping a qualifier that is already part of the named answer.


## Answer Span Length Calibration

- Match the answer span to the question type: count questions return only the bare value; entity questions return the minimal entity; descriptive, title, or definition questions return the full relevant source phrase exactly as written.
- Do not collapse a full descriptive answer span into a shorter named entity, even if the shorter entity is semantically plausible; copy the exact phrase that the source uses to provide the requested attribute, definition, or relationship.

- For "what kind/type/sort of X" questions, return the exact class/kind phrase from the context that fills the answer slot. If the source gives only a bare modifier in that slot, return only that modifier. If the source supplies or defines a class/category term with its head noun, return that full category term instead of truncating it to the bare adjective; do not add a questioned noun the source does not use.



## Category Questions with Multiple Entities

- For questions that ask what category or type several entities share, return the singular category or class term exactly as the context defines it; do not pluralize or inflect it to match the question's plural wording.



## Answer Span Overrides for Question Type

- For count questions such as 'how many ...', return only the bare number word or numeral from the source. Do not append the counted noun or unit even if it appears next to the number in the context.
- For underspecified demonstrative or anaphoric subjects such as 'this story', 'this person', or 'this film', resolve the pronoun to the entity established by the question path or the passage that explicitly defines its type/class; do not let other passages that merely use the same common noun distract you.
- For medium/format/classification questions, return the explicit class or medium stated for that target entity in the connected passage, not a medium from another related or similarly worded story. Preserve the source's classification term rather than substituting a looser alternative from the question.
- When a longer source phrase conflicts with an answer-type constraint, the answer-type constraint wins: the answer should be a bare value for count questions and a class term for classification questions.



## Exact Span for Titles and Formal Names

- For questions asking for the title or name of a creative or serial work, copy the complete source phrase exactly as written, including any subtitle introduced by a colon or dash. Do not truncate to a shortened common name, heading, or initial-title form even if that appears in the context.
- For exact-match questions where the source contains multiple surface forms for the same entity, select the full-form source phrase from the sentence that directly supports the answer; do not shorten it to a plausible common name or heading.
- In particular, when a title and subtitle are introduced together in the first mention or definitional passage, return the full title including the subtitle and preserve the source's capitalization of the leading article.



## Award and Action Span Rules

- For "what award/honor/title did X win" questions, return the core award or title name from the source. If the source phrase is an attributive organization/sponsor + award construction, answer with the award title itself and do not copy an organizational prefix unless the question or source treats that prefix as part of the standalone award name.
- For "what notable act/achievement/feat did X do" questions, copy the full source clause or predicate phrase that states the act, including a leading frame such as "He is credited with ..." or "He is known for ..."; do not reduce it to a bare gerund phrase.
