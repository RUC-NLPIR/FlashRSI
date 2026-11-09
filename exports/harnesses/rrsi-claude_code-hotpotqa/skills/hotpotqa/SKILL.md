---
name: hotpotqa
description: Use for every supplied-context question-answering task in this experiment.
---

# Question Answering Skill

Use this skill whenever a task supplies a context and asks for a short answer.

## 1. Honor the requested output format
Read the task instruction and produce exactly the format it requests. When the instruction says `Return only the short answer`, the final message contains only the answer itself: no labels, quotes, commentary, explanations, or extra punctuation.

## 2. Locate the answer-bearing sentence first
- In your thinking, resolve the question's subject first. If the question contains a pronoun or definite reference (`this`, `that`, `it`, `he`, `she`, `the series`), trace it to the specific context entry it denotes. For `A or B?` questions, resolve the subject before picking an option; do not count surface mentions of an option in unrelated entries.
- Then locate the single context sentence that directly states the requested fact. If the subject's own entry does not state it, use the other entry that does state it.
- Do not answer from an entry that merely shares a surface word with the question.

## 3. Choose a verbatim span
- The answer must be an exact, contiguous excerpt of the supplied context, copied character-for-character.
- Prefer the shortest contiguous excerpt that still fully answers the question.
- Do not paraphrase, reword, or compose a phrase that does not appear verbatim in the context.
- Do not import a name, title, or phrase form from a different sentence or entry.

## 4. Adjust the boundary to the question focus
After choosing the shortest complete span, adjust its edges with these reusable rules:
- Yes/no: answer `yes` or `no`, lowercase, with no explanation.
- Count (`how many`, `approximately how many`, `number of`): keep only the numeral exactly as written. Delete counted nouns and units unless the question asks for that unit as a standard measure.
- Classification (`what kind/type/style/genre/category/sport of ...`, `what are ...`): keep the class term as it appears in the context. Keep an adjective+noun compound when the whole compound is the class name; delete the head noun only when the question already names it. For a work's genre or style, keep the full genre label including subgenre modifiers that are part of the label (for example `black comedy`, `romantic comedy`); delete only a holiday, nationality, or location modifier that describes the work rather than the class.
- Person: use the exact name form in the answer-bearing sentence. Do not import a fuller or shorter form from another entry. If the question is `Who was/is [name already given]?`, return the descriptive phrase the context uses to define that subject instead of the legal name. If `who` is singular and the answer-bearing sentence lists several people joined by `and`, keep only the first full name before `and`.
- Titled work: use the exact title form in the answer-bearing sentence. When the question names alternatives in quotes, keep the chosen alternative exactly as written; do not add a subtitle or a fuller title from another entry.
- Proper noun (company, organization, university, place): keep the full contiguous proper-noun phrase as written in the answer-bearing sentence, including suffixes such as `Films`, `Inc.`, `University`, or `College`, and comma-separated city/state/country qualifiers. Drop only a leading locative preposition (`on`, `at`, `in`).
- Relation (`from where to where`, `between ... and ...`): keep the full relation phrase including the leading relation word.
- Measurement (`how high/tall/long/far/old/much`, `what year`): keep the number or range with its unit exactly as written, and verify the requested dimension. A count question is never a measurement question.
- Statement, definition, record, or event: keep the complete reporting sentence or clause verbatim, including its lead-in words and final punctuation.
- If no focus rule matches, use the shortest contiguous context span that still fully answers the question.

## 5. Copy the excerpt exactly
- Preserve the excerpt's case, punctuation, diacritics, spaces, and quote characters exactly as they appear in the context.
- Do not rewrite numbers or ordinals into another format, and do not add a leading article unless the context excerpt already has it.
- Do not split a single proper name, title, place phrase, appositive, coordinate expression, or other compound expression.

## 6. Verify before you answer
Before the final message:
1. Draft the answer, then invoke the Skill tool with skill `flashrsi:answer-verifier`, passing the question and your draft in the tool `args`.
2. Apply the corrected answer returned by that skill.
3. If the verifier is unavailable, check the drafted answer yourself:
   - It is `yes`/`no`, or it is a contiguous substring of the supplied context.
   - It is the shortest span that still fully answers the question.
   - It follows the focus boundary in section 4.
Then emit only the corrected answer.
