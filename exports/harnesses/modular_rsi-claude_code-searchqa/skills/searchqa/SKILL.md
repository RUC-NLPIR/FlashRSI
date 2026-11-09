---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

## 1. Bind the answer to the clue's target

Before answering, identify the exact entity the question asks for and the
grammatical object/entity type it requests. Decide whether the clue asks for a
term, a person, a country, a date, a missing word, a work title, a book, a
truth value, an event, an organization, a specific named figure, a group of
people or things, a specific category or type of things, or some other specific
type. Return only that entity, as supported by the supplied context. Do not
return a truth judgment, echo a named entity from the clue or context, or
substitute an associated/related phrase when the clue asks for a different
target. Do not substitute or return an associated title, date, location,
relationship, a similar item from the context, or any similar-but-unrequested
fact.

Before finalizing, parse the clue to determine the exact entity type and
grammatical object being requested (e.g., person vs. work title, book vs.
truth value, specific named figure vs. associated figure, group of people vs.
the title of a work about them, show vs. episode/subtitle, character vs. actor,
figure vs. formula, author vs. truth value, phrase vs. associated person,
requested event vs. another event from the same period, organization vs. the
type of people or businesses that formed it, category vs. an organization
associated with it). Verify that the chosen answer satisfies the whole clue and
matches the requested type, then return only that entity rather than an
associated title, descriptor, truth judgment, person, formula, event,
organization, or related named entity from the context.

When the clue asks for a category or group, return the exact grouping named or
supported by the supplied context, not a broader, modern, or related grouping
(e.g., return the context-supported group "Scandinavia", not the related but
different "Nordic countries"). When the clue asks for a person, return the
person, not an associated campaign year, event, or related fact.

When the clue asks for an event, return the exact event the clue requests as
supported by the supplied context, not a different event from the same period,
place, or context. When the clue asks for a type or category of things, return
that type or category, not the name of an organization or alliance formed by
those things, and not another named entity associated with them. When the clue
asks for an organization by name, return that organization, not the broader
category it belongs to or the members that formed it.

When the clue asks for a group of people or things described by a work or
title, return the group itself, not the title of the work about them. When the
clue asks for a specific named figure, return that named figure, not another
named figure that merely appears nearby in the context or is associated with
the same event or institution.

When the clue asks for a person, group, title, book, or other named entity,
return that entity's name itself, not a truth judgment about it (e.g., "True"
or "False") and not a description of what kind of thing it is (e.g., a "tribute
act" or other associated descriptor). The grammatical object is the answer:
if the clue asks who or what, supply the requested name as supported by the
context, not an evaluation or paraphrase of it.

Before finalizing, re-read the clue and verify that the chosen answer satisfies
every part of it. Distinguish between superficially related context entities:
a site vs. a building at that site, a generic role vs. a named individual,
a source vs. its energy form, a person vs. an associated date or event, a
missing fragment vs. a visible title, a person vs. the work they produced,
a work title vs. the people or things that work describes, a character vs. the
actor who played them, a show vs. one of its episodes or subtitles, a specific
named figure vs. another figure mentioned nearby, a requested event vs. a
different event from the same context or period, a type or category of things
vs. the organization or named group associated with it, and an entity vs. a
truth judgment about it or a description of it. When several context entities
are superficially related, return only the one that matches the grammatical
request, not the first or nearest associated entity.

Before finalizing, parse the clue to identify the exact entity type and the
grammatical object it requests, and verify that the candidate satisfies the
whole clue and matches that type. For wh- clues (who, what, which, or where),
return the requested entity itself, never a truth judgment about it. Do not
substitute an associated example for the product type or category the clue
defines, a related organism or part for the exact thing the clue asks about, or
a broader generic category for the precise target the supplied context
supports.

Examples of bound targets: "this city", "Marquess of this", "this film",
"this title", "this book", "these animals", "one of these holes", "this
person", "this work", "this character", "this show", "this phrase", "this
event", "this organization", "this type/category of things", or "this named
figure" each names a specific entity and form; return exactly that target.

## 2. Return only the shortest exact answer phrase

After selecting the answer, normalize the output so only the shortest phrase
that satisfies the clue remains:

- Match the number/form of the grammatical request (for example, singular for
  "one of these", plural for "species of these" or "these animals"), and choose
  the term form that the clue and context support over a derived or longer
  descriptor (e.g., "hydroelectricity" rather than "hydroelectric power",
  "Bull Moose" rather than "Bull Moose Party", "Massachusetts" rather than
  "Senators from Massachusetts").
- Strip markdown formatting and emphasis.
- Remove full sentences, explanations, hedging alternatives, and explanatory clauses.
- Remove verb-phrase fragments and other non-answer material.
- Remove appended proper nouns, event phrases, and verb clauses that go beyond
  the requested moniker, term, person, or place.
- Remove unnecessary descriptors, leading articles, and punctuation unless they
  are part of the requested answer phrase.
- Remove unrequested noun descriptors that turn the requested base term into a
  longer noun phrase (e.g., return the requested style/term/type alone, not
  "term + home/object/other category noun"), unless that noun is part of the
  proper or official name the clue asks for.
- Remove over-specific qualifiers when the clue asks for the shorter or more
  general target; keep a qualifier only when it is part of the required
  proper/official answer phrase.
- Remove corporate suffixes and unrequested title or descriptor words when the
  clue asks for the underlying entity rather than the full title or corporate
  name (e.g., "Sirius Satellite Radio" -> "Sirius", "Sultan of Brunei" ->
  "Brunei", "Hallmark Cards" -> "Hallmark").
- Use the shortest name form that matches the clue's expected usage: remove
  unnecessary middle names, initials, honorifics, and added titles, but when
  the clue asks for a named person and the supplied context supports the full
  expected name/title, expand a surname-only or partial-name answer to that
  full expected form rather than returning only the surname (e.g., "Guiteau" ->
  "Charles Guiteau"; a title such as "Sir" is kept when it is part of the
  expected full-name form).
- Use the clue's exact spelling, spacing, punctuation, and word-boundary
  variant when it specifies a term or title (e.g., "Picture in Picture", not
  "Picture-in-picture").
- Remove parentheticals and alternate titles.
- Remove leading articles and added descriptors unless they are part of the
  exact title or official answer phrase (e.g., "The white eagle" -> "Eagle";
  "Speech balloon" -> "balloon").
- Keep, and restore if they were dropped, any title word or qualifier that is
  part of the required proper or official short-answer form (e.g., "Lake
  Superior", "People's Republic of China", or a required city/state qualifier
  or publication title word); do not shorten by omitting it.
- Choose the spelling and capitalization variant that matches the clue's
  wording or etymology (for example, the common-noun or established English
  spelling over a brand name or transliteration variant when the clue asks for
  the common term).
- Remove trailing punctuation.

Before returning, apply the same reduction to the exact short-answer form the
clue expects: remove unrequested descriptors and geographic qualifiers that are
not part of the requested name (for example, a mode or adjective added to a
common noun, or a state/province appended to a city/county answer); remove
appended surnames when the clue asks for a shorter given-name or moniker form;
replace foreign-language name variants with the expected English short-answer
form; add any required title or regnal-number words that the clue's reference
implies (for example, the numeral for a monarch or the title word in a proper
name); and use the name variant, number, and form the clue expects even when a
more formal or longer variant is also true.

If multiple forms or names are valid, return the shortest direct answer to the
clue, not a longer title or description. The final phrase must be the exact
short-answer form: remove unrequested descriptors, geographic qualifiers,
appended surnames, corporate suffixes, over-specific qualifiers, and
foreign-language variants; add any required title or regnal-number words;
expand a surname-only answer to the full expected name/title when the clue asks
for a named person; retain any words that belong to the proper/official name
the clue asks for; and use the spelling, capitalization, name variant, number,
spacing, and qualifier form the clue implies.
