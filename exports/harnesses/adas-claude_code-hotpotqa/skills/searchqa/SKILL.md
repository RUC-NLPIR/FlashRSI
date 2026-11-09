---
name: searchqa
description: Use for every supplied-context question-answering task where the answer is in, or directly derivable from, the supplied snippets or paragraphs.
---

# Supplied-Context QA Skill: Answer-Surface Evidence Verification

Follow this procedure internally. Do not mention the procedure in your final answer.

## 0. Lock the output contract before reasoning
- Decide the requested answer type first: person, organization/team/company, work title, place, date/time, numeric/measure, type/category, yes/no, multiple choice, or computed number.
- The final answer may only be:
  A. a verbatim contiguous span copied from the single strongest evidence sentence, or
  B. exactly `yes` or `no` for yes/no questions, or
  C. the exact option text/letter copied from the question for multiple choice, or
  D. for a question that asks for an arithmetic result (count, difference, age, duration, sum, etc.), a number computed from exact ledger values when no verbatim answer exists.
- For A, B, and C you are not asked to compose an answer in your own words. Your job is to locate the exact span that fills the question's slot and copy it.

## 0b. Use the hook's Evidence Map as a shortlist, never as the answer
If a `DETERMINISTIC EVIDENCE MAP` block is present before the task, read it first.
- Its `QUERY FRAME` is a provisional type/shape hint; correct it if the question shows otherwise.
- Its `CANDIDATE BOARD` contains deterministic, copyable span hypotheses with a `role` hint (`TITLE`, `FIRST`, or `OBJECT`). Treat them as leads to verify, not as authoritative, and not as exhaustive. Use the role hint only to choose the correct surface form after the candidate is verified.
- Its `BRIDGE PATH WITNESSES` are two-sentence chains that share an explicit named entity. They are a prioritized map for finding second-hop evidence; verify each hop against the full context, and do not trust a path whose shared entity is a date or a non-answer phrase.
- Its `EXPANDED EVIDENCE` contains graph-expanded lines. Still read and build the ledger from the complete supplied context, because the map may miss the right line.

## 1. Build a coreference-resolved evidence ledger
- Split every supplied snippet/paragraph into sentence-level rows.
- Before recording a row, resolve pronouns and possessives (`he`, `she`, `it`, `they`, `this`, `that`, `his`, `her`, `their`) to the nearest named entity or title in the same unit or the preceding sentence of the same paragraph. Record the resolved subject in the row.
- For each distinct statement, write:
  `[SourceID] subject | relation | value | time/place/condition | polarity | exact wording`
- Keep the `value` field word-for-word as it appears, including capitalization, punctuation, and internal spacing.
- Mark each row `EXACT` if it concerns the same entity, event, date, or condition named in the question, and `DISTRACTOR` otherwise. Record negations/hedges in `polarity`.

## 2. Convert the question into a query frame
Write down:
- Target type (the kind of thing the blank should be).
- Requested relation(s) and any intermediate hop.
- Every explicit constraint (time, place, role, superlative, exclusion, "not", etc.).
- Required output form from step 0.

For **comparison** questions, identify the shared attribute and record that the answer is the winning entity's name, not the attribute value. For **yes/no**, write the precise claim and the conditions that must all hold for `yes`. For **multiple choice**, list each option as a separate hypothesis. For **arithmetic/computed number** questions, write the formula using exact ledger values.

## 3. Verify candidates from the board, bridge paths, and the full ledger
Run the same check on every board candidate, on every bridge-path endpoint, and on any additional candidate you derive from the full ledger.

- **Forward retrieval:** find ledger rows whose resolved subject and relation match the question and whose constraints all hold.
- **Backward chaining:** start from the target type and requested relation, list every row whose value could fill the blank, then chain backward through any intermediate hop.
- **Graph chaining (required for bridge questions):** treat entities as nodes and ledger rows as edges. Walk from a question entity to an intermediate entity and then to the target value, requiring every hop to be an explicit ledger row. Use the hook's `BRIDGE PATH WITNESSES` to locate candidate second-hop lines, but re-check that the shared entity is real and is not just a date, number, or unrelated common word.
- **Proof obligations:** for each candidate, list what must be true if that candidate were the answer, and score it on (a) independent `EXACT` rows supporting it, (b) any row that contradicts it or ties it to a different entity/time/condition, (c) constraint violations, and (d) assumptions needed to fill missing hops.
- Actively try to refute the highest-scoring candidate with a contradicting row before accepting it.

## 4. Adjudicate the answer and then choose its exact surface
Score candidates by: independent `EXACT` support; satisfaction of all constraints; a complete, explicit chain for bridge questions; no contradiction; fewest assumptions.
Then choose the **answer surface** from the candidate's strongest source sentence, using these rules:

- **Person (`who` / `whom` / `whose`):** copy the complete person name as introduced in that source sentence, including first and middle names, a quoted nickname, and a generational suffix (`Jr.`, `Sr.`, `III`). Do not shorten a full name to a familiar short form, and do not include titles, roles, dates, or appositive descriptions that are outside the name itself.
- **Organization, team, company, conference, or place:**
  - Copy the proper-name phrase exactly as it appears in the selected source sentence, including legal suffixes (`Co., Ltd.`, `S.p.A.`, `Football Club`) and category words that are part of the official name. Remove only a leading article (`the`) and surrounding punctuation.
  - If the question asks for a bare category (`which conference`, `which team`, `which university`) and the source phrase ends with that exact category word, keep the full official phrase (for example `Atlantic Coast Conference`, `Liberty University`).
  - If the question already qualifies the category with a modifier (`which Division II conference`, `which national team`) and the source phrase ends with that category word, copy the name without that final category word (for example `Northeast-10`, `China`), because the category is already explicit in the question.
  - For a nested place phrase such as `Bogota, Colombia`, copy only the component that matches the requested granularity: the city/town for `which city/town`, the country for `which country`, and so on. Do not include the larger or smaller location in the answer.
- **Type / category / genre / position / language / style:** copy the bare category phrase (for example `film`, `left-back`, `drama`), not a longer descriptive clause and not an expanded list.
- **Date / time:** copy the date or time expression exactly as it appears in the chosen row. Do not paraphrase a specific date as a holiday or season name.
- **Quantity (`how many` / `how much` / `how long` / `how far` / `how old`):** copy only the number or measurement expression, dropping hedging words (`around`, `about`, `over`) and dropping the unit unless the unit is part of the exact answer. Example: `around 200 pages` should be copied as `200` when the question asks `how many pages`.
- **Comparison questions:** the winning candidate must be an entity name/title copied from the ledger, never the raw attribute value.

If two candidates tie, prefer the one whose source span is shortest while still completely answering the question and following the surface rule above.

## 5. Copy the answer byte-for-byte (or emit the computed number)
- Re-read the chosen span in its source sentence and apply the step-4 surface rule one final time.
- Output only that span, or exactly `yes`/`no`, or the exact choice text, or the computed number.
- No markdown, no bold/italics, no quotes, no added punctuation, no trailing spaces, no full sentence unless the question explicitly demands one.
- Do not shorten a person's name or a work title. For organizations and places, apply the category-word rule above and otherwise keep the official phrase intact; do not append the question's category word to the answer.
- For computed numbers, output only the numeric result in the shortest standard form, with units only if the question asks for them and the ledger values share those units.
- If no candidate survives verification, output `unknown`.
