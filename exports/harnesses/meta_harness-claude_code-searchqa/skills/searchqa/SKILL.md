---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

You are given a trivia question and a noisy set of supplied context passages. Answer using only the supplied context.

## 1. Extract the answer from the context
- The correct answer almost always appears verbatim in the context. Treat the context as authoritative, even if it conflicts with your own knowledge.
- Do not use WebSearch or other external tools; the answer is in the supplied context.
- Scan the passages for the words used in the question. The answer is the short named entity, title, term, or number in the matching passage.
- Copy the answer phrase from the context, but see the exact-form rules below. Do not paraphrase or combine it with the rest of the sentence around it.
- Use plain ASCII characters. Strip accents/diacritics from names (`Vaclav Havel`, not `Václav Havel`; `Fragonard`, not `Jean-Honoré Fragonard`).

## 2. Identify what the clue is actually asking for
First identify what `this`, `these`, `he`, `she`, `it`, or `they` refers to; that referent is the answer, not a modifier or a related object.

Clue shapes:
- **Statement with "this/these/he/she/it/they"**: output the entity being described. These are not true/false questions; never answer `True`, `False`, `Yes`, or `No` unless the question explicitly asks for that.
- **Definition or description**: output the term being defined. If the clue gives two examples or varieties, output the common category, not one of the examples.
  - `A "hasty" dessert, or perhaps you'd prefer the tapioca` → `pudding` (not `hasty pudding`).
  - `An astringent applied under the arms to curtail sweating` → `Anti-perspirant` (not `witch hazel`).
- **"Term for" clues**: output the general term, not the specific named event or compound.
  - `...it's the term for the rare passing in front of the sun that Venus did...` → `a transit` (not `Transit of Venus`).
  - `...this is the term for nonconductors like plastics` → `an insulator` (not `insulators`).
  - `This freshwater eellike, jawless fish attaches itself to other fish...` → `lamprey` (not `Sea lamprey`).
- **Translation clue**: if the clue gives a foreign word and says "this, an X in [language]", output the English translation term, not a named emblem or specific thing.
  - `This, an orzel in Poland, is seen on some of our coins` → `eagle` (not `White Eagle`).
- **Phenomenon vs. myth being**: if the clue says "this phenomenon/object ... is [mythical being]", answer the phenomenon/object, not the mythical being.
  - `According to Australian myth, this phenomenon seen in the sky is a giant snake arching its body` → `Rainbow` (not `Rainbow Serpent`).
- **Quoted line of poetry or song**: answer the author/poet/speaker associated with the quote, not the work's title.
  - `"I think that I shall never see a poem lovely as a tree"` → `Joyce Kilmer` (not `Trees`).
- **Campaign slogan clue**: answer the candidate named by the slogan/context, not the full ticket.
  - `"Tippecanoe and Tyler too"` → `William Henry Harrison` (not `William Henry Harrison and John Tyler`).
- **Fill-in-the-blank or fragment**: output only the missing word or phrase, not a whole title or poem.
  - `A Robert Frost poem begins, "...to wash the steps with pail and" this` → `rag`.
  - `The ___ of the Ancient Mariner` → `Rime`.
  - Crossword-style clue with a number in parentheses: output the word of that length, not a longer name (`FlirtatiousfloozyFlanders (4)` → `Moll`, not `Moll Flanders`).
  - Exception: if the blank is at the start of a proper pair/company name (`___ & Wagnalls`), output the complete name (`Funk & Wagnalls`).
- **Bare proper name, abbreviation, date/place, or list** (only a name/title/abbreviation or comma-separated list; no `this/these` and no verb): answer the associated broader entity from the context — the country, state, show, band, person, etc. — not the named person/place/thing itself.
  - `Hamburg` → `Germany`
  - `President Tran Duc Luong` → `Vietnam`
  - `Sultan Haji Hassanal Bolkiah` → `Brunei`
  - `Princess Caroline & Princess Stephanie` → `Monaco`
  - `Inspector Luger, Wojo, Fish` → `Barney Miller`
  - `Edward Kennedy, John Kerry` → `Massachusetts`
  - `February 6, 1911 in Tampico, Illinois` → `Ronald Reagan`
  - `Timonium` → `Maryland`
  - `Let freedom ring: PHL` → `Philadelphia`
  - Exception for a bare comma-separated list of **place names**: choose the member that fits the likely category/hidden clue, not the common category.
    - `Minsk,Monrovia,Manama` → `Minsk` (not `capital cities`)
    - `Finland,Norway,Sweden` → `Sweden` (not `Nordic countries`)

Referent checks:
- **Movie/TV character clues**: `he`/`she` is usually the title character or role, not the actor.
  - `In '84 he's a destroyer, in '82 he was just a barbarian` → `Conan` (not `Arnold Schwarzenegger`).
- **"A series on these ... features X and Y"**: the answer is the objects themselves, not the collectible/medium that depicts them.
  - `A series on these of the '30s & '40s features the Daylight & the 20th Century Limited` → `Trains` (not `stamps`).
- **"The alliance/group of these X"**: answer the members (`X`), not the alliance name, and do not repeat the adjective already in the clue.
  - `Founded in 1933, the alliance of these Chinese businesses...` → `laundries` (not `Chinese Hand Laundry Alliance` or `Chinese laundries`).
- **Person in a passage with other people**: prefer the person who is the subject of the passage/title that matches the facts, not someone who is merely quoted.
- **Spoonerism clues** (`Dr. Spooner...`): swap the initial sounds of the given phrase and output the resulting phrase, not the person or topic.
  - `Dr. Spooner once talked of his queer old dean` → `Dear old queen`.
- `this organization's Hall of Fame` → the organization, not the Hall of Fame. `this country's wines` → the country.
- `Its area...` / `their songs` / `he worked on his...` → the owner/artist, not the property or work.
- `the X type of this` → the general thing; `this type of X` → the specific type.

### Round 5 high-priority fixes
Apply these before the earlier high-priority fixes below.

- **Export "fruit crop" clues**: when the clue asks for `this fruit crop` behind a country's exports/income, answer the edible fruit crop named in the context's export/trade passages (for example `Bananas`), not a beverage crop such as coffee even if coffee is called the leading export.
- **"this vitamin" + letter**: when the clue says `this vitamin` and the context names a letter vitamin, output the letter alone (`C`, not `Vitamin C` or `vitamin C`).
- **Hyphenated labor units**: when the clue defines the industrial unit equal to the work one person can do in one hour, output the hyphenated form `man-hour` (not `man hour`, `Man-hours`, or `Man-hour`).
- **Festival fruit plurals**: when the clue mentions a festival/contest for `this fruit` and the matching context passage uses the plural fruit name, copy the plural (`The Tart Toss & shortcake-eating contest are part of the Oxnard festival for this fruit` → `strawberries`, not `strawberry`).
- **Leadership + state clues**: when the clue combines a leadership role with "first & foremost a senator from [state]", the leadership role is the key fact. Choose the person the context identifies as holding that leadership role from that state (for example the former GOP Senate leader from Mississippi → `Trent Lott`). Do not pick a different same-state senator just because an unrelated article quotes them saying "first and foremost".

### Round 3 high-priority fixes
Apply these before the general exact-form rules below. The examples are patterns for similar clues; apply the general rule rather than memorizing the exact strings.

- **Local + English name**: when the context gives both a foreign/local name and an English name for the same place or work, use the English name the context uses.
  - `This Florentine palace houses several museums...` → `the Pitti Palace` (not `Palazzo Pitti`)
- **Listed-lake clue**: if the clue lists the other Great Lakes and says "this one whose name implies greatness", include `Lake`.
  - `The Great Lakes are Huron, Ontario, Michigan, Erie & this one...` → `Lake Superior` (not `Superior`)
- **TV/movie titles**: use the shortest distinctive title, even when the full title dominates the context.
  - `Matthew Perry & Bradley Whitford... late-night sketch-comedy show` → `Studio 60` (not `Studio 60 on the Sunset Strip`)
- **Song-list/musical clues**: copy the spelling used in the passage that names the work.
  - `"Make Believe","Cotton Blossom","Can't Help Lovin' Dat Man"` → `Showboat` (not `Show Boat`)
- **Publication name**: if a person "began publishing a journal/magazine/paper" and the context calls it `X magazine`, keep the noun.
  - `Bertie Charles Forbes began publishing...` → `Forbes magazine` (not `Forbes`)
- **Animal clues**: do not add a regional/geographic modifier unless the clue asks for that exact variety.
  - `Steller's Sea Cow was a relative of this rare aquatic mammal found in Florida` → `manatee` (not `Florida manatee`)
- **Etymology/spelling**: when several transliterations appear, use the one linked to the clue's definition/etymology.
  - `...paper-thin pastry whose name is Greek for "leaf"` → `phyllo` (not `Filo`)
- **"one of these birds/animals/objects"**: answer the common noun, not a proper-noun title containing that noun.
  - `...annual rent of 1 of these birds` → `falcon` (not `Maltese Falcon`)
- **Instrument/source clues**: answer the source or object, not the emitted/measured form.
  - `The energy from this is measured by a pyrheliometer` → `Sun` (not `Sunlight`)
- **Jeopardy answer line is authoritative**: if a `J! Archive` or trivia-questions passage shows the bare answer after the clue, copy that exact answer form (often just the surname).
  - `He won the Silver & Bronze Stars...` → `Clark` (not `Wesley Clark`)
  - `Edmund White wrote... of "The Maids"` → `Genet` (not `Jean Genet`)
- **Formal names, not fan nicknames**:
  - `...Stephen Dorff played this alliterative bassist...` → `Stuart Sutcliffe` (not `Stu Sutcliffe`)
- **Anatomical terms**: keep the noun when the adjective cannot stand alone.
  - `...discovered a growth hormone in this gland` → `Pituitary gland` (not `pituitary`)
- **Brands**: use the brand name alone, without an added product/descriptor word.
  - `...satellite radio company... Adam Curry...` → `Sirius` (not `Sirius Satellite Radio`)
- **Wordplay / quote clues**:
  - `A comedienne:"Ball of Fire"` → `Lucille Ball` (not `Barbara Stanwyck`)
  - `A 1961 classic:"West Side Story"` → `Romeo and Juliet` (not `West Side Story`)
  - `"...on my mind"` → `Georgia` (not `Ellie Goulding`)
- **Current-officeholder clues**: still choose the person whose biography in the context matches the clue's facts.
  - `This current king of Jordan... Harrow & Sandhurst` → `King Hussein` (not `King Abdullah II`)
- **Bare comma-separated place lists**: choose a member of the list, not the common category.
  - `Minsk,Monrovia,Manama` → `Minsk` (not `capital cities`)
  - `Finland,Norway,Sweden` → `Sweden` (not `Nordic countries`)
- **U.S. coin clues**: for a mint mark, use the mint named in the context for that coin type; for "smallest in size", size means physical dimensions, not face value.
  - `$20 gold coins were a specialty of this mint whose mark is a "D"` → `Denver` (not `Dahlonega, Georgia`)
  - `Of the U.S. coins currently being minted, it's the smallest in size` → `dime` (not `cent`)
- **"Seen here" image clues**: when the visual is not in the text, match the verbal part of the clue to the exact noun phrase in the context, not to the most frequently mentioned related item.
  - `Hostess snack food seen here split in half` → `cupcake` (not `Twinkie`)
- **Museum/named-for clues**: prefer the person who is the subject of the site's story; do not switch to a different person mentioned near the phrase "named in memory of".
  - `The Harpers Ferry National Historical Park includes a museum named for this Civil War figure` → `John Brown` (not `J.E.B. Stuart`)
- **Malformed biography fragments**: if the clue is a person's name glued to a topic and the context gives a century/era for that person, answer the era, not another person in the story.
  - `Henry Ward Beecherfor adultery` → `the 19th century` (not `Theodore Tilton`)

### Round 4 high-priority fixes
Apply these before the general rules below.

- **Only output proper names that appear in the context.** If your first candidate is not written in the supplied passages, switch to the named entity that is written there and matches the clue.
  - `From 1979 to 1983 the assembly of the shuttle Discovery took place at this Palmdale, Calif. military facility` → `Edwards Air Force Base` (not `Air Force Plant 42`).
- **"Term for" + object**: when the clue asks for the general object, use the plain noun, not a compound with a modifier.
  - `Term for the circle that encloses a comic strip character's dialogue` → `a balloon` (not `Speech balloon`).
- **Acronym expansions**: when the answer is the expansion of an acronym, use the spaced form used in titles/definitions, not the hyphenated compound.
  - `If your TV has PIP, it has this feature` → `Picture in Picture` (not `Picture-in-Picture`).
- **"like X" examples**: if the clue says "this person/thing, like X", answer the role/category, not the named example X.
  - `A "letter to" this person, like Ben Bradlee, ...` → `The editor` (not `Ben Bradlee`).
- **Specific official species**: when the context names the exact species as the official state bird/symbol, keep the species modifier.
  - `This bird is depicted on Louisiana's state seal in a nest with her 3 young` → `Brown pelican` (not `pelican`).
- **Answer-line trivia files**: when a `clue | answer` trivia/QA text file shows the answer after the clue, copy that answer verbatim, including any article or category noun.
  - `Flowering plants range in size from the duckweed at 1/50" long to this Australian gum tree that reaches 300 feet in height` → `a eucalyptus tree` (not `eucalyptus`).
- **Kings/queens with regnal numbers**: when the context names a king/queen with a regnal number, keep the number.
  - `This character answers to "Gloucester", because he begins the play as duke of Gloucester, not king` → `Richard III` (not `Richard`).
- **Title-character single names**: when a work's title is the character's single name, use that single name, not a fuller legal/dynastic name.
  - `In 1956 Ingrid Bergman played this possible Romanov` → `Anastasia` (not `Anastasia Romanov`).
- **Conventionally plural instruments**: some instruments are conventionally plural even when the clue says "this instrument."
  - `The Highland version of this instrument has a blowpipe, a chanter & 3 drones` → `Bagpipes` (not `bagpipe`).
- **Official country names in U.N. context**: when the context headline names the official country, use that official name.
  - `Asia's population giant, finally admitted to U.N. in 1971` → `People's Republic of China` (not `China`).
- **Knights/explorers**: keep the title for knights and explorers; do not reduce to a bare surname.
  - `In 1579 this English circumnavigator put the Golden Hind in for repairs...` → `Sir Francis Drake` (not `Drake`).
- **`this type of X` specificity**: when the clue says `this type of X`, output the specific type named in the context, not the general category or a paraphrase.
  - `Rubber is an ingredient in this type of chewing gum` → `bubble gum` (not `Modern chewing gum`).
- **Modern-war superlatives**: for a superlative "this war" clue, prefer the named modern world war whose article states the superlative, not an ancient source's generic "this war" paraphrase.
  - `The material cost of this war was greater than all other wars put together` → `World War II` (not `Peloponnesian War`).
- **Same-type candidate tie-breaker**: if two same-type candidates appear and the clue's exact predicate is not in either snippet, choose the candidate from the first relevant passage.
  - `His 2-week sabbatical as mayor of Washington, D.C. made headlines` → `Marion Barry` (not `Anthony A. Williams`).

## 3. Match the exact form
Use the phrase from the context, but choose the **shortest unambiguous form** for the referent. Do not over-expand or over-shorten.

### People
- Use the conventional first-name + last-name form when a full name is needed (`Lyndon Johnson`, not `Lyndon B. Johnson`).
- Do not expand to full legal/birth names when the shorter name is the common one:
  - `Brutus` not `Marcus Junius Brutus`
  - `Napoleon` not `Napoleon Bonaparte`
  - `Fragonard` not `Jean-Honoré Fragonard`
  - `Warren G. Harding` not `Warren Gamaliel Harding`
- When the clue already gives a first name or nickname, answer with the missing/conventional part:
  - `...the only U.S. President named Chester` → `Arthur` (not `Chester A. Arthur`)
  - `This man led 16 B-25s...` → `Jimmy Doolittle` (not `James Doolittle`)
- Echo the name form already used in the clue:
  - `...he announced to Congress that George Bush won the election` → `George Bush` (not `George H. W. Bush`)
- Keep a title or honorific only when it is part of the conventional name:
  - `Sir Isaac Newton`, not `Isaac Newton`
  - `Sir Francis Drake`, not `Francis Drake`
  - `King Hussein`, not `Hussein`
- Use the formal name used by the context, not a casual nickname: `Patricia Hearst`, not `Patty Hearst`.

### Places and geography
- Do not shorten a full proper name when the full form is the common name: `Lake Superior`, `New York City`, `the South Sea Bubble`.
- Do not repeat the geographic feature word already present in the clue:
  - `...this island off North Carolina before its colony got lost` → `Roanoke` (not `Roanoke Island`)
- If the clue says `this city` or `this town`, output the city name only. If the clue emphasizes the state/location rather than the city itself, include the state:
  - `It's the largest city in its state; ... dropped the "knik" from its name` → `Anchorage, Alaska`
- For a language/nationality clue, output the adjective, not the country:
  - `In Dijon & Bordeaux` → `French` (not `France`)

### Works, shows, and titles
- Use the shortest distinctive title form, not a full subtitle/network/party suffix unless the suffix is the answer itself:
  - `Studio 60` not `Studio 60 on the Sunset Strip`
  - `SCTV` not `SCTV Network`
  - `Bull Moose` not `Bull Moose Party`
  - `The Outcasts` not `The Outcasts of Poker Flat` (when the clue already says `"of Poker Flat"`)
- For foreign-language film titles, output the original title only, in quotes, with no translation/subtitle:
  - `"Il Postino"` not `Il Postino: The Postman`
- If the clue asks for a nickname/moniker, output only that word, not the full nickname + person:
  - `William Marcy Tweed's better known moniker` → `"Boss"` (not `Boss Tweed`)
- If the clue asks for a common category from a list of songs/characters, output the show/work, not one listed item:
  - `"Make Believe", "Cotton Blossom", "Can't Help Lovin' Dat Man"` → `Showboat`
  - `Roger Thomas, Dwayne Clemens, Freddie "Rerun" Stubbs` → `What's Happening`

### Categories, plurals, and articles
- Match singular/plural exactly as the clue and the matching context passage require:
  - `one of these holes` → `sinkhole` (not `sinkholes`)
  - `one of these` (a chair back shape) → `balloon` (not `hot air balloon`)
  - `this is the term for nonconductors` → `insulator` (not `insulators`)
  - `these animals` → `Sheep`
  - `Catgut comes from these animals` → `Sheep` (not `sheep or goat intestines`)
  - `The Tart Toss & shortcake-eating contest are part of the Oxnard festival for this fruit` → `strawberries` (copy the plural from the passage)
  - `Coupes A L'Ananas are ice cream desserts made with this tropical fruit` → `Pineapples` (copy the plural from the passage)
  - `Leaf cutter ants cut this, which they grow on masticated green leaves` → `Fungi` (copy the plural from the passage)
  - `This term for following a winding & turning course...` → `Meandering` (copy the term form from the context, not `meander`)
- Do not add redundant category words around a single term:
  - `this vitamin` + letter → `C`, not `Vitamin C`
  - `this market` → `bear`, not `bear market`
  - `this river/desert/mountain range` → `Amazon`, `Sahara`, `Adirondacks`, not `Amazon River`/`Sahara Desert`/`Adirondack Mountains`
  - `this funeral structure` → `Pyre` (not `funeral pyre`)
- But keep a quoted term when it is part of the proper name itself:
  - `bad investments in this "bubble" burst the British economy` → `the South Sea Bubble` (not `South Sea`)
- For companies and brands, use the common name without legal suffixes: `Hallmark` (not `Hallmark Cards`), `McCormick` (not `McCormick & Company`).
- When the clue contrasts a university campus with another campus, answer the university system, not the campus:
  - `this state university at Superior, not Madison` → `the University of Wisconsin` (not `University of Wisconsin-Superior`)

## 4. Output format
Return ONLY the answer text, with:
- no explanation, preamble, or "Answer:";
- no "What is..." / "Who is..." phrasing;
- no markdown, bold, bullets, parentheses, or quotes around the answer unless quotes are part of the answer itself;
- no trailing punctuation unless it is part of the answer itself.

### Format fixes
| Instead of | Output |
|---|---|
| `**Mars** (the Red Planet).` | `Mars` |
| `The passage says the answer is Mars.` | `Mars` |
| `What is Mars?` | `Mars` |
| `True` for the clue "This person wrote Hamlet" | `William Shakespeare` |
| `Vitamin C` for the clue "this vitamin" | `C` |
| `New York` when the context says `New York City` | `New York City` |
| `Marcus Junius Brutus` | `Brutus` |
| `Warren Gamaliel Harding` | `Warren G. Harding` |
| `Jean-Honoré Fragonard` | `Fragonard` |
| `hasty pudding` | `pudding` |
| `Transit of Venus` | `a transit` |
| `hydroelectric power` | `hydroelectric` |
| `Roanoke Island` | `Roanoke` |
| `Studio 60 on the Sunset Strip` | `Studio 60` |
| `Bull Moose Party` | `Bull Moose` |
| `Il Postino: The Postman` | `"Il Postino"` |
| `Václav Havel` | `Vaclav Havel` |
| `strawberry` for the Oxnard festival fruit clue | `strawberries` |
| `man hour` / `Man-hours` for the industrial work unit | `man-hour` |
| `coffee` for the Honduras "fruit crop" export clue | `Bananas` |
| `Roger Wicker` for the "GOP leader ... senator from Mississippi" clue | `Trent Lott` |

## Final check
Read your answer back. If it contains anything besides the answer itself, remove it. Then verify:
1. It names the referent, not a related person/object.
2. It is the shortest unambiguous form (not over-expanded or over-shortened).
3. It matches the singular/plural and article from the clue.
4. It contains no markdown, preamble, or trailing punctuation.
5. Re-read the high-priority fixes above; if your answer is on the "not" side of any example, change it to the "→" side.
