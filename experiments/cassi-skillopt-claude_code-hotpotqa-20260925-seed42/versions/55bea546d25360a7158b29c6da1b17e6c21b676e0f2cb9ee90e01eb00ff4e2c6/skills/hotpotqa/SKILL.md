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
- For person questions, return the full canonical name from the context passage that directly identifies or answers the target person, including first names, middle names, and quoted nicknames as stated there. If the person's own context block gives a fuller legal name while another block or a bridging mention uses a shorter or common form, use the fuller form from the person's own block; do not shorten it to the form used only in cross-references.
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
- If a term is ambiguous or multiple supplied context blocks share the same name, select the paragraph whose relationships and co-occurring named entities match the question. Use the question's additional clues (profession, role, work, year, location, organization, or associated person) to disambiguate before applying bridge facts or returning an answer.
- If several context blocks share a name/title, do not settle by title alone; list the candidate blocks and match the named entity or distinguishing attribute present in the question, then answer from the block that contains that companion clue.


## Classification Answer Form

- For classification questions such as `What are X and Y?` or other plural question phrasing, return the singular category noun that the context uses to define each item, not a pluralized form. If the context says each item `is a novel`, answer `novel`, not `novels`, even when the question uses a plural verb such as `are`.


## Resolving Anaphoric and Medium Questions

- When the question uses an underspecified referring expression such as `this story`, `this work`, `the story`, or `it`, do not match it to a passage merely because that passage contains the surface word `story`, `book`, or `movie`. First determine the titled work or entity the question is about, then use that work's own context block.
- For questions asking whether a story or work is or was made into or is a `book`, `movie`, `novel`, `film`, `play`, etc., return the direct medium/format label stated for that titled work. Do not infer a medium from a biography saying a person's story `inspired` a movie or opera; that is an adaptation mention, not a classification of the story itself.
- If the context gives a specific medium term for the work (e.g., `volume in the ... novel series`, `stand-alone novel`), prefer that exact term over a broader question word such as `book`.



## Resolving Bridge Clues Through Descriptions, Properties, and Relations

- When the question identifies an entity or person by a descriptive phrase rather than by name (e.g., a profession, role, nationality, birth date, relationship, achievement, size/area, sponsor, or other attribute), scan all supplied context blocks for that exact descriptive clue and use it to locate the entity's own context block; then read that target's own block for the requested fact.
- Descriptive clues include constructions such as `the author of <work>`, `the person who wrote <work>`, `the actress who hosted <event>`, `the entrepreneur best known for <thing>`, and `pioneers of <movement>`.
- Use the descriptive phrase only to find the target; do not return the phrase itself unless the question asks for that description, category, or classification.
- If the question names one entity and asks for another entity characterized by a role or attribute, first use the named entity's block to collect candidate names or terms, then match the candidate against the descriptive block before answering.
- If a numeric, statistical, or date descriptor appears in the question (area, year span, count, birth date), confirm the target context block contains that same descriptor before finalizing. For birth-date clues, match the quoted date against the `(born ... <date>)` parenthetical in candidate blocks.
- If multiple entities in the context fit the description, match additional co-occurring named entities, dates, professions, roles, works, years, locations, organizations, or distinguishing attributes from the question to choose the correct target.
- For property-based bridge questions that ask which entity in a named group or context has a stated property or descriptor, first locate the entity whose own context block explicitly contains that property, then confirm the supplied context links that entity to the named group or context before returning its full canonical name. If the named group is mentioned in another entity's block through sibling or shared-attribute statements, treat that as a valid link only when explicitly stated.
- For partner/route/credited-person relation bridges:
  - For partner questions such as `Where is X's Y partner based?`, locate the direct partnership sentence in X's own block (e.g., `X partnered with Z to ...`) and use Z as the bridge. Do not substitute an entity only described as developer, publisher, distributor, or owner unless that sentence explicitly calls it a partner.
  - For a creative work identified by its credited people, resolve each person from their own block using the biographical clue in the question, then find the work block whose direct description names both resolved people; return the requested property from that work block.
  - For transit/route questions, take the route's own block as the source for the places it passes through, then open the candidate place's own block to verify any additional qualifier before answering.
- Return the matched entity or requested value in exact context wording. For entity answers, preserve full canonical names and suffixes as stated in the direct evidence.



## Shared-Property, Intersection, and Geographic Containment

- For questions asking what two named entities have in common, share, or are both known for, collect the requested property from each relevant context block. If an entity's own block lacks the property, scan the other supplied context blocks for an explicit phrase connecting that entity to the property, such as a venue name, organization, event, club, or location.
- Return the shared value exactly as stated in the direct context, without appending entity names, category heads, or extra words not requested. Do not infer the shared property from entity type alone when no explicit contextual support is present.
- For mutual industry/field/area or shared-category questions, use the domain label directly stated in at least one entity's block and confirm through the other entity's stated occupations or categories that it belongs to that domain; return the singular domain term, not an occupation word such as `writer` or `novelist`.
- For `Both X and Y are located in what city?` and similar shared-location questions, extract the common city from each entity's own block and return only that city. Do not add state/province/country unless requested.
- For compound yes/no questions such as `Do X and Y have property P?`, answer `yes` only when both entities have explicit direct support for P; if either lacks it, answer `no`.
- For questions asking for the population or census value of the city where an institution is located, first identify the city from the institution's own block, then read that city's own block and copy the numeric value exactly as written, preserving commas. Do not use a similarly named place from another context block.
