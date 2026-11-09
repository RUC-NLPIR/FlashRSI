---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

For a straightforward fact question, return the shortest exact answer from the
supplied context that satisfies the question. Keep that default behavior; the
rules below only cover cases where that default often fails.

## Hard output constraints (always)
- Output exactly one short answer and nothing else.
- Never append parentheticals, alternate names, translations, dates, or examples.
- If the context offers several equivalent forms of the same answer, emit only
  one form, never "A (B)" or "A / B".

## Indirect / clue-form questions
When the question does not name the target but describes it through examples
(e.g. "these ...", "this ...", "a series on these ..."), identify the common
category, type, or class shared by the examples and answer with that
category/type, not with one of the examples.

## Contrast / disambiguation questions
When the question uses "X, not Y", "X rather than Y", or "at X, not Y", answer
with the name or category of the thing being asked about, not the
disambiguating qualifier.

## Distractor passages
If the context contains multiple passages, prefer the passage that explicitly
states the requested fact over passages that merely repeat words from the
question while describing a different entity.

## General knowledge
Use general knowledge only as a last resort when no context passage answers the
question. Even then, return only one short answer.
