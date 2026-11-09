# Question Answering Skill

## Answer format
- Return the shortest answer span that is directly supported by the supplied
  context. Do not add explanations, full sentences, or trailing punctuation
  unless the answer span itself requires them.
- Match the question's vocabulary to the context's vocabulary. If the question
  offers a coarse choice such as "book or movie", prefer the specific category
  term used by the context (for example "novel", "book", "film", or "movie")
  instead of a generic term the context does not support.

## Evidence completeness
- Before answering that a requested value is not present, scan every supplied
  passage, not only the first passage about the target entity. Other passages
  may mention the target entity, an alias, or a co-referent entity and contain
  the answer.
- Resolve pronouns and demonstratives such as "this story", "this", or "it" to
  the most specific antecedent supported by the supplied context.

## Multi-hop
- If the target entity's own passage lacks a requested value, check all other
  passages that mention the target or a related entity before concluding that
  the answer is absent.
