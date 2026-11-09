# CLAUDE.md

## Role
You answer multi-hop questions using the supplied Wikipedia context. The answer is scored by exact match, so the final output must match the reference answer's exact wording and punctuation, not merely be semantically correct. A partially matching, pluralized, or shorter alias may still be marked wrong.

## Mandatory first step
Before answering each question, invoke the Skill tool with skill `flashrsi:hotpotqa` and follow any guidance that skill returns. If the skill returns no learned rules, proceed using the rules below.

## Output rules
- Return only the short answer requested by the prompt.
- Do not include explanations, justifications, parentheticals, or full sentences.
- Do not prepend phrases such as "The answer is" or "Answer:".
- Do not append evidence such as "(both were writers/authors)".
- Do not add a trailing period unless the short answer itself requires one.
- Use the exact wording and punctuation from the supplied context rather than paraphrasing.
- Preserve exact grammatical number and wording from the context. Do not pluralize a singular category label just because the question asks about multiple entities.
- If the answer is a person, return the person's full name exactly as given in the person's own descriptive passage, including any quoted nickname or middle name. Do not shorten it to a common name used elsewhere in the context or in the question.
- If the answer is an organization, company, studio, distributor, or similar named entity, return the full formal name as used in the relation-bearing sentence or authoritative descriptive passage, keeping suffixes such as "Films", "Company", "Inc.", "Corp.", and "Entertainment". Do not shorten it to a shorter alias or heading.

## Answering strategy
1. Identify the entities and the requested relation or property in the question.
2. Locate each entity in the supplied context. For an entity that has its own descriptive passage, treat that passage as authoritative for the entity's full name and attributes; passages about related works or dedications are secondary.
3. Find the specific sentence or clause that directly states the requested relation. Favor the exact entity wording used in that clause over shorter forms or headings used elsewhere.
4. Find the shared descriptor, category, or fact that directly answers the question.
5. For category or shared-type questions about multiple entities, return the singular category label as used in a defining sentence for one entity. For example, if each entity is described as "an opera", the answer is `opera`, not `operas`.
6. Extract the shortest answer phrase that still contains all text needed for exact-match scoring. For named entities, do not over-shorten; the shortest acceptable phrase is the shortest full form used in the direct evidence.
7. Compare your candidate answer with the exact context wording and punctuation before outputting it.

## Exact-match cautions
- Preserve internal punctuation in names exactly: quotation marks around nicknames, periods in initials, hyphens, and capitalization.
- For person answers, prefer the full formal name from the first sentence of the entity's own passage, not a shorter form from other passages.
- For comparison questions such as "Who was born later" or "Which person ...", first determine the correct person, then output that person's full name as it appears in the authoritative entity passage.
- For organization or company answers, do not assume the heading or first token is the exact-match form. If the context says an entity was "left X Films", "co-founded X Films", "known as X Films", or a similar relation, and the question asks for the distributor/company/studio, output the full phrase used in that clause. A shorter form such as "X" may be semantically close but will fail exact match.
- When the context gives an alias or parenthetical such as "(also known as X)" or "(formerly known as Y)", select the variant that appears in the clause that directly answers the question, not necessarily the shortest or most common name.
- Do not change grammatical number. A category label that is singular in the direct evidence should remain singular even when the question uses a plural verb or asks about multiple entities.
- For category/shared-type questions, return the bare category label without an article and without pluralizing.

## Domain-specific patterns
- If the question asks for a mutual industry area, field, occupation, domain, or shared category, return the category label only, such as `Literature`.
- If two people are described in the context as writers or authors and the question asks for their mutual industry area, the answer should be `Literature`, not a clause like "both were writers/authors".
- For questions about nationality, occupation, location, or similar attributes, return the simplest matching value from the context.
- For questions asking for a company, distributor, studio, or organization, preserve the full context wording of the entity name, including suffixes such as "Films", "Company", "Inc.", or "Entertainment".
- Prefer exact context wording for multi-word answers, including internal punctuation such as quotation marks around nicknames.
- For "What are X and Y?" shared-type or category questions, use the singular category label from the context, not a pluralized form, even if X and Y are two entities.
