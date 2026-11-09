## Skill: main

# Question Answering Skill

## Task Description
Answer the user's question using only the supplied context. The question may be a full interrogative sentence, a short clue, a quoted title fragment, or a fill-in-the-blank phrase. Return only the short answer.

## Interpreting Short Clues
- A short clue may be a single word or phrase rather than a complete question. Use the context to determine the expected answer class and relation.
- If the clue is only a bare place name, treat it as asking for the enclosing place or location identifier supported by the context, usually the state/province/region in which the place is located.
- Do not return the queried place name itself or a longer document title that contains it merely because that title appears first or frequently in the context.

## Output Format
- Return only the short answer phrase.
- Do not include explanations, evidence, full sentences, quotation marks, or extra punctuation unless it is part of the answer.
- Use the minimal precise form of the answer as supported by the context.
- If the question already mentions part of a title, name, or descriptor, omit that part from the answer only when the remaining words still form a complete, unambiguous answer.
- For fill-in-the-blank questions, return only the missing text; do not repeat any visible portion of the phrase.
- For people, prefer the shortest commonly used identifying name from the context, but retain an honorific or title when it is part of the explicit answer provided in the matching context, such as a direct clue-answer pair or a canonical full name.
- For works, groups, or other entities, prefer the short title or common name over a longer article title or full formal title, unless the question or direct answer context requires the full title.
- For company or organization names, prefer the shortest distinguishing name that is unambiguous in the context. If the question already identifies the entity's type or industry, do not repeat that type or industry as part of the answer unless it is essential to the proper name.
- For location answers, return the shortest appropriate geographic unit requested by the clue. For a bare place-name clue, return only the enclosing state/province/region, not the queried place or a longer compound place name.
- Ignore document markers such as [DOC], [TLE], and [PAR] when forming the answer.
- For "this [descriptor] [category/noun]" clues, return only the specific core term or shortest complete answer. Do not repeat a descriptive adjective or category noun already given in the clue when the remaining word or phrase is a complete answer.

## Strategy
- First, parse the question carefully and identify every constraint in it: the expected answer class, key descriptors, and any process step or relation described.
- Treat the expected answer class as a hard filter. If the question says "acid," the answer must be an acid; if it says "alkali," the answer must be an alkali. Do not switch classes merely because a descriptive word overlaps with another candidate's name.
- For a short clue that is a single name or phrase, determine what the clue is asking about before selecting an answer. For a bare place name, identify the enclosing location from the context rather than repeating the place name or selecting a longer title containing it.
- Locate the context passages that satisfy all the clues, not only the most eye-catching term. For multi-step processes, align the question with the correct step or agent.
- Match the entity or title that directly satisfies the question and is explicitly supported by the context.
- Prefer the shortest exact form that is unambiguous in the supplied context, but do not shorten a title or honorific when the source uses that titled form as the direct answer.
- Before finalizing, re-read the question and check whether the answer contains words already given in the question. The question may include a descriptor or category word that should not be repeated. Remove only redundant words that are safe to drop; never strip essential category words, compound-name words, or titles if doing so would make the answer incomplete or change its type.
- If the context contains both short and long forms of the same name or title, choose the short form that still fully answers the question, unless a direct clue-answer context explicitly supplies the longer or titled form.
- Avoid adding extra names, dates, titles, or descriptive phrases beyond what the question asks for.
- Base the answer only on the supplied context; do not introduce outside knowledge.

## Structured Clue-Answer Contexts
- When context contains pipe-separated or otherwise structured quiz-style lines, such as `category | clue | answer`, treat the question as matching the clue portion.
- If the clue portion matches the question, return the answer portion exactly as written, including honorifics, titles, punctuation, and full names.
- Do not shorten the answer portion merely because a shorter form of the same entity appears elsewhere in prose or in another document.
- If the structured answer is already a direct complete answer, it should take precedence over a shorter form inferred from other passages.

## Learned Rules and Revisions
- For named works or entities, actively search the context for a shorter or common name, not just the longest title. If the context gives both a full formal title and a shorter standalone name in quotes or running prose, return the shorter standalone name unless the question explicitly asks for the full title.
- In descriptive clues such as "X and Y star in this ..." or similar "this ..." phrasing, the answer is only the entity name or title, not a full sentence, description, or longer formal title.
- For Jeopardy-style clues phrased as "one of these ..." or "these ...", do not automatically pluralize the answer. Prefer the singular common noun or class term unless the context clearly requires a plural or the answer is a plural-only proper noun.
- Do not assume frequency equals correctness: a longer title appearing often in document titles should not override a shorter common title explicitly used for the same entity.
- Exact answer matching is strict; avoid unnecessary pluralization, subtitles, descriptive tails, or repeated category/industry suffixes when the context supports a shorter or singular form.
- Bare place-name clues: If the question is only a place name, return the enclosing state/province/region or other directly implied location identifier from the context, not the place name itself or a longer title containing it. Do not return a document title such as "Place-Suburb, State" when the context supports the state alone.
- For people, do not drop a title or honorific when the matching context directly gives that titled form as the answer. A shorter name appearing elsewhere in the context is not a reason to shorten the direct answer.
- For company and organization names, if the question already identifies the entity's type or industry, treat that category as already given. Strip a repeating type/industry suffix from the answer and return only the distinguishing proper name. Example: if the clue is "this satellite radio company" and the context supports both a longer name ending in "Satellite Radio" and a shorter brand name, return the shorter brand name.
- This suffix-stripping rule applies to prose contexts. A structured clue-answer context may explicitly supply a fuller name, and that fuller structured answer should still take precedence.
- For "this [descriptor] [category/noun]" clues, do not return the full descriptive phrase if the descriptor is already present in the question. In particular, if the question asks for a structure or object using a descriptive modifier such as "funeral structure," and the context contains a phrase like "funeral pyre," return only the core term "pyre," not "funeral pyre."
- The same principle applies to any descriptive modifier that merely restates the clue: strip the repeated descriptor and return the distinguishing term alone when it remains a complete, unambiguous answer.

## Fill-in-the-Blank and Partial Title Questions
- If the question is a quoted fragment containing an ellipsis, such as `"... X"`, `"X ..."`, or `"... X ..."`, treat it as a fill-in-the-blank request. Return only the missing words that replace the ellipsis.
- Do not return the visible words as the answer, even if several context documents contain those visible words as a complete title or phrase.
- Use the ellipsis position to determine where the missing text belongs:
  - Leading ellipsis (`"... X"`): the visible text is the end of the target phrase; supply the immediately preceding missing words.
  - Trailing ellipsis (`"X ..."`): the visible text is the start of the target phrase; supply the following missing words.
  - Ellipsis between visible text: supply the missing interior words.
- Candidate context entries must contain the visible text in the correct position. Prefer the entry whose title or phrase matches the visible fragment exactly, including capitalization and punctuation, and has the visible fragment at the correct boundary of the core phrase.
- If several context entries contain the visible text, do not choose a standalone exact-match title when the ellipsis signals that the visible text is only part of a longer phrase. Choose a longer phrase that fills the missing slot.
- Output only the missing text exactly as it appears in the context, preserving proper noun capitalization and word order.

## Domain Notes and Clarifications
- In chemistry, "caustic" can mean corrosive or burning; it can describe strong acids as well as strong bases. Do not assume "caustic" always refers to an alkali such as caustic soda or lye.
- In hot-dip galvanizing or metal surface preparation contexts, alkaline/caustic cleaning typically uses sodium hydroxide/caustic soda/lye, while acid cleaning/pickling uses hydrochloric acid or sulfuric acid. If the clue explicitly says "acid," the expected answer is the acid pickling agent, not the alkaline cleaner.
- When multiple acids appear in the context, choose the one that the context directly says is used in the cleaning/dipping/pickling step, especially if it is described as dilute or ambient, rather than one mentioned only as an alternative or under a different condition such as heated.
- Do not let a prominent clue word such as "caustic" override another explicit category word such as "acid." Match the complete clue, not just a single overlapping word.
- In entertainment or trivia contexts, prefer singular common nouns for "one of these" category clues, and prefer short common titles over longer formal titles with subtitles, unless a direct clue-answer context gives a complete titled form.
- In mythology, history, and general trivia, a clue describing a structure used for burning a body, such as a "funeral structure," expects the one-word term "pyre" when the context supports it. Do not include the descriptor "funeral" because the clue already supplies that meaning.
