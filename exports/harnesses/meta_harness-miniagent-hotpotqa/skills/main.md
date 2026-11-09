# Question Answering Skill

Use these rules when answering questions from supplied evidence.

## Evidence search

1. Read every paragraph before answering. Multi-hop answers often require two
   different paragraphs, and the final evidence may be in a paragraph that is
   not the first one about an entity.
2. When an entity is mentioned in several paragraphs, check all of them before
   concluding the evidence is missing. If another paragraph states the fact,
   use it.
3. Do not use external tools when the evidence is already supplied in the
   prompt. The supplied context is sufficient for the answer.
4. Prefer exact wording from the evidence. The correct answer is usually a
   verbatim span of the supplied context.

## Answer format

5. Return only the answer value: no restatement of the question, no reasoning,
   and no markdown.
6. Match the answer span exactly as it appears in the evidence.
   - If the evidence answers with a short phrase, return that short phrase.
   - If the evidence answers with a full sentence, return that full sentence;
     do not cut a sentence answer down to a bare number or noun.
   - For questions asking `from where to where`, include the complete
     `from ... to ...` phrase exactly as written.
7. Yes/no questions: answer exactly `yes` or `no`. If a question gives
   alternatives (`Was it a book or movie?`), answer with the correct
   alternative, not `yes` or `no`.
8. Year, date, and number questions: preserve the exact words, digits, units,
   ranges, and thousands separators from the evidence. Do not convert words to
   digits or digits to words unless the evidence uses that form.
9. Person questions: use the name exactly as it appears in the part of the
   evidence that answers the question. Do not automatically expand a common or
   professional name into a longer legal name, and do not automatically shorten
   a fuller name; match the evidence span for the answer.
10. For category questions (`What genre ...`, `What style ...`, `What kind ...`),
    answer with the shortest complete category phrase from the evidence. Drop
    generic added words such as `film`, `films`, `movie`, `novel`, or `book`
    when they are not part of the answer, but keep a required head noun such as
    `shelter` in `no-kill shelter`.
11. For official titles, awards, places, and measurements, return the exact
    answer phrase as written. Include a subtitle or location only when it is
    part of the answer itself; do not add generic words such as `award` or
    `prize` unless the evidence's answer phrase uses them.
12. Do not add parenthetical expansions, alternative names, or acronyms. If the
    evidence contains an answer and a parenthetical aside, return the main
    answer phrase.
13. If the question asks for one person and the evidence names several people
    joined by `and`, return only the first named person.
