---
name: hotpotqa
description: Use for every supplied-context question-answering task in this HotpotQA experiment.
---

# Question Answering Skill

Use only the supplied context; do not search externally or rely on outside knowledge.

## Answering Rules

- Return only the requested short answer; do not write a sentence, restate the question, add explanations, Markdown, bold, parentheses, or trailing punctuation.
- Do not infer facts that are not explicitly stated in the supplied context.
- Copy the exact wording from the relevant context for descriptive phrases, named entities, titles, ordinal positions, and numeric/spelled-out forms (e.g., return `four` if the context says `four`, not `4`). For attribute/category questions such as `What style/type/genre of ...?` or questions that already name the requested category or unit (e.g., `what genre of films`, `what type of music`), return only the exact requested value from the context. Do not copy the whole descriptive noun phrase, the entity/category head, or the category noun already present in the question. Exception: when the context states the requested value as a fixed multiword category label or compound descriptor phrase whose head noun is essential to the classification (e.g., `Moravian and other Slavic folk music`), copy the complete phrase exactly, including the head noun. The rule to return only the requested value still applies to genuine adjective-only attributes such as styles, genres, and types.
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
4. For multi-hop or bridge questions, use a fact from the first entity's paragraph to identify the intermediate entity, then read that entity's paragraph for the answer. Facts about a target entity may appear inside another entity's description, especially in comparisons or shared attributes.
5. For comparison questions, extract the same comparable property or value for each candidate and compare them directly. For yes/no comparisons, answer "yes" only when the context explicitly states the compared attribute for both entities; broad descriptions such as "multi-instrumentalist" do not establish a specific instrument, so answer "no" if explicit support is missing.
6. For birth-year or birth-date questions, look for the relevant context block containing `(born ... <year>)` and return only the requested part.
7. Before answering that something is not stated, verify the requested property under all plausible surface forms and related terms (e.g., area vs. volume, size, capacity); prefer the context's stated value and units.
8. Return only the short answer requested; no extra explanation, sentences, citations, or surrounding text.

## Checks

- Prefer the supplied context over outside knowledge.
- If a term is ambiguous, select the paragraph whose relationships match the question. If several supplied context blocks share the same name/title, do not settle by title alone; list the candidate blocks and match them against any co-occurring named entity or distinguishing attribute present in the question (e.g., a featured artist, author, creator, year, or type), then answer from the block that contains that companion clue.


## Classification Answer Form

- For classification questions such as `What are X and Y?` or other plural question phrasing, return the singular category noun that the context uses to define each item, not a pluralized form. If the context says each item `is a novel`, answer `novel`, not `novels`, even when the question uses a plural verb such as `are`.


## Resolving Anaphoric and Medium Questions

- When the question uses an underspecified referring expression such as `this story`, `this work`, `the story`, or `it`, do not match it to a passage merely because that passage contains the surface word `story`, `book`, or `movie`. First determine the titled work or entity the question is about, then use that work's own context block.
- For questions asking whether a story or work is or was made into or is a `book`, `movie`, `novel`, `film`, `play`, etc., return the direct medium/format label stated for that titled work. Do not infer a medium from a biography saying a person's story `inspired` a movie or opera; that is an adaptation mention, not a classification of the story itself.
- If the context gives a specific medium term for the work (e.g., `volume in the ... novel series`, `stand-alone novel`), prefer that exact term over a broader question word such as `book`.


## Answer-Form Calibration

- For `what award/prize/medal did X win?` questions, remove an awarding-body or sponsor prefix from the start of the award phrase and return only the standalone award name used in the direct evidence, unless the full prefixed form is the canonical name or the question explicitly asks for the formal sponsored title.
- For `what did X do?` or `what notable act/achievement/action ...?` questions, copy the complete predicate clause from the direct evidence sentence, including finite verbs, carrier verb phrases, and any subject pronoun that introduces the clause. Do not reduce the source clause to a bare gerund or noun phrase.
- Before finalizing, compare the candidate surface form to the direct evidence clause and to the answer type. If a short-answer rule would strip or add words relative to the context clause that directly answers the question, adjust to preserve the expected form for that answer type.


## Additional Success Patterns

### Resolving Descriptive or Attribute-Only Entities in Bridge Questions

- When the question identifies an entity by a descriptive phrase, relative clause, profession, time period, nationality, award, title, office, or relationship rather than by name, first locate the exact or near-exact descriptive or attribute match in the supplied context, identify which named entity it describes, then read that entity's own context block for the requested attribute.
- Do not return the identifying phrase itself as the answer unless the question explicitly asks for that description; use it only to find the named entity and then answer from that entity's facts.

### Temporal Answer Form

- For `on what day`, `in what year`, or similar date/year questions, return only the date or year exactly as stated in the context (e.g., `January 17, 1981`, `1945`).
- Do not include leading prepositions such as `on` or `in`, and do not convert numeric years to words or words to numeric years.

### Intersection and Shared-Credit Questions

- For questions that ask which person or entity appears in, worked on, or is associated with two named works or groups (e.g., `What star of X also appeared in Y?`), extract the credited members or participants named in each work's own context block and return the common member. Direct co-occurrence in both lists is sufficient; do not require an explicit cross-reference between the works.

### Vague Comparison Terms

- For comparison questions using broad terms such as `wider`, `broader`, `larger`, or `more widely`, treat the comparable dimension as an explicitly stated scope or reach property: geographic reach (global/international/multinational versus regional/local), number of locations or countries, product range, or a similar stated scope phrase. Prefer the exact scope wording in each candidate's own context block and do not infer the dimension from entity type alone.

### Shared-Role Yes/No Comparisons

- For yes/no questions asking whether two people share a role, treat any role named in a person's occupation list or descriptive clause as explicit support. A person described as `singer, songwriter and actor` and another as `singer, guitarist, and songwriter` both explicitly support `singer-songwriter`; answer `yes` when each component is stated, and `no` when the context gives only an unrelated broad description.

### Ordinal Bridge Resolution

- For bridge questions with an ordinal (`first`, `second`, `third`), resolve the ordinal using chronological, term, or explicit context clues before selecting the entity paragraph. Do not confuse the first mentioned or earliest block with the ordinal target; then read the resolved entity's own paragraph for the requested property.

### Plain-Text Alternate Names

- For questions asking what an entity or product is called or referred to as, return the alternate name as plain text, using the context's spelling but without surrounding quotation marks, Markdown, or extra punctuation, even if the context encloses the term in quotes.

### Place-Containment and Administrative Units

- For place-containment questions (e.g., which county/state/province/country a city, venue, or landmark is in), return the full administrative unit exactly as stated, including words like `County`, `Province`, or `State`; do not return only the city or the bare geographic name, and do not omit the unit suffix.

### Numeric Answer Formatting

- For numeric answers, copy the digit string exactly from the direct evidence, preserving commas and decimal points (e.g., return `1,234` as written, not `1234`). Do not add or remove formatting.

### Singular Questions with Compound Sources

- For singular questions that point to a compound source (e.g., a work created by more than one person), if the requested property is explicitly stated for only one of the named people in the supplied context, return that one's property; otherwise follow the single-person rule for compound phrases.
