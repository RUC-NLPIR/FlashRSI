---
name: searchqa
description: Slot-first, type-routed, evidence-grounded question answering for SearchQA tasks. Use for every question where the supplied context contains search snippets, web pages, or retrieved documents.
---

# SearchQA Answering Protocol

You answer questions from noisy search contexts. Most questions are Jeopardy-style clues and the answer is a specific entity, title, name, date, number, or short phrase. Exact-match grading is used, so the answer must be exactly the slot the question asks for, in the form the strongest evidence uses.

Work through the steps below in private reasoning. Do not put reasoning in the final response unless the task explicitly asks for it.

## 0. Use deterministic pre-extracted evidence if present
A preprocessor may add up to three blocks before the task: `SLOT CONTRACT`, `PRE-EXTRACTED ANSWER LINES`, and `ALIGNED PROSE EVIDENCE`.

- `SLOT CONTRACT` is a deterministic guide to the answer surface form. Read it first and let it constrain how much or how little you output.
- `PRE-EXTRACTED ANSWER LINES` are deterministically pulled from the supplied snippets. A clue that closely matches the question is very strong evidence; if you use it, copy the answer text after `=>` exactly, preserving wording, capitalization pattern, abbreviation, and word order.
  - Tag `EXACT` means the clue text matches the question; treat it as decisive. Output the text after `=>` exactly, without shortening, expanding, or rephrasing, unless the `SLOT CONTRACT` requires deleting a trailing category word that the hook did not already strip.
  - Tag `EXACT-PARTIAL` means the clue matches but the extracted answer is only a surname or first name for a person slot. Do not copy it verbatim; use it to identify the person, then output the full name form used by the rest of the evidence.
  - Tag `close` is strong but not decisive; verify it completes the question.
- `ALIGNED PROSE EVIDENCE` is a deterministic re-ranking of ordinary prose sentences: words in `[[double brackets]]` are already stated in the clue, so the missing answer is normally an adjacent unmarked noun phrase. Stop before a trailing year or place that merely describes when/where, and do not include it in the answer. The `=> lead:` hint (if present) is just a candidate span, not a pre-extracted answer.
  - Use these sentences to locate the answer in noisy prose, especially when no `PRE-EXTRACTED ANSWER LINES` are present.
  - If the answer name naturally embeds a bracketed clue word (for example "East River" for "this river", or "First Amendment" for "this amendment"), output the full evidence name -- do not cut it to only the unmarked modifier.
  - Do not let a prose lead override an `EXACT` pre-extracted line or the `SLOT CONTRACT`. Verify the lead completes the whole clue before using it.

Still verify that the chosen answer completes the question, but do not let a weaker paraphrase override a decisive `EXACT` line.

## 0b. Obey the deterministic slot contract
If a `SLOT CONTRACT` block is present, apply it as an override to your usual surface-form guess:

- `role: ENTITY` — the blank is the named entity itself. Do not repeat the category word that follows `this`/`these` (for example a question slot that says "this missile", "this gland", "this company", "this river", or "this city" should be answered with the name, not with "... missile", "... gland", "... company", etc.). Also strip legal suffixes and descriptors that are not part of the answer name.
- `role: TYPE_OF` — the blank is a subtype/kind. Start from the strongest evidence's exact wording for that subtype, then drop a category noun already stated in the question (for example the noun after "type of") unless dropping it would leave an incomplete or non-idiomatic answer. Do not add words that are not in the evidence.
- `role: COMPLETION` — answer only the missing token(s). Never repeat words already shown outside the blank or outside the quoted fragment.
- `role: BARE_CLUE` — the clue is a title, name, or fragment with no explicit slot. Supply the missing attribute (category, place, person, or title) in the shortest exact form the evidence uses, not a descriptive gloss or associated name.

If the slot contract conflicts with a pre-extracted answer line, the pre-extracted exact line wins unless the line is `EXACT-PARTIAL` or the line contains a category word that the slot contract says to delete.

## 1. Identify the exact answer slot
Before choosing an answer, restate in one sentence what is being asked and identify the exact grammatical slot, including number and required words.

- "This type of X" / "these X" asks for the distinguishing word or phrase, not the category noun X unless the evidence uses the full subtype phrase.
- "Multi-this" asks only for the part after "multi-".
- "This relative of his/hers" asks for the possessive phrase (for example, "his mother"), not just the bare noun.
- "This does what" / "because it does this" asks for a complete predicate: keep the verb plus its necessary object or complement, not just the bare verb, unless the bare verb alone is grammatical and complete.
- "Rate of this" asks for the thing whose rate is described, not the numeric rate itself.
- "One of these" is singular; "these" is plural. Match number.

If the question already contains a descriptor, category noun, or qualifier for the slot, do not put that word in your answer unless the slot contract says the evidence phrase includes it or the word is part of a proper name.

## 2. Route by clue shape
Decide what kind of clue this is, because different shapes require different slots.

- Direct "This ..." / "These ..." clue: the entity described.
- Bare title/category clue (a name, title, place, or date with no question word): supply the missing category attribute, not a nearby place, a description, or an associated person.
- Quote/fragment clue: decide whether the slot is the work, the author/speaker, a category/nationality, or the missing text itself. A quoted line by itself does not automatically ask for the author.
- Year + event clue: usually asks for the title, event, or entity associated with that year, not a person merely involved.
- Foreign-language clue: give the English equivalent from evidence, not a related but different item.
- Completion clue (blank or a quoted fragment with one side missing): output only the missing text, never the words already printed.

## 3. Read and filter evidence
- Read every supplied snippet before choosing, but start from `PRE-EXTRACTED ANSWER LINES` and `ALIGNED PROSE EVIDENCE` when present.
- Prefer pre-parsed answer lines first, then aligned prose sentences that directly cover the clue, then other snippets.
- Discard snippets about a different time, place, or similarly named entity.
- Treat snippets that pair a clue with a short answer as very strong evidence.

## 4. Generate candidates, subtract, verify
- List every plausible answer from the directly relevant snippets.
- Score candidates on directness (how exactly it fills the slot), specificity, agreement across independent snippets, and recency/reliability.
- For each candidate, subtract words already present in the question as slot descriptors, unless the slot contract is `TYPE_OF` and dropping the category would leave an incomplete or non-idiomatic answer.
- Prefer a precise name/date/title over a general category, but prefer the generic category noun over a brand or example when the question asks "these ..." or "this type of ..." and no specific subtype is asked for.
- Substitute the chosen answer back into the question. It must make a true, grammatical, complete statement.

### Exact-match form check
Mentally normalize both the candidate and the evidence wording like a grader does: lowercase, plain ASCII, remove punctuation, and remove only `a`/`an`/`the`. If two forms differ in token order, function words such as `of` or `to`, abbreviations such as `Mt.` vs `Mount`, possessives, or singular/plural, they will be graded as different answers. Preserve the exact evidence form.

- People: use the name form from the evidence or QA line that most directly answers the question. Use a surname only when that evidence uses a surname only; use a full name when it uses a full name; keep titles and honorifics that are part of the evidence form. Do not automatically expand or contract a name, except when a pre-extracted line is tagged `EXACT-PARTIAL`, in which case you must expand the partial name to the full evidence form.
- Titles and names: preserve exact wording, including a leading "The" only when it is part of the title. Use plain ASCII spelling (for example, "Les Miserables" rather than "Les Misérables") unless the question itself uses the accented form.
- Dates: answer at the granularity the question asks for (year, month, or full date). Quantities: include units only when the slot asks for a quantity and the evidence gives them.

## 5. Output
- Output only the answer, with no explanation, no markdown, no surrounding quotes (unless quotes are part of the answer itself), and no leading phrase such as "The answer is".
- Give the shortest complete answer that still fills the exact slot.
- If no plausible answer appears in any snippet, answer "unknown". If evidence is weak but a candidate exists, still choose the best-supported candidate rather than refusing.
