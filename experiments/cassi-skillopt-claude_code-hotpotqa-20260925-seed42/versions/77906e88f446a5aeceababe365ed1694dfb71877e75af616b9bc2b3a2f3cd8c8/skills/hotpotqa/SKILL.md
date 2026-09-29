---
name: hotpotqa
description: Use for every supplied-context question-answering task in this HotpotQA experiment.
---

# Question Answering Skill

Use only the supplied context; do not search externally or rely on outside knowledge.

## Answering Rules

- Return only the requested short answer; do not write a sentence, restate the question, add explanations, Markdown, bold, parentheses, or trailing punctuation.
- Do not infer facts that are not explicitly stated in the supplied context.
- Copy the exact wording from the relevant context for descriptive phrases, named entities, titles, ordinal positions, and numeric/spelled-out forms (e.g., return `four` if the context says `four`, not `4`). For attribute/category questions such as `What style/type/genre of ...?` or questions that already name the requested category or unit (e.g., `what genre of films`, `what type of music`), return the requested value from the context. If the context supplies a standalone descriptor or adjective that answers the question, return only that descriptor and do not repeat the category noun from the question. If the context defines the kind by a compound label in which the category noun is part of the label and the descriptor alone is incomplete or not a standalone kind, return the full compound label exactly as stated, including the category noun. Do not copy unrelated descriptive clauses or extra modifiers that are not part of the classification label.
- Before finalizing, compare the answer with the wording in the relevant context sentence; exact-match grading may require context wording rather than synonyms.
- For award, prize, medal, or similar honor questions, separate the awarding body or sponsor from the title of the honor. When the direct evidence has the form `<awarding-body> <honor title>` or `<awarding-body> <honor title> award`, and the question asks simply what award or honor the person won, return only the standalone honor title from the direct evidence, omitting the awarding-body or acronym prefix unless the prefix is an inseparable part of the common name or the question explicitly asks for the formal sponsored title. Verify the shorter title is itself a complete standalone name; if not, keep the full context phrase.

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


## Sport/Activity and Occupation-Label Questions

- For questions asking what sport, activity, or type of athlete/performer a person participates in or is, return the exact sport/activity descriptor phrase used in the direct evidence clause (e.g., `track cyclist`, `ice hockey player`, `rally driver`).
- Do not convert the descriptor into a bare sport name or a gerund. If the context identifies the person as an `ice hockey player`, answer `ice hockey player`, not `hockey`, `ice hockey`, or `playing hockey`.
- Preserve the actor/agent suffix (`player`, `racer`, `cyclist`, etc.) unless the context itself gives a bare sport name as the direct answer.
- Remove nationality, league, team, or organization modifiers that are not part of the requested sport/activity descriptor, but do not add synonyms or extra words.

## Full Titles and Subtitles

- When the requested answer is the name/title of a work, periodical, publication, or other titled entity, return the complete title exactly as it appears in the direct evidence sentence, including any subtitle after a colon or dash and original capitalization.
- Do not reduce the title to a short or common name, even if the question uses a shortened form, the context later refers to it by a short label, or a bridge mention uses only part of the title.

## Measurement and Full-Clause Answers

- For questions that ask for a measured quantity such as height, distance, depth, size, speed, count, or another numeric property, do not reduce the answer to a bare number plus unit. Return the complete measurement clause from the direct evidence exactly as written, including the subject, any superlative or comparison, the measured value, and unit qualifiers such as `above sea level`.
- If the requested measurement is stated only as part of a full sentence in the supplied context, copy that full sentence rather than shortening it. This is an exception to the short-answer/no-sentence rule for measurement questions because exact-match grading may require the full evidence clause.
- Preserve the original digit formatting and unit wording; do not add or remove thousands separators, abbreviate units, or rephrase the context wording.


## Candidate and Bridge Resolution from Named or Described Entities

- When the question names two or more candidate works/entities (e.g., `Between A and B, which ...?`), check each candidate's own context block for explicit support for the requested property and return the matching candidate's title/name exactly as stated, not the property value or explanation.
- When the question describes an entity only by role, profession, nationality, time period, or distinguishing phrase, search the supplied context for that descriptive clue, resolve it to the named entity it modifies, then open that named entity's own context block for the requested fact.
- If a bridge phrase or descriptive clue yields more than one candidate, choose the candidate whose own context block explicitly supplies the requested property; do not answer from candidates for whom that property is absent or only implied. A shared surface word or co-mention is not enough.
- For bridge questions that name a place, work, organization, or thing and ask which person/entity is associated with it, read the named entity's own context block first to identify the target person or entity mentioned there, then return that target's canonical name exactly as stated. Do not return the named bridge entity itself.
- When a named work or place and another entity are linked through a relation, use the relation in the named work/place block only to identify the target entity, then retrieve the final value from the target entity's own block.
- For relation questions such as `What number/role/attribute of the person for whom X held office, worked, or served?`, use X's own block to identify the principal person, then read that principal's own block and copy the requested ordinal or attribute from there.
- When the same title appears for a song, album, film, or other work and the question identifies it by work type and/or release year, disambiguate by the requested work type and date, select the matching block, and extract credited people or properties from that block.
- For product or alternate-name questions where a company/store is identified by a unique attribute such as headquarters, chain, or owner, first resolve the company/store from that attribute, then read the product or alternate-name block and return the name exactly as context wording without added punctuation.
