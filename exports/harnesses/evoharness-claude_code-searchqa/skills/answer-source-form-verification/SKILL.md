---
name: answer-source-form-verification
description: Determine the authoritative source, answer type, and exact surface form before committing an exact-match short answer. Use when the retrieved context interleaves a speaker's guess with an 'A:' answer, when the prompt labelled 'Question' is a bare declarative statement with an unresolved pronoun, or when the prompt's 'one of these [plural]' phrasing dictates a singular noun with article.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [64cb77e3c59a40e1ae3a9502bd565867, 6072e63558b445ad9c01394dfed313b4, f6f35af39efd4a16ba440993d142349e]
---
1. Trust the authoritative marker, not the plausible guess. In a Jeopardy!/Q&A transcript, a named speaker's response (e.g., "CORDRAY: What is gravity?") is often a WRONG guess; the real answer follows the "A:" marker. Extract the "A:" value, and discount conflicting forum posts when independent sources agree.

2. Resolve the prompt's actual answer type. When the "Question" is a bare declarative statement with an unresolved pronoun ("his", "her", "their") and no question word, it is not a True/False claim. The expected short answer is the named entity the pronoun refers to — resolve it against the context and emit that entity's name.

3. Match grammatical number and article to the prompt's phrasing. A blank introduced by "one of these [plural category]" ("...one of the ... holes") wants the singular count noun with its indefinite article ("a sinkhole"), not a bare plural ("sinkholes").

4. Before committing, check three things: what answer type the prompt requests (entity vs. boolean), which context region is authoritative vs. distractor, and what exact surface form (article/number) the key expects. Do not let the most salient or plausible token override these.
