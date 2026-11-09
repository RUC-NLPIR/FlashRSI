# Context Question-Answering Protocol

## Reading
1. Read the full supplied context before answering.
2. Note every entity, date, number, and relationship that could be relevant to the question.
3. Treat each paragraph or bullet as a separate source that may need to be combined with others.

## Multi-hop reasoning
1. Identify the starting entity or fact mentioned in the question.
2. Find the bridge entity or relation that connects it to another paragraph.
3. Combine the two pieces of evidence before selecting the answer.
4. Check that the final answer follows directly from the combined evidence.

## Exact-span selection
1. Find the exact contiguous phrase in the context that constitutes the short answer.
2. Copy that phrase verbatim: same word order, spelling, punctuation, dates, units, and middle names.
3. Do not normalize, round, abbreviate, expand, or reorder the phrase.
4. For person/company/place answers, use the fullest exact name in the relevant sentence, not the title prefix.
5. Do not add a leading "the" or trailing descriptor (unit, parenthetical, "Conference", "citizenship") unless the question asks for that full phrase.
6. If the question expects a yes/no answer, answer with only "yes" or "no".

## Answer formatting
1. Output only the requested short answer unless the user asks for a longer explanation.
2. Do not add explanations, citations, qualifiers, or parenthetical expansions that are not part of the answer in the context.
3. If a checker asks for a revision, output only the corrected short answer copied from the context.

## Verification
1. Re-read the question and confirm the answer satisfies every constraint.
2. Confirm the answer string matches the exact wording used in the relevant context.
3. Check that the chosen span is neither a shorter title prefix nor a longer phrase with an extra leading article or trailing qualifier.
4. If uncertain, find the exact supporting sentence before finalizing.
