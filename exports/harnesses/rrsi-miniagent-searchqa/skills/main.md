# Question Answering Skill

Use these rules on every QA turn.

## Follow output-format instructions exactly
If the user's request says to return only the short answer (or "only the ...",
"just the ...", "nothing else", "one word", "one line"), the final message must
be exactly the requested answer phrase and nothing else. Remove every lead-in,
restatement, explanation, citation, markdown, quote, parenthetical, gloss,
date, or trailing punctuation that is not part of the requested form.

## Answer from the supplied context
- Map every clue and predicate in the question to the single entity or term
  most directly and specifically supported by the supplied context. Do not
  answer from outside knowledge, and do not keep a candidate that matches
  only part of the clue.
- Treat every concrete clue (numbers, dates, denominations, abbreviations,
  relationships) as a hard filter. If a candidate matches a surface token but
  misses another constraint, discard it and keep looking.
- For a definition/category clue ("An X that does Y", "the term for ..."),
  return the general category term whose function the context states, not a
  salient example sharing only one property. Before choosing a named remedy,
  ingredient, or other specific item, confirm the context states it as the
  general term that performs the function; an item that merely shares one
  property is a distractor.
- For a bare role/title clue, return the associated country, state, or
  organization. For a bare pair/list clue, return the shared label or
  location, not a sentence about the people.
- If a planned external lookup fails, do not override the supplied context
  with an outside-memory candidate; fall back to the strongest
  context-supported entity.
- For a quoted-fragment clue (for example "...on my mind"), prefer the
  passage that completes the fragment with a single diagnostic adjacent token
  over the most frequent similar entry, and return that adjacent token.
- For a "these ..." or "one of these ..." clue, return the category term for
  the group, not the quoted phrase itself and not a phrase that repeats a
  qualifier already present in the question.

## Preserve the canonical surface form
- Echo the exact wording supplied by the context: number, capitalization,
  hyphenation, and name extent.
- Once you have the correct entity or term, emit the shortest context phrase
  that still satisfies every clue. Drop trailing category suffixes, years,
  parentheticals, and full legal names when the question asks for a nickname,
  surname, acronym, term, or short label.
- For a produce/plant clue ("this fruit", "this berry"), return the noun form
  the context uses for the food itself, not a singular attributive form used
  in festival or brand names.
- For a Jeopardy-style "this ..." or "whose ..." person clue, return the
  surname/target name only when the supplied context gives the answer that
  way. For a factual statement about a person ("he/his/her ..."), keep the
  person's name exactly as the context introduces it.
- Do not over-shorten a correct full name. If a follow-up asks for a shorter
  phrase, keep the current answer when it is already the shortest context
  phrase that names the same entity and satisfies every clue. Never drop a
  given name, honorific, or required company word, and never replace a name
  with an epithet or descriptor the clue does not ask for.

## Exact-match self-check
Before finalizing, ask: "If the grader compares my final message
character-for-character with the expected short answer, does anything extra
remain?" If yes, remove it. Then ask: "Is this exact wording (number, case,
hyphenation, and extent) taken from the supplied context?" If not, fix it.
