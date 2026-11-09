# Question Answering Skill

Use the supplied Wikipedia context as the only source of facts. Before answering:

1. **Identify the target.** Decide what kind of value is requested (person, place, date, number, yes/no, title, or short phrase). When several passages share a name, use the clues in the question to pick the correct one.
2. **Resolve the hop.** For multi-hop questions, first find the bridge entity mentioned in the question, then read the passage about that entity, then extract the final value from it.
3. **Answer exactly.** Return only the requested value in its shortest exact form, keeping the spelling, numbers, dates, and punctuation as they appear in the context. Do not add explanations, wrappers, hedges, or extra candidates unless the question asks for more than one.
4. **Binary questions** should be answered with only `yes` or `no`. If the question asks you to choose between named alternatives (for example `book or movie`), answer with the chosen alternative.
5. **Keep single values intact.** Ranges, dates, titles, and proper names are single values even when they contain `and`, commas, or dashes (for example `1899-1902`, `May 23, 2000`, `St. Louis-style pizza`). Do not split a single value into pieces.
