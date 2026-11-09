---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# SearchQA Answering Rules

## Goal
Return the exact short answer from the supplied Wikipedia context. The final
message must be only the answer: no reasoning, no preamble, no markdown, no
"Answer:", no explanation, no hedging.

## Procedure

### 1. Resolve the target
- Identify the answer slot from the question: `who` -> person, `where` -> place,
  `when`/`what year` -> date or year, `which`/`what` -> entity or category,
  `how many`/`how much` -> quantity, yes/no -> `yes` or `no`.
- Resolve pronouns and demonstratives (`this story`, `the mount`, `it`) by
  matching the rest of the question to the strongest context entry. Do not jump
  to a merely similar entity.
- For multi-hop questions, use the bridge facts. If the first entity's paragraph
  lacks the requested attribute, follow the named relation to the linked
  paragraph and use the evidence sentence there.
- If the question gives two or more required properties, accept a candidate only
  if it satisfies every property. Reject a candidate that satisfies one property
  but lacks another, and keep looking.
- For `this story` in a `book or movie` question, prefer the context entry whose
  first sentence defines the work itself with a medium (`a volume in the ...
  novel series`, `a ... novel`, `a ... film`) over a biography that only says a
  person's story `inspired` an adaptation.

### 2. Extract the evidence phrase
- Find the shortest continuous phrase in the relevant context sentence that
  directly fills the answer slot.
- Keep the context's exact wording, spelling, diacritics, and number/date format.
- If the requested answer is a predicate, clause, or definition, copy the
  complete clause from the context instead of paraphrasing or shortening it.
- If the evidence value is a range, keep the whole range (`185,000 to
  190,000 m³`), not just the first number.
- For a `who` question, prefer the sentence that supplies the specific event
  or relation asked about, and copy the name exactly as printed there. If that
  sentence uses only a pronoun, use the entity's first sentence. If the event
  sentence describes the person with a different role than the question (for
  example, the question says `English comedian` but the event sentence says
  `actress`), use the entity's first sentence, whose description matches the
  question. Do not expand a name beyond the form used in the chosen evidence
  sentence.
- For `What notable act did X do?` / `What is X credited with?`, keep the whole
  evidence sentence, including the subject and the trailing purpose clause
  (`He is credited with disabling German explosives placed to destroy a vital
  bridge to delay allied liberation.`).

### 3. Answer-format rules
- Yes/no questions: output only `yes` or `no`.
- `book or movie` / media questions: identify the work the question refers to.
  Prefer the context entry whose first sentence defines the work itself with a
  medium (`a volume in the ... novel series`, `a ... film`, `a ... novel`) and
  answer with that medium (`novel`, `book`, `film`, `movie`). Ignore adaptation
  mentions in a biography (even the subject's own) when a work entry states the
  medium.
- Comparison/choice questions: output only the chosen entity's name exactly as
  written in its context entry.
- For `Who was born later/earlier` or `Who died earlier/later` comparisons, copy
  the chosen person's name exactly as printed in the first sentence of their
  context entry, including middle names (`Lee Earle "James" Ellroy`).
- For `who` / `what man` / `what woman` questions that identify the person by
  membership in a named duo or group (`part of the duo Simon & Garfunkel`), copy
  the full personal name from the person's own context entry first sentence
  (`Paul Frederic Simon`), not a shorter form used in another entry.
- `what kind/style/genre` questions: output only the category label or
  descriptive quality.
  - For `What style of film is X?`, output only the core genre from the work's
    definition, dropping seasonal/geographic/audience modifiers that are not the
    genre itself. `a 2016 American Christmas comedy film` -> `comedy`. Keep
    compound genres such as `romantic comedy`, `science fiction`, `dark fantasy`.
    This overrides the generic head-noun rule for film-style questions.
  - If the category label is a compound noun phrase with its own head noun
    (`no-kill shelter`), keep the full phrase.
  - If the question already contains that head noun (`film`, `films`,
    `guitar riffs`), output only the modifier(s) (`comedy`, `horror`,
    `heavily downtuned, mid-paced`).
  - If the question asks `what kind/type of <category>` and the context contains
    a dedicated entry whose title is the kind being asked about (`No-kill
    shelter` for a question about a kind of animal shelter), answer with that
    entry title verbatim (`no-kill shelter`). This overrides the compound-label
    and head-noun rules when both apply.
- `which type/kind of X` questions that ask for a named variety: keep the full
  type name as written (`St. Louis-style pizza`).
- `What are X and Y?` questions asking for a common category: output the
  singular category word (`opera`, `game`), not a plural and not examples.
- `Who is/was X?` questions asking for a definition: output the short
  descriptive phrase that follows `is/was` in the context, without the person's
  name and without the leading article (`Punjabi language Bhangra
  singer-songwriter`). If the question asks for a person's identity in an event
  or role, output the name instead.
- `from where to where` questions: copy the full phrase exactly, starting with
  `from` and including the `to ...` part (`from the South Para Reservoir in the
  north to the Mount Bold Reservoir in the south`).
- `how many`/`how much`/population/date questions: output the number or date
  exactly as written, preserving the context's format (`four`, `19th`,
  `25,216`) and keeping ranges and units when present (`185,000 to 190,000 m³`).
- `how high` questions: when the only supported height evidence is a full
  sentence about a linked mountain or peak, copy that sentence rather than just
  the number.
- `What sport does/do X participate in?`: if the context describes the person
  with a role phrase such as `World Cup alpine ski racer`, output that exact role
  phrase (`alpine ski racer`), not a generic sport name.
- Fill-in-the-blank questions such as `women's ____?`: output only the missing
  word (`rights`), not the words already present.
- Award/prize questions: output only the core award name. Remove any leading
  conferring organization or initials (`ICC`, `BAFTA`, `Academy`, `Nobel`) and
  remove a trailing `award`/`awards` when the question already contains the word
  `award`. Context `three consecutive ICC Umpire of the Year awards` ->
  `Umpire of the Year`.
- Treaty/agreement/act questions: copy the full title exactly as printed in the
  evidence sentence, including a leading `The` and a trailing year if they appear
  (`The Oregon Treaty of 1846`).
- Company/organization/studio/distributor questions: copy the full proper name
  used in the evidence sentence, including suffixes such as `Films`, `Pictures`,
  `Studios`, `Company`, and `Inc.` (`Miramax Films`, not `Miramax`), unless the
  evidence sentence itself uses a shorter official name as the primary form.
- College/university questions: when the context lists multiple variants of the
  same institution (`Harvard Business School`, `Harvard University`), answer with
  the common base name (`Harvard`). Otherwise use the institution's full proper
  name.
- Place questions: if the question asks `where` or for a base/location, copy the
  complete place phrase used in the evidence sentence (`Yarmouth, Maine`;
  `John F. Kennedy International Airport, New York`). If the question asks for
  the name of a venue or entity, output only that name (`Old Trafford`), not the
  surrounding address. Do not append a containing state/country that the
  question already names unless it is part of the place's full proper name.
- `part of what country/state/county` questions: when the question asks what
  larger unit a region (county/province/district) is part of, use the most
  specific unit named in that region's own context entry (`County Londonderry` ->
  `Northern Ireland`), not a broader or historical term found in another entry
  (`United Kingdom`, `Ireland`).
- Singular `who` questions: if the evidence clause names several people, output
  only the first named person directly involved; do not append the rest of the
  list.

### 4. Final trim
Remove:
- reasoning, preamble, and phrases like "The answer is";
- markdown such as `**bold**` or bullets;
- parenthetical alternatives (`Pastafarianism (the Church of the Flying
  Spaghetti Monster)` -> `Pastafarianism`);
- unnecessary articles, prepositions, and trailing punctuation;
- words already present in the question unless they are part of a proper name or
  an exact quoted phrase.

### 5. Do not answer "not stated"
The supplied context set is the evidence. If the target paragraph alone lacks
the requested value, follow the explicit named relation to another paragraph and
use the supported evidence sentence there. Prefer an evidence-backed answer over
giving up.

## Format examples
- `George Bradburn and Lydia Maria Child were both in favor of women's ____?` -> `rights`
- `... a tragic play in how many parts?` -> `two`
- `What number of President was Rutherford B. Hayes?` -> `19th`
- `How many Grammy awards did Sam Smith win in 2015?` -> `four`
- `What was the population at the 2010 census ...?` -> `25,216`
- `Are Bicycling and Dine both American magazines?` -> `no`
- `What are Carmen and Un ballo in maschera?` -> `opera`
- `After appearing in his first Cricket World Cup final in 2007, what award did Aleem Dar of Pakistan win for three consecutive years from 2009 to 2011?` -> `Umpire of the Year`
- `What treaty ended disputed joint occupancy of the region where Reverend Gustavus Hines was a missionary?` -> `The Oregon Treaty of 1846`
- `The Weinstein Company ... retained ownership of Dimension Films after leaving what film distributor?` -> `Miramax Films`
- `What notable act did Jan van Hoof do during the Dutch resistance?` -> `He is credited with disabling German explosives placed to destroy a vital bridge to delay allied liberation.`
- `North Shore Animal League America is the largest example of what kind of animal shelter and protection organization?` -> `no-kill shelter`
- `Works by what man, who was part of the duo Simon & Garfunkel, were included in the 1967 Joan Baez album, Joan?` -> `Paul Frederic Simon`
- `What style of film is the Office Christmas Party?` -> `comedy`
- `Was this story made into a book or movie?` -> `novel`
