---
name: searchqa
description: Use for every supplied-context question-answering task in this SearchQA experiment.
---

# Question Answering Skill

## Pre-extraction strategy

1. Identify the question's requested slot (e.g., height, date, person, award, place) and whether it asks for one entity or several.
2. Return only the context span that fills that slot.
3. Do not substitute another fact about the same entity (such as coordinates when height is requested).
4. Do not append additional related entities when the question asks for a single answer.

## Answer extraction

1. First locate the supporting fact in the supplied context.
2. After locating the supporting span, return the exact minimal contiguous phrase from the supplied context that fills the requested slot.
3. Preserve the context's surface form exactly: case, punctuation, number/unit style, full personal names, and complete official award/title wording.
4. Preserve leading prepositions and articles when they are part of the requested phrase (e.g., "from the South Para Reservoir in the north to the Mount Bold Reservoir in the south").
5. Do not insert incidental prepositions such as "on" before a bare place answer.
6. Do not paraphrase, normalize, shorten, expand, or substitute outside knowledge for the located phrase.

## Output contract

1. Before emitting, identify the exact slot the question requests and return the shortest contiguous context phrase that fills that slot.
2. For category, genre, or type questions, return only the bare category label as written in the context, not a longer noun phrase ending in a class word such as "films"; for other slots, likewise omit extra descriptive nouns, qualifiers, and trailing class terms.
3. Emit only the exact answer phrase.
4. Do not add biographical detail, state/unit qualifiers, parentheticals, markdown, or trailing punctuation.

## Handling near-synonym or related labels

1. If a requested quantity appears under a near-synonym or related unit label in the context (for example, the question says "area" but the context gives the value under "volume"), return the context value rather than refusing.
