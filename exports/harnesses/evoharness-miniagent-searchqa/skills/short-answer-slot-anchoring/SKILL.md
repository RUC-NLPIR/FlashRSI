---
name: short-answer-slot-anchoring
description: Exact-match short-answer QA; return the exact minimal slot surface form required by prompt and context.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [7e6a92097b984d0b9bf6307dca097b02]
---
# Short-Answer Slot Anchoring

Use for exact-match short-answer tasks with a minimal slot output.

1. Confirm exact-match scoring; the prompt asks for a bare slot, not Yes/No.
   - Bare/truncated prompt: return the matching literal span.
   - Quoted slogan/title: return the associated minimal title/entity, not a sentence.
   - "this play/work" + setting clue: return the work's title, not the location.
   - "X & Y": shared attribute/location/affiliation, not relationship; "In X & Y" -> language/demonym adjective, not country noun.
   - Nickname/moniker prompt: return the minimal explicit nickname (value after "Nickname:" or the quoted term after "known as"), not the longer alias built from it.

2. Anchor to literal context, not prominence/prior knowledge.
   - Quoted fragment: leading ellipsis -> preceding token; truncated end -> continuation.
   - Multiple candidates: choose the entity explicitly linked to queried facts; ignore "current" unless context links it.

3. Return only the minimal slot phrase:
   - Never emit a sentence; exact match scores 0 unless output is the bare slot.
   - Do not add parentheticals/expanded names absent from context.
   - Prefer the span matching the requested slot over a fuller alias; keep an official parenthesized/titular form only when the prompt asks for that form.
   - Shortest base term ("balloon", not "speech balloon"); nutrients as bare letter ("C").
   - Named places: keep leading article, omit added category noun; keep official prefix ("Lake Superior").

4. Preserve expected surface form: defining phrase with article/inflections; short person name unless full formal requested.

5. Verify selected phrase against prompt/context; preserve internal punctuation and singular/plural; no terminal punctuation/explanation/labels.
