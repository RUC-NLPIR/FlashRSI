# Question Answering Skill

When the user asks a short-answer question with supplied context:

- Output only the answer value. Do not add explanations, lead-in phrases
  (e.g. "The answer is"), full sentences, markdown, quotes, or trailing
  punctuation.
- Do not include parenthetical alternatives, examples, dates, or source
  snippets in the final answer.
- Keep proper names and titles complete. Do not drop words such as "Lake",
  "Mount", "Fort", "The", "New", "San", or a person's first name.
- Prefer the exact wording used in the supplied context for the target.
- If the question asks for a common noun or category, answer with that noun
  phrase rather than a sentence.
- If the context is noisy or seems incomplete, give the best short answer
  supported by the context; do not answer "the context does not mention..."
  or similar.
