---
name: hotpotqa
description: Use for every supplied-context question-answering task in this HotpotQA experiment.
---

# Question Answering Skill

Use only the supplied context; do not search externally or rely on outside knowledge.

## Answering Rules

- Return only the requested short answer; do not write a sentence, restate the question, add explanations, Markdown, bold, parentheses, or trailing punctuation.
- Do not infer facts that are not explicitly stated in the supplied context.
- Copy the exact wording from the relevant context rather than paraphrasing, especially for descriptive phrases, ordinal positions, titles, and numeric/spelled-out forms (e.g., return `four` if the context says `four`, not `4`).
- Before finalizing, compare the answer with the wording in the relevant context sentence; exact-match grading may require context wording rather than synonyms.
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
