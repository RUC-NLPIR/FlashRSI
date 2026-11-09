---
name: short-answer-exact-match
description: Return the minimal exact-match answer for short-answer QA. Use when a prompt instructs "return only the short answer" (or otherwise implies exact-string grading) and asks for a name, nickname, alias, title, symbol/code, or person (a person named by a first name or full name — answer with the bare surname); when the context offers a full title and a shorter common name, variant spellings/aliases of the target, or overlapping group terms whose membership must cover every listed item; when a title/role is shared across people and a "current"/"former" qualifier disambiguates; or when exact match hinges on verbatim spacing/punctuation, number inflection, or a nickname-vs-formal-name choice.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [b55578edb7ba4b5ba9ed09dc7333795b, 88d06cbae9ef4d5f827ed4d8ed7e2ee7, 4c64770f574c499392b07f182a75c72c]
---
For exact-match short-answer questions, produce the shortest span that fully answers the interrogative — no extra words.

1. Extract first. If the answer appears verbatim in the context, copy it from the most definitional source (glossary, title, definition line) and emit it immediately; do not paraphrase or search beyond the provided documents — delay can leave the run with no answer.

2. Return the minimal token only — the bare name, nickname, alias, or surname the question asks for — with no role words, type affixes, or category word the question already names ("Bull Moose", not "Bull Moose Party"; "C", not "Vitamin C").

3. Prefer the shortest common/canonical form: a full title vs. a shorter common name → emit the shorter one ("Studio 60", not "Studio 60 on the Sunset Strip").

4. Match the exact form the grader expects: no appended parentheticals, punctuation, or extra tokens; over-expansion scores 0. Do not re-add a qualifier from the prompt ("M*A*S*H", not "M*A*S*H (1970)"), and preserve verbatim spacing ("high pressure", not "high-pressure").

5. Among accepted spellings/aliases, emit the one matching the question's phrasing ("Greek for leaf" → "phyllo").

6. Verify every constraint before committing; do not anchor on a salient keyword across near-miss passages. Confirm role, place, and numeric detail all hold in one passage. For overlapping group terms, pick the one covering every item ("Nordic countries" includes Finland, "Scandinavia" does not).

7. Preserve exact surface form, including number inflection: emit the standalone form verbatim ("million strawberries"), not the referent's singular.

8. For a person with a nickname and a formal name, emit the formal name ("Patricia Hearst", not "Patty Hearst").

9. Parse for a temporal/status qualifier ("current", "former", "last") before extracting. When a title/role is shared across people, that qualifier — not context frequency — picks the individual; find the passage tying that person to the attribute.
