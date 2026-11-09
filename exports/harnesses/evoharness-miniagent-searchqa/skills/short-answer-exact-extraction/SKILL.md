---
name: short-answer-exact-extraction
description: Use for exact-match short-answer QA; return only the minimal slot value with the expected surface form, anchored to the strongest context support.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [fcb4868f4e8847f79ef5622f2e05ddcd, bc63eb4bd9234e4583a6c12cb3851cef, 9420eb98f0004e649aa999b6f66fd116]
---
# Short-Answer Exact Extraction

Use for exact-match short-answer tasks with a minimal slot output.

1. Confirm exact-match scoring; a bare/declarative prompt asks for the slot value, not Yes/No.

2. Identify the slot from the prompt form:
   - Bare entity-only prompt: the entity is given; return the informative predicate value from its definitional sentence (country/location/category), not an appositive official/expanded name.
   - Truncated fragment: return the matching literal continuation span, not a source/title.
   - Quoted slogan/catchphrase/title: return only the minimal associated title/entity, never a sentence that merely contains it.
   - "this play/work" + setting clue: return the work's title, not the location.
   - Definition/category: return the exact defining-sentence noun phrase with article/inflection.

3. Anchor to the strongest explicit context support, not prominence/prior knowledge:
   - Multiple candidates: choose the entity explicitly linked to the queried facts; ignore "current" unless context links it.
   - Quoted fragments: leading ellipsis -> preceding token; truncated end -> immediate continuation.

4. Return only the minimal slot phrase with the expected surface form:
   - Publication names: return the full title as given, including the type noun ("Forbes magazine", not "Forbes").
   - Diacritics: use the unaccented ASCII form when context supports it; never restore diacritics absent from the context.
   - Nutrients: bare letter ("C", not "Vitamin C").
   - Term variants: shortest base term ("a balloon", not "speech balloon").
   - Named places: keep leading article, omit added category noun ("the Sahara", not "Sahara Desert"); keep official prefix ("Lake X").
   - No parentheticals/expanded names; never emit a sentence containing the answer.

5. Verify against prompt and strongest context span; match grammar/capitalization and singular/plural; return no punctuation/explanation/labels.
