---
name: hotpotqa
description: Use for every supplied-context question-answering task in this HotpotQA experiment.
---

# Question Answering Skill

Base every answer only on the supplied context, then apply these output rules before finishing:

1. **Answer only.** Return the bare answer and nothing else: no explanation, no reasoning, no hedging, no parenthetical remarks, no "Answer:" prefix, and no trailing period.
2. **People: full name.** When the answer is a person, use the fullest form of their name given in the context — given name(s) and surname, including any middle name shown in the lead sentence. Do not shorten to a surname or first name.
3. **Works: full title.** When the answer is a titled work (book, album, periodical, film), give the full title exactly as written, including any subtitle after a colon.
4. **Named things: the name itself.** When the answer is a named thing such as an award, give only its own name: omit an organization's initials placed before it and omit trailing category words such as "award" or "awards" that are not part of the name.
5. **One value, no alternatives.** Never hedge or join alternatives (no "X/Y" or "(X/Y)"). Pick the single correct answer term. If the answer is a field or category, give the specific field noun rather than a broad activity verb.
6. **Comparisons and facts.** For "who is older/younger/later" and similar comparisons, output only the chosen entity's full name. For factual-value questions (year, number, single word), output exactly that value.

Before submitting, re-read your answer and delete every word beyond the bare answer the rules above require.
