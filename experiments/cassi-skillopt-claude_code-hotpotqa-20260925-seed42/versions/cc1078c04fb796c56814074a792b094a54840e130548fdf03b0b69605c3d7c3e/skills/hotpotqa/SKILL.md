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
- Before finalizing, compare the answer with the wording in the direct evidence sentence and, for bridge questions, with the most specific named entity's own context block. Exact-match grading may require context wording rather than synonyms: preserve middle names, pen-name/pseudonym cue values, and complete descriptive phrases; do not shorten a canonical name or drop words that are part of the evidence phrase.

- For organization, company, distributor, studio, label, or similar named entities, return the full canonical name exactly as stated in the direct evidence sentence, including suffixes such as `Films`, `Company`, `Corporation`, `Inc.`, or `Ltd.`. Do not shorten the target entity's name to the bare headword, even if a shorter form appears in another context block or in an intermediate bridge mention.
- For person questions, return the full canonical name from context, including first names and quoted nicknames, rather than a shorter or common version.
- For questions asking "who is/was X" or "what role does X have", return only the descriptive phrase from context that identifies the person, not a sentence containing the person's name.
- If a singular "who" question asks for one person but the context gives a compound phrase such as "produced by X and Y", return only the first named entity unless the question explicitly asks for all or multiple people.
- For location questions, return only the location name as stated, without appending associated venue or organization details unless the question asks for them.

## Procedure

1. Read the question carefully and determine the requested short-answer type (e.g., name, date, place, yes/no, description, comparison).
2. Identify the named entities, bridge clues, and the requested relation or comparison.
3. Treat all supplied context as a single searchable evidence base; locate the relevant paragraphs by title and scan for explicit dates, names, numbers, and relationships. If the question asks about an entity but that entity's own context block lacks the requested information, scan every other context block for mentions of that entity or closely related entities.
4. For multi-hop or bridge questions, use a fact from the first entity's paragraph to identify the intermediate entity, then read that entity's paragraph for the answer. Facts about a target entity may appear inside another entity's description, especially in comparisons or shared attributes.
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


## Most-Specific Block and Name Cues

- When a question names a specific work, person, or member and that entity has its own supplied context block, open that specific block before finalizing. Prefer its wording over a shorter mention in a containing series/group/work block or credit list.
- For bridge questions that resolve to a person, use the person's own context block as authoritative for name spelling. If its title/introductory sentence gives a full name with middle names before a parenthetical birth/death note, return that full form rather than a shorter first-last form used in a bridge mention.
- For questions asking what name an author uses or wrote under (`pen name`, `pseudonym`, `alias`, `as`), locate the explicit cue phrase such as `under his pen name of` and return the exact pen name that follows it. Do not replace it with the author's legal name or a work title, and do not omit part of the pen name when the cue phrase includes it.


## Skill Invocation

- When the system prompt instructs you to invoke this skill, call the Skill tool directly and silently at the start of the task before reading or answering. Do not emit visible planning text, an announcement (e.g., `I'll invoke the required skill first.`), or any explanatory lead-in before the Skill tool call.
- After the skill is loaded, proceed immediately with the requested short answer in the requested format, without restating the question or adding commentary.


## Bridge and Own-Block Resolution

- When a question starts from a named work, event, or person and asks for a property of a related entity, use the source block only to identify the related name, then open that related entity's own context block and take the requested value from an explicit evidence sentence there. Do not answer from the source block unless it directly states the requested property, and do not return an intermediate bridge mention unless that same sentence directly states the requested value.
- When a question identifies an intermediate entity through a paraphrase or descriptive relationship (e.g., `the event that closed down ...`, `the region where ...`, `the province with area ...`, `the administrative region whose capital is ...`, `the periodical that contained ...`, `the film role of ...`), first locate the context block that explicitly states that descriptive relationship and gives the intermediate entity's name. Use that block only to identify the named target, then open the target entity's own context block when the requested property is stated there.
- If the target is identified only descriptively (e.g., `the actor born <date>`, `the American professional football player`, `the singer who ...`, `the person who wrote ...`, `the actress who hosted ...`, or `the man who wrote ...`), locate the person/entity block that explicitly matches that descriptor, then answer the final property from that block, not from the source block that merely mentions the descriptor.
- For relational words such as `prequel`, `sequel`, `lead single`, `second album`, `featured on`, `starring`, `credited as`, `recorded for`, or `also stars`, treat the phrase after the relation as the linked title/name. Read that linked title's or person's own block for the requested date, character, role, or other property.
- In film/work questions asking for a character played by a named person in a work that also features a described other person, locate the work block that contains both the named person and the described other person, then return the role/character from that same block exactly as written.
- Prefer the target entity's own block when it states the requested property; use another entity's description only when the target block lacks the property or the question explicitly points to that other description.
- If the bridge mention uses a shorter name, title, or label, still open the named entity's own block and use its direct evidence wording for the final answer.
- For questions that supply both a named source and a numeric/descriptive clue, match the clue against all supplied context blocks. If a block explicitly contains the matching descriptor, use it even when the entity's own block does not restate that clue.
- When the final answer is a named title, treaty, periodical, organization, or location, copy the exact wording from the direct evidence sentence, including leading articles, subtitles, year suffixes, and canonical full names where present.
- If multiple blocks match the question's surface words, use all supplied qualifiers such as year, medium, rank, jurisdiction, or relationship to select the matching block, and ignore blocks that only repeat a shared word.
