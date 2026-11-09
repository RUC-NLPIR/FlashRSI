---
name: answer-form-verification
description: Use before finalizing a short answer when scoring may be exact or span-based. Verifies that the candidate copies the full source span the question requires, including formal names, minimal entity names, category head nouns, complete predicate frames, extent qualifiers, and direct anaphor resolution.
flashrsi:
  algorithm: evo_harness
  level: general
  source_task_ids: [5a851d485542992a431d1ade, 5adc8b065542994d58a2f644, 5a8f5993554299458435d5d5, 5abbc2285542992ccd8e7f8b]
---
# Answer-form verification

Before finalizing a short answer, check its form as well as its factual content. Many failures already contain the right entity but in the wrong lexical form. Copy the exact source span the question requires; do not normalize, paraphrase, or over-minimize.

1. Classify the expected output form from the question and context:
   - Person by name: full formal name from the source's introductory sentence, not a shorter article-title form.
   - Organization/entity: shortest source form that directly answers.
   - Ordinal: spelled-out ordinal, not numeric.
   - Kind/category: minimal category head noun from the source (e.g., "no-kill shelter"), not a bare modifier.
   - Notable act framed as "He is credited with [action] to [purpose]": complete predicate, including lead-in and purpose clause.
   - Extent ("from where to where"): full directional phrase with function words and compass qualifiers.
   - Bridge/multi-hop: full linking span; resolve ambiguous anaphors by the sentence directly classifying the work, not adaptation language like "made into a movie".

2. Locate the exact source span that answers the question.

3. Compare the candidate with that span and recover:
   - restore missing required wording (full names, predicate lead-ins, purpose clauses, category head nouns, direction qualifiers);
   - trim extra coordinated names, prefixes, or suffixes only when not required;
   - resolve ambiguous anaphors by direct classification, not related/adaptation mentions.

4. Preserve source wording and case; prefer the shortest source span that fully answers. Do not add words the question does not require.
