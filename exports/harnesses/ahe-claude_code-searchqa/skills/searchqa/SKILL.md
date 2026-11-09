---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

Answers are scored by exact string match, so the final answer must be the bare
answer string and nothing else. Follow this procedure for every SearchQA question.

## 1. Answer immediately after this skill

As soon as these instructions are available, stop all further reasoning and
produce the final answer in your very next assistant message. Do not call another
tool, do not continue thinking, and do not wait for another turn.

## 2. Locate the answer in the context

Read the question and the supplied context. If the question is a run-together
fragment or has missing spaces, interpret it as the intended query and still
extract the entity it asks for. Identify the single entity, name, title, term,
or short phrase the question asks for. Prefer the shortest substring of the
context that fully answers the question.

## 3. Extract the bare answer

- Answer the question; do not restate the topic and do not repeat the question.
- If the question asks about a person and uses pronouns (for example "he",
  "she", or "they"), return the person's name only, not a work title or
  description that contains that name.
- If the context gives both a foreign-language name and an English name or
  translation for the same referent, and the question is in English, return the
  English name.
- If the context states that something "is/was a/an [proper name] [descriptor]",
  return the proper-name part and drop the descriptor noun.
- If the question is only a noun phrase, date/place fragment, or label, return the
  entity it refers to, not a sentence about it.
- If the question asks for a definition or description, return only the term being
  defined, not the term plus its generic head noun.
- If the question is a fill-in-the-blank, return the complete named phrase that
  fills the blank, including printed words when they are part of the same phrase.
- If the answer is a work with a descriptive subtitle or suffix, return the
  shortest unambiguous title.

## 4. Final check before output

Before finalizing, remove a trailing common noun that only names the kind or type
of entity (such as "Network", "Series", "Show", "Film", "Movie", "Book",
"Palace", "River", "Mountain", "Company", or "Corporation") when the question
asks for the entity itself and that noun is not needed to make the name unique.
Keep an acronym by itself when the expanded form adds only a generic descriptor.

## 5. Format the answer

- Plain text only: no Markdown, no quotes, no bullets, no links.
- No full sentences, no explanation, no hedging, no parenthetical expansions.
- No leading or trailing punctuation or whitespace.
- Return exactly one short phrase.

## 6. Always produce a final answer

Even when the question is a bare keyword or fragment, choose the most relevant
short entity from the context and return it. Do not stop after invoking this
skill; always end with the final answer.
