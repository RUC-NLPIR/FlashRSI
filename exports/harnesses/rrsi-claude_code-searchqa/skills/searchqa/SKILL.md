---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

## Learned rules

### Answer selection
1. Answer from the supplied context only. Do not use web search or outside knowledge unless no document contains a usable clue.
2. Prefer the direct, specific clue in the context over broader background. If the question asks "this type of X" and one document states the question's key terms together with a specific answer phrase, return that specific phrase rather than a general category found in other documents.
3. When the question is only a name, list, or topic with no explicit interrogative, return the fact the context attaches to it — a place, role, category, source work, or other label — choosing the most specific attached fact over a broad shared label. Do not infer an answer type from the question's surface form; let the context decide what kind of fact the answer is. Never return a full sentence or biography.

### Pronouns and declarative clues
4. When the question is a declarative sentence with a pronoun (he, she, they, his, her, its, this, these) and no wh-word, resolve the pronoun to the person or entity named in the context sentence that matches the event, and return that name. Do not answer with the document title or the described object. If no context sentence matches the event, return the named person or entity in the context that is the grammatical antecedent of the pronoun; never default to a document title or an outside-memory name.

### Truncated or partial quotes
5. When the question is a truncated or partial quote (it contains `...` or is a short quoted fragment), match the exact fragment to a document title or sentence in the context, then return the missing word or words from that title or sentence. Do not anchor on a frequent document that merely shares the fragment.
6. If more than one title or sentence completes the fragment, prefer the shortest completion that uses the fragment as an exact suffix with no continuation after it; then prefer a plain title over a lyrics page, lyric-line title, or title with extra descriptors. If none is an exact suffix, return the completion with the fewest extra words. Never default to the most familiar completion.
