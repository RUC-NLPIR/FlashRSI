# Question Answering Skill

## Learned output-format rules

1. Return only the short answer: the requested entity, value, or completed
   phrase. Do not wrap the answer in a sentence, an article plus noun phrase,
   a parenthetical, or trailing punctuation.
2. When the question is a fill-in-the-blank, output the complete phrase exactly
   as it appears in the supplied context, including the words on both sides of
   the blank. Do not output only the missing word.
3. Prefer the shortest exact name or alias used in the supplied context for the
   requested entity. Do not substitute a longer title when a shorter form is
   used in the evidence.
4. Preserve exact spelling, capitalization, numbers, and dates from the
   evidence. For a person, copy the full name exactly as written. Never insert
   parentheses or a middle name that is not already present in the evidence.
   Prefer the shortest complete ``First Last`` form when both a two-word name
   and a longer name are present. Use a parenthesized form only when the
   evidence itself contains that exact parenthesized form.
5. If a clue or question already contains part of the answer, do not repeat
   that part in a longer descriptive phrase; answer with the requested slot.

## Incomplete or malformed question recovery

6. If the user's question has no explicit interrogative word (who, what, when,
   where, why, how, which, whose), no question mark, and no blank, treat it as
   an incomplete question and infer the requested slot from the context:
   - a bare person/entity name: answer the associated fact stated about that
     entity (for example the country, role, or title), not the name itself;
   - a quoted slogan or phrase: answer the person or entity the context
     associates with that phrase;
   - a declarative sentence with a pronoun (he/she/it/they): answer the
     person or thing the pronoun refers to;
   - a declarative sentence that contains a year or date but does not ask for
     it: do not answer the year/date; resolve the pronoun or subject instead;
   - missing spaces or concatenated words: split at the most likely word
     boundary and infer the requested slot.
   Return only the short answer as in rules 1-5.
