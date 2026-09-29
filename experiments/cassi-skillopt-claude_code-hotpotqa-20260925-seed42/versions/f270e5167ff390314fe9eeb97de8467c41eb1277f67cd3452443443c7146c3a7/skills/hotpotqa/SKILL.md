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
- For location questions, return only the location name as stated, without appending associated venue or organization details unless the question asks for them.

## Procedure

1. Read the question carefully and determine the requested short-answer type (e.g., name, date, place, yes/no, description, comparison).
2. Identify the named entities, bridge clues, and the requested relation or comparison.
3. Treat all supplied context as a single searchable evidence base; locate the relevant paragraphs by title and scan for explicit dates, names, numbers, and relationships. If the question asks about an entity but that entity's own context block lacks the requested information, scan every other context block for mentions of that entity or closely related entities.
4. For multi-hop or bridge questions, use a fact from the first entity's paragraph to identify the intermediate entity, then read that entity's paragraph for the answer. Facts about a target entity may appear inside another entity's description, especially in comparisons or shared attributes. After resolving the final target entity, check its own context block for a complete evidence sentence that directly states the answer; if such a sentence is present, copy that whole sentence verbatim as the answer instead of reducing it to a shorter named entity or attribute taken from that sentence or from an earlier bridge mention.
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



## Bridge and Entity Disambiguation

- When several supplied context blocks share the same title or name, do not answer from the first matching title. Match additional clues in the question (co-occurring named entity, date, place, role, work type/medium, or property) and an explicit attribution phrase in a block such as `a three-act play by ...`, `a novel by ...`, or `a musical based on ...`, then use only the selected block.
- When the question identifies a person or entity indirectly through a named work, group, event, award, relationship, or descriptive phrase such as `a 2012 storm`, `an American brand of hotels`, or `the actor who played <role>`, first locate the context block that contains that description/title and reveals the named entity. If that block lists multiple candidates, use the list only to locate the intermediate entity, then open each candidate entity's own block to verify the requested property. Use the named entity as a bridge and return the candidate whose own block supports the property; do not return the descriptive phrase, persona, title, or a list-item block unless the question explicitly asks for that description or the Procedure's complete-sentence exception applies.
- When a named work, title, character, or entity is defined in its own context block by an identity phrase such as `whose alter-ego is ...` or `chronicles the adventures of ...`, and the question asks for the person or identity behind that title/persona, read that entity's own block and return the name introduced by the identifying phrase exactly as stated. Do not return the persona/title or a list-item block that merely mentions the work.
- For questions that supply a birth date or year plus another fact, first find the person block whose `(born ...)` parenthetical matches the supplied date, then confirm the other fact in that person's own block or the linked work block before answering.



## Multi-Condition and Relation Bridge Extraction

- For questions that identify the answer by two or more independently stated conditions, treat all supplied context blocks as a set of constraints. Scan separate blocks for each condition, collect candidate entities, and return only the entity that satisfies all conditions. Do not answer from a block that satisfies only one stated condition, even if its title or surface wording partially matches the question.
- When the question uses a relation verb such as `trained`, `graduated`, `included`, or `collected` that does not appear verbatim in the context, match the closest explicitly stated relationship in the source block (e.g., `studied at`, `became champion with`, `supervised the recordings of`, `essays ... collected in`), then confirm the target also satisfies any additional descriptor in the question from its own block.
- For a bridge question that starts from an attribute or achievement and asks which entity satisfies it, first find the entity whose own block states that attribute/achievement, then return the other named entity from the same direct-evidence sentence, preserving the exact wording, unless the Procedure's complete-sentence exception applies.
- For creator/work bridges, identify the creator from the work's own context block, then read the creator's block for the requested collection, oeuvre, or property.
- For `graduated from` or `studied at` questions, extract the institution exactly from the person's education sentence and verify the requested qualifier in that institution's own context block before returning the institution name; follow the educational-institution rule above for whether to keep or omit suffixes such as `University`, `College`, or `Business School`.
- For questions asking which team or organization a person was part of when they achieved something, use the achievement sentence in the person's own block and return the team/organization named there; do not substitute a team block that omits the person.
- When the requested answer is the object of a relation in the target entity's own block (e.g., parent company, subsidiary, league, state, location), return that object exactly as stated, preserving full canonical names and suffixes, unless the Procedure's complete-sentence exception applies.



## Specific Inspiration, Ownership, and Proximity Bridges

- When a question asks what artist, band, song, or work inspired or led to an album, film, or other creative work, prefer an explicit sentence that names a specific artist, group, or work in connection with the work's conception. Do not answer with a broad era or genre phrase when a specific named inspiration is present.
- For questions asking what park, city, or geographic feature an institution or museum is located by or near, and the institution's own block links it to a parent organization, open that parent organization's block and return the named geographic feature or unit exactly as stated there. Do not return the parent organization or a broader city when the question asks for the adjacent landmark or feature.
- For chained ownership, operation, or control questions, use the target entity phrase to identify the immediate operator/owner from the target's block, then read that intermediate entity's own block for the ultimate owner or controller. Preserve the exact canonical wording from the final evidence sentence.
- For a named person with a played role/character, locate the person's own context block and return the work title found in the same clause; confirm against the work's own context block only when the question asks for a property of that work.
