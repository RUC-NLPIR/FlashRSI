# Extractive QA Skill

Use this process whenever the user supplies a context and asks for a short
answer.

1. Read the question first, then scan the supplied context for exact supporting
   strings. The context is evidence; do not silently substitute outside
   knowledge.
2. In the context, document titles usually appear after `[TLE]` and snippet
   text after `[PAR]`. Some snippets are trivia/Q&A lines of the form
   `CLUE | ANSWER`; in that case the expected short answer is the text after
   the vertical bar.
3. Decide what kind of answer the question asks for:
   - If it asks for a category (a country, state, city, sport, language, etc.),
     return that category even when the clue names a more specific entity.
   - If the question is only a title, name, or phrase, infer the hidden
     category from the context: a state park title asks for its state, a
     company/weapon name often asks for its country, a person's name often asks
     for a related person or role.
   - If the clue quotes a line of dialogue, answer the work, not the character,
     unless the clue explicitly asks for the character.
   - If the clue is a quotation and asks what it exemplifies, answer the broad
     category (language, nationality, etc.), not the speaker.
4. Produce the shortest answer that satisfies the question. A single name,
   number, date, or short title is better than a phrase or sentence. For a
   named entity, drop a trailing common-noun descriptor; for a city, do not add
   its state or country unless the question asks for that larger place.
5. If your first draft is a sentence or description, reduce it to the entity or
   short phrase the question is actually asking about.
6. Strip markdown, surrounding quotes, trailing punctuation, years, subtitles,
   and descriptive parenthetical qualifiers, but keep parenthesized words that
   are part of the context's exact answer.
7. If evidence is weak, give the single most likely short answer anyway; do not
   explain uncertainty.
