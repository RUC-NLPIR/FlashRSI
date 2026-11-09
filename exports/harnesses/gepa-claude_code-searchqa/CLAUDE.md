# searchqa Guidance

## Mandatory first step
Before answering each question, invoke the Skill tool with skill `flashrsi:searchqa` and follow that skill. If the skill returns learned rules, apply them. If it returns no learned rules, use the guidance below.

## Input format
Most tasks are short-answer question-answering tasks from supplied context:
- A user instruction line often says: `Answer the question using the supplied context. Return only the short answer.`
- A `Context:` section contains documents delimited like `[DOC] [TLE] ... [PAR] ...`.
- A final `Question:` line contains the query or clue.

## Task objective
These tasks are scored by exact match against a reference string. A semantically similar answer with different surface spelling, diacritics, punctuation, spacing, or extra words is usually wrong. Return the answer string exactly as required by the context and question.

## Question type detection
Classify the final `Question:` before searching for evidence:
- Explicit question: if it is a complete interrogative such as `Who...?`, `What...?`, or `Which...?`, answer the entity or term that question requests.
- Definitional clue: if it asks `Term for X`, `What is the name of X`, or similar, answer the defined term.
- Bare quotation or first-line clue: if the question is only a quoted phrase, line, lyric, or sentence with no interrogative, treat it as an attribution clue. The expected short answer is usually the person credited with those words in the supplied context, not the title of the work and not the subject of the quote.

## Answering procedure
1. Read the user's requested output format and obey it exactly. If the instruction says `Return only the short answer`, output only the answer: no explanation, citation, punctuation, commentary, or extra prose.
2. Extract the answer from the supplied context, not from outside knowledge.
3. Identify the strongest evidence line for the question. For definitional clues such as `Term for X`, `What is the name of X`, or `What is the term for X`, prefer a context line that directly defines a term, especially:
   - Glossary-style entries like `TERM - definition` or `TERM: definition`.
   - Direct defining sentences like `A/An TERM is ...` or `TERM is ...`.
4. Choose the shortest, most direct defined term that fills the clue. Do not expand it into a longer descriptive phrase, article title, or related phrase with an extra modifier unless the strongest evidence line itself defines that fuller form as the term.
5. Do not treat a document title as the answer merely because it contains a relevant phrase. Titles are often broader or more specific than the expected short answer. Prefer the term from a glossary-style definition or a direct definitional sentence.
6. If a glossary-style line defines a bare term and another line or document title uses a longer name, the bare defined term is usually the better exact-match answer.
7. Preserve the exact wording of the answer as it appears in the strongest evidence line. Normalize all-caps glossary entries to ordinary lowercase unless the requested format or proper-noun rules require otherwise.
8. Keep small function words and articles that belong to the answer. If the answer is a singular countable noun and the natural short-answer form includes `a`/`an`/`the`, include that article; do not drop it.
9. If multiple surface forms occur in the context, use the most direct, concise label from the clue-bearing definition rather than a longer description elsewhere.

## Attribution and bare-quote questions
For a question consisting only of a quoted passage, poem line, lyric, or phrase:
- Find the context line or document that contains the quoted wording.
- Look in that same document for an explicit credit or byline: `by NAME`, `Author: NAME`, `Lyricist: NAME`, `Creator: NAME`, `Poet: NAME`, or a title of the form `Work by NAME`.
- Output the credited person's name as the short answer, not the title of the work. The quotation is evidence for the source; the expected answer is usually the attribution.
- If the quoted words are a poem line or lyric and the context separates roles such as composer and lyricist, output the author of the words (poet/lyricist), not the composer, performer, or title.
- If a document title is of the form `Work by NAME`, extract only the `NAME` portion for an attribution clue. Do not return the `Work` portion alone.
- Prefer the name in ordinary prose/byline order (`First Last`) over inverted metadata order (`Last, First`) unless the question wording specifically matches the inverted form.
- If the same person appears with multiple spellings or forms, choose the form from the clearest attribution line or title, and keep exact spelling as printed in that context.

## Exact surface form and spelling
- Use the answer exactly as printed in the supplied context. Do not restore accents, diacritics, or native-language spellings that are absent from the context.
- If the context gives an ASCII transliteration, OCR spelling, or simplified spelling of a name, use that spelling rather than a canonical outside-world spelling.
- Do not convert names or terms to a more formal or non-English form based on external knowledge, even if the supplied form appears incomplete or less correct.
- If the same name or term appears with multiple spellings, prefer the spelling from the strongest evidence line, then the spelling that best matches the question's own wording.
- Treat accented and unaccented characters as distinct for exact-match purposes. Only output accented characters if the context contains them in the answer-bearing phrase.

## Using the question wording
- Treat words such as `this`, `that`, `it`, or `these` in the question as slots the answer must fill. The answer should fit that slot after the question's modifiers are applied.
- For a clue phrased as `the [specific/regional/named] type of this`, answer with the general category or base noun, not the specific named variant. The modifier is part of the clue, not part of the answer.
  - Test: `the [specific] type of [answer]` should read naturally. If including the modifier makes the phrase redundant (`the [specific] type of [specific] [answer]`), remove the modifier.
- If the question asks directly for a named variant, include that variant in the answer. If it asks through a `type of this` construction, do not.
- A document title or example that mentions a specific variant is weak evidence for the base category. Use a definition or direct statement that shows the base term as the category.
- If the question is not an interrogative but a bare quotation, do not use the title of the quoted work as the answer unless the question explicitly asks for the title or work name.

## Choosing among multiple context forms
- Prefer evidence in this order:
  1. A glossary/dictionary-style definition line: `TERM - definition`, `TERM: definition`.
  2. A direct defining sentence such as `A/An TERM is ...`.
  3. A clue-bearing sentence using the same wording as the question.
  4. Document titles and broad topic labels, which are lower priority.
- For bare-quote attribution questions, the strongest evidence is a line or title that explicitly pairs the quoted work with a person (`Work by NAME`, `Author: NAME`, `Lyricist: NAME`). The name is the answer; the title alone is not.
- A line that merely repeats the question text is not evidence for the answer unless it also states the answer.
- Do not allow a related but longer phrase to override a concise, direct term from a definition line.

## Failure patterns to avoid
- Expanding a short context answer into a longer name or a named variant.
- Choosing a document title or broad topic label instead of a direct definitional term or a requested attribution.
- For a bare-quote question, outputting the work title or subject instead of the credited author/creator.
- In a `Work by NAME` title, outputting the `Work` portion when the question is a bare quote asking for the attribution.
- Including a modifier, regional name, or specific variant when the question asks for the general category via `this` or `type of this`.
- Dropping articles or determiners from the answer.
- Adding diacritics, accents, native spellings, or other surface forms that are not present in the supplied context.
- Treating high semantic similarity as success; exact-match tasks require the exact reference string.
- Adding explanations or citations when the instruction says to return only the short answer.
- Outputting extra whitespace, punctuation, or quotes around the answer.

## Final check
Before finalizing, compare your answer with the strongest context phrase and the requested format. Verify that every character of the answer matches the context's spelling, including diacritics or lack thereof. If the instruction says `Return only the short answer`, your entire reply must be that short answer, with no extra text or punctuation. For `type of this` clues, substitute the answer into the question and verify that it names the general category, not a specific variant. For bare-quote attribution clues, verify the answer is the credited person's name, not a work title or subject.
