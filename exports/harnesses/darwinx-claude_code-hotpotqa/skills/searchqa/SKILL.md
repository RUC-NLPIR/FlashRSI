---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

Answer every question from the supplied context only. Return only the short answer in the requested format.

## Step 1 — Read everything first
- Scan all passages before answering. Note each passage's subject and its concrete details (names, dates, roles, places, titles, numbers).
- Prefer the context's exact wording over paraphrases or outside knowledge.

## Step 2 — Direct answer first
- If one passage already contains the complete answer, answer from that passage and stop.
- Do not chain extra hops, re-open other same-name passages, or over-disambiguate when a single passage fully answers.

## Step 3 — Bridge hop (only when needed)
- Use a bridge only when no single passage contains the complete answer.
- Trace: passage for the entity named in the question → passage that connects it to the requested target.
- Always answer the final requested slot (the value the question actually asks for), never the bridge or intermediate entity.

## Step 4 — Choose the right value
- If a passage lists several candidates, join them with "and" only when the passage explicitly attributes the fact to both/all and the question asks who it is true of. Otherwise return the single value the question targets.
- Do not return an entity already named in the question unless it is the requested answer.
- For repeated names, use the passage that matches all the question's concrete details (dates, roles, places); reject name-only partial matches.

## Step 5 — Format the answer
- Short answer only: no explanation, markdown, headings, trailing period, or parenthetical asides.
- Yes/no questions: answer only "yes" or "no". For "both"/"each" questions, verify each entity explicitly before deciding.
- Numbers and dates: keep the context's exact form (digits vs words, ordinal vs cardinal).
- Names: use the form the relevant passage uses; do not add middle names, titles, or post-nominal letters.
- Titles: give the complete title/subtitle as the context gives it.
- Awards: give the award name as it appears in the context.
- Places: match the place granularity the question asks for (city, county, state, or country).
- Comparisons: extract both values from the context and compare them explicitly.
- "What did X do / what is X notable for": return the context sentence that states the act, using its wording.

## Step 6 — Final check before answering
- Re-read the question and confirm the answer is the requested slot, comes from the context, and is formatted as a bare short answer.
- If the first reading does not answer the question, re-check related passages and same-name entries before giving up.
- Answer "not enough information" only when the context truly lacks the requested fact.
