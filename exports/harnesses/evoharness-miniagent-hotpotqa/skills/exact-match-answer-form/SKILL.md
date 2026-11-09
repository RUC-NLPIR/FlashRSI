---
name: exact-match-answer-form
description: Use for exact-match short-answer QA to copy the shortest required source span; choose name form by question phrasing, avoid repeating question nouns, prefer singular source category nouns for plural-sounding multi-entity questions, and preserve source numeral wording.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [5ac42546554299076e296d70]
---
# Exact-match answer form

Copy the shortest required source span exactly; do not normalize, abbreviate, or expand.

- Person by name: choose by question phrasing. "Who wrote [work]?" -> shorter credited name from the direct attribution ("It was written by Ian Maxtone-Graham"), not the expanded formal name in a biographical lead. Otherwise use the full formal introductory name.
- Organization: shortest source form.
- Ordinal: spelled-out, not numeric.
- Kind/category: if the question already names the category noun ("What kind of guitar riffs..."), copy only the distinguishing modifier phrase ("heavily downtuned, mid-paced"); do not repeat the head noun. Otherwise use the minimal category head noun ("no-kill shelter").
- Multi-entity "What are X and Y?" shared-category questions: the plural-sounding question does not make the answer plural. When the source defines each entity with a singular category noun (e.g., "an opera in four acts"), answer with that singular source noun ("opera"), not an inferred plural ("Operas.").
- Sport/activity: source role descriptor ("alpine ski racer"), not a normalized noun.
- Numeric quantity: for bare answers, copy the numeral exactly as written; "four 2015 Grammy Awards" -> "four", not "4"; "2,300" -> "2,300".
- Bridge/multi-hop: full linking span.

Keep structure words: complete "credited with [action] to [purpose]" predicate; full "from where to where" extent with compass qualifiers. Resolve anaphors by direct classification, not adaptation language.
Before finalizing: trim extra names/prefixes/suffixes only when not required; restore missing canonical wording; preserve source wording/case. Strip natural-language wrappers only for bare numeric answers.
Prefer the shortest span that fully answers and fits the question; add no extra words.
