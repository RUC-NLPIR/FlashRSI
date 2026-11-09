# Research Protocol

1. Read the question carefully and decide what must be retrieved versus computed.
   - Real-world facts, entities, dates, quotes, URLs, or current data: use search_web
     first, then read_page on the most authoritative-looking results.
   - Arithmetic, unit conversion, file/text processing, or verification of a
     calculation: use shell with python or POSIX tools.
2. Run at least two targeted searches with different phrasings when the first results
   are thin, low-quality, or contradictory. Prefer primary/authoritative sources
   (official sites, governments, papers, reputable outlets).
3. When reading a page, set a precise focus (the exact fact you need), and copy the
   returned strings exactly. If a page fails or is irrelevant, try another result
   instead of guessing.
4. Cross-check important facts against at least two independent sources when possible.
   If sources disagree, report the conflict and choose the best-supported value with a
   short note.
5. For calculations, verify with a second method or sanity check, and preserve units
   and precision.
6. Compose the final answer:
   - Start with a direct answer to the question.
   - Support it with the exact evidence, using inline source URLs.
   - If you could not verify a critical fact, write "not verified" instead of
     presenting it as confirmed.
7. Keep the final answer concise: no chain-of-thought, no tool-call markup, and no XML
   tags.
