# Question Answering Skill

The supplied context is the only evidence. Answer directly in one final
message, without tool calls, whenever the context already contains the answer.

## Final-answer rules

1. The final message must contain only the requested short answer: no
   preamble, explanation, hedging, parentheticals, or extra punctuation.
2. Copy the answer verbatim from the supplied context.
   - Choose the shortest contiguous context span that fully answers the
     question.
   - For a named entity, copy the exact name/title form used in the passage
     that directly answers the question. Do not import a longer biographical
     form, a middle name, or a shorter alias from a different passage.
   - For numbers and ordinals, keep the exact form used in the context
     (spelled-out vs numeric, punctuation, separators). Do not add words such
     as "about", "around", or "approximately".
   - For yes/no questions, return only "yes" or "no" in lowercase.
3. Cross-reference every supplied context passage and resolve anaphora and
   co-reference before answering. The relevant evidence may be in a passage
   that does not repeat the subject's name. Do not answer "not stated" until
   every passage has been checked.
4. Match the answer shape the question asks for.
   - For a category/type/kind/genre/style question, return the shortest exact
     evidence phrase that fully names the category. Do not repeat the head
     noun or unit named in the question when the label is already complete
     without it; keep the compound label when the modifier alone is not a
     complete label.
   - For a singular question, return exactly one entity or value; do not join
     distinct answers with "and".
   - For a where question, return the place name alone, without a leading
     preposition.
   - For a from/to or range question, copy the complete phrase including the
     leading "from".
   - For an act or achievement question, copy the complete evidence clause or
     sentence that states it, including any introductory attribution.
   - For an award question, return the award title exactly as the evidence
     states it, without adding an organization prefix or a plural suffix that
     is not part of the title.
   - For a question that offers alternatives, resolve the reference to the
     passage that states the fact and return the term used there.
5. Before finalizing, verify that the final answer is a contiguous verbatim
   substring of the supplied context and contains no extra tokens.
