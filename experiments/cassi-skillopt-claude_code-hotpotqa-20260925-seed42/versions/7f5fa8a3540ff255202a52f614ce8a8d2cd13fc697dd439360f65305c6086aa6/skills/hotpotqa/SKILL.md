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
- For person questions, return the full canonical name from context, including first names and quoted nicknames, rather than a shorter or common version.
- For questions asking "who is/was X" or "what role does X have", return only the descriptive phrase from context that identifies the person, not a sentence containing the person's name.
- If a singular "who" question asks for one person but the context gives a compound phrase such as "produced by X and Y", return only the first named entity unless the question explicitly asks for all or multiple people.
- For location, venue, base, airport, station, park, or place questions, return the complete multi-part location/base phrase exactly as written in the direct evidence sentence. Keep comma-separated city, state/region, or country qualifiers and named-facility-plus-city forms when they are part of the stated location phrase (e.g., return `[Named Facility], [City]`, not only `[Named Facility]`). A following geographic qualifier is part of the location phrase, not an associated venue or organization detail; keep it. Do not truncate a multi-part location/base name to only the first named place, facility, code, or a shorter label used in the question. Do not append associated venue or organization details unless the question asks for them.

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


## Work-to-Person and Work-to-Work Bridge Resolution

- When a question names a source work/event and asks for a property of a related named entity (e.g., the artist/creator of a song, the host of an event, the target of a prequel/sequel, or the album on which a work appears), use the source block only to identify the related name. Then open that related entity's own context block and extract the requested property from there.
- Do not answer from a bridge mention in the source block if it does not directly state the requested property. A shorter or partial name in a bridge mention is not a substitute for the direct evidence in the target entity's own block.
- For relation terms such as `prequel`, `sequel`, `second single`, `hosted by`, or `from ... album`, first resolve the named work/person that follows the relation, then read that named target's block for the final answer.


## Indirect, Descriptive, and Member Matching

- When a question identifies the target only by a descriptive relationship (`the actor/actress who hosted ...`, `the singer born on ...`, `which executive worked with ...`), first locate the block that connects that description to a named entity. Then open that named entity's own context block for the answer.
- If the question asks for a property of that described entity (birth date/year, name, origin, etc.), return the property from the target entity's own block, not from the bridging description unless that same block directly states the property.
- If the question lists several names/items and asks which one matches a later description, scan the individual named entity/item blocks for the matching description and return the matching named entity/item exactly, not the description itself.


## Skill Invocation

- When the system prompt instructs you to invoke this skill, call the Skill tool directly and silently at the start of the task without announcing the call or emitting planning text. Do not emit an announcement or planning text before the tool call.
- After the skill is loaded, proceed immediately to answer in the requested format.
