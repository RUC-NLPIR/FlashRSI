#!/usr/bin/env python3
"""SearchQA UserPromptSubmit preprocessor with deterministic slot contract,
pre-extracted QA cells, and a new token-aligned prose evidence layer.

This hook runs before the model sees the task. It:
1. deterministically parses the supplied search snippets and re-emits strong
   ``CLUE | ANSWER`` cells as a small, high-priority evidence block;
2. computes a short ``SLOT CONTRACT`` from the question so the model chooses
   the exact answer surface form instead of over- or under-answering;
3. token-aligns each ordinary prose sentence with the clue, re-emits the most
   clue-covering sentences with the clue tokens bracketed, and (when the
   missing span is a complete, disjoint noun phrase) surfaces a short lead.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

STOP = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "in",
    "on", "at", "to", "for", "from", "with", "without", "by", "about", "into",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "can", "will", "just", "should", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "having", "do", "does", "did",
    "doing", "what", "which", "who", "whom", "whose", "when", "where", "why",
    "how", "name", "question", "answer", "context", "supplied", "task",
    "following", "use", "using", "find", "give", "return", "short", "phrase",
    "single", "entity", "one", "this", "that", "these", "those", "it", "its",
    "as", "according",
}
BAD = re.compile(
    r"https?://|www\.|\bright\s*:|\bwrong\s*:|see more|click|image|photo|"
    r"title\s*:|definition|pronunciation|translations?",
    re.IGNORECASE,
)
TAG = re.compile(r"\[(?:DOC|TLE|PAR)\]", re.IGNORECASE)
CUE = re.compile(
    r"\b(?:this|these|what|who|which|where|when|whose|name|named|called|known|"
    r"term|word|year|city|state|country|capital|author|title|island|river|"
    r"mountain|president|king|queen|movie|film|book|play|song|animal|plant|"
    r"element|language|religion|department|agency|company|band|group|sport|"
    r"game|instrument|tool|weapon|ship|plane|car|building|monument|body|bone|"
    r"muscle|gland|disease|drug|chemical|food|fruit|vegetable|candy|drink|"
    r"color|number|date|holiday|war|battle|treaty|law|amendment)\b",
    re.IGNORECASE,
)
ANSWER_BAD_START = {
    "like", "and", "but", "or", "also", "plus", "is", "are", "was", "were",
    "these", "those", "this", "that",
}
ABBREV_WORDS = {
    "st", "mt", "dr", "mr", "mrs", "ms", "prof", "gen", "col", "capt", "sgt",
    "lt", "rev", "hon", "jr", "sr", "vs", "etc", "dept", "no", "nos",
    "approx", "phd",
}

# Words that are generic category nouns for slot-surface stripping. When the
# question slot is an ENTITY (``this gland``, ``this missile``), an evidence
# answer cell that tacks the category on the end should have that suffix removed.
STRIP_HEADS = {
    # Category/legal nouns for which the slot contract can safely tell the
    # model not to repeat the category word. Keep this set deliberately small:
    # other category nouns (river, city, state, amendment, series, candy,
    # cheese, ...) often form part of the answer name (East River, First
    # Amendment, World Series, cotton candy), so they get the generic ENTITY
    # contract instead.
    "gland": ["gland", "glands"],
    "missile": ["missile", "missiles"],
    "company": ["co", "corp", "corporation", "inc", "ltd", "llc", "usa", "u.s."],
    "co": ["co", "corp", "corporation", "inc", "ltd", "llc", "usa", "u.s."],
}

# Only these heads are safe for the hook itself to truncate from an extracted
# ``CLUE | ANSWER`` line. Legal company suffixes are left alone because the
# official answer form often keeps them (for example "Tiffany & Co.").
STRIP_SAFE_HEADS = {
    "gland": STRIP_HEADS["gland"],
    "missile": STRIP_HEADS["missile"],
}

# Person slots where a one-token answer in a pre-extracted line is likely only
# a surname/first name, so the model should expand it from the fuller evidence.
PERSON_HEADS = {
    "man", "woman", "girl", "boy", "daughter", "son", "person", "people",
    "author", "composer", "actor", "actress", "detective", "president",
    "king", "queen", "singer", "writer", "poet", "novelist", "playwright",
    "philosopher", "circumnavigator", "explorer", "scientist", "artist",
}

# Tokens that separate a complete answer noun phrase from the rest of a prose
# sentence. When a cleaned prefix/suffix span has one of these on its connector
# edge, the span is likely a whole answer rather than a modifier of the next
# clue word (e.g. "The pancreas is ..." vs. "The East River ...").
RELATION_VERBS = {
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "having", "do", "does", "did", "done", "became", "become", "called",
    "known", "named", "refers", "meant", "means", "wrote", "written",
    "authored", "composed", "directed", "painted", "founded", "discovered",
    "invented", "created", "designed", "built", "led", "ruled", "won", "made",
    "produced", "released", "starred", "played", "coined", "developed",
    "formulated", "patented", "located", "situated", "published", "issued",
    "recorded", "sang", "performed", "served", "acted", "began", "started",
    "ended", "died", "born", "held", "took", "got", "includes", "included",
    "features", "featured", "commemorates", "commemorated", "depicts",
    "depicted", "tells", "told",
}

# Edge words stripped from a prefix/suffix span before it is shown as a lead.
TRAILING_STRIP = RELATION_VERBS | {
    "a", "an", "the", "of", "in", "on", "at", "by", "to", "for", "from",
    "with", "without", "as", "and", "or", "but", "that", "which", "who",
    "whom", "whose", "this", "these", "those", "it", "its", "also", "then",
    "there", "here", "about", "into", "over", "under",
}
LEADING_STRIP = RELATION_VERBS | {
    "and", "or", "but", "that", "which", "who", "whom", "whose", "also",
    "then", "as", "of", "in", "on", "at", "by", "to", "for", "from",
    "with", "without", "about", "into", "over", "under",
}

# Prepositions that indicate a locative/possessive relation rather than a
# direct equative/defining one. A prefix lead is only shown when the connector
# edge is a direct copula or relation verb, not "X is in/on/of/at ...".
BAD_CONNECTOR_PREPS = {
    "in", "on", "at", "of", "from", "with", "without", "about", "over",
    "under", "to", "for", "by", "into",
}

# Sentences with these markers usually present a second/contrasting entity, so
# their subject is a distractor more often than the answer. Keep the sentence
# for verification, but do not promote its subject to a lead.
LEAD_BLOCKER_RE = re.compile(
    r"\b(?:another|other|also|too|however|but|instead|neither|nor|although|"
    r"though|whereas|while|not)\b",
    re.IGNORECASE,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?|[^\sA-Za-z0-9]+")


def normalize(text: str) -> str:
    """Grader-like comparison key: ASCII, lowercase, no punctuation/articles."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    text = re.sub(r"\b(?:a|an|the)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_tokens(text: str) -> list[str]:
    return [tok for tok in normalize(text).split() if tok not in STOP]


def split_prompt(prompt: str) -> tuple[str, str]:
    """Return (question, context) from the standard SearchQA prompt."""
    question = prompt
    context = prompt

    match = re.search(r"(?is)\n\s*Question\s*:\s*\n(.*)$", prompt)
    if match:
        question = match.group(1).strip()
    else:
        matches = re.findall(r"(?im)^\s*Question\s*:\s*(.*)$", prompt)
        if matches:
            question = matches[-1].strip()

    match = re.search(
        r"(?is)Context\s*:\s*\n(.*?)\n\s*Question\s*:\s*\n", prompt
    )
    if match:
        context = match.group(1).strip()
    else:
        c_match = re.search(r"(?is)Context\s*:", prompt)
        if c_match:
            index = c_match.end()
            context = prompt[index:].strip()
            q_index = context.rfind("\nQuestion:")
            if q_index >= 0:
                question = context[q_index + len("\nQuestion:"):].strip()
                context = context[:q_index].strip()
        else:
            context = ""
    return question, context


def parse_docs(context: str) -> list[tuple[str, str]]:
    """Split context into (title, paragraph) pairs.

    Documents are separated by ``[DOC]`` and may contain more than one
    ``[PAR]`` block. Keeping each ``[PAR]`` block separate prevents a short
    ``CLUE | ANSWER`` cell from being glued to the next prose paragraph when
    the harness strips newlines.
    """
    docs: list[tuple[str, str]] = []
    for part in re.split(r"\[DOC\]", context, flags=re.IGNORECASE):
        part = part.strip()
        if not part:
            continue
        title_match = re.search(
            r"\[TLE\]\s*(.*?)(?:\n|\[PAR\])", part, re.IGNORECASE | re.DOTALL
        )
        title = title_match.group(1).strip() if title_match else ""

        paragraphs: list[str] = []
        for block in re.findall(r"\[PAR\](.*?)(?=\[PAR\]|$)", part, re.IGNORECASE | re.DOTALL):
            block = TAG.sub(" ", block)
            block = re.sub(r"\s+", " ", block).strip()
            if block:
                paragraphs.append(block)
        if not paragraphs:
            # A document with no [PAR] marker (for example an undecorated
            # plain-text snippet) is still kept as a single paragraph.
            block = TAG.sub(" ", part)
            block = re.sub(r"\s+", " ", block).strip()
            if block:
                paragraphs.append(block)

        for paragraph in paragraphs:
            docs.append((title, paragraph))
    return docs


def clean_field(field: str) -> str:
    """Remove QA-cell trailers and surface noise from one answer/clue field."""
    field = TAG.sub(" ", field)
    field = re.sub(r"\s+(?:right|wrong)\s*:.*$", "", field, flags=re.I | re.S)
    field = re.sub(r"\s+value\s*:.*$", "", field, flags=re.I | re.S)
    field = field.strip().strip("*").strip()
    # Some QA cells append a second, unrelated title after a sentence break,
    # e.g. ``PETITS FOURS. "JOY OF COOKING"``. Keep only the answer before the
    # first real sentence break unless that break is an abbreviation.
    if has_sentence_break(field):
        m = re.search(r"\.\s+(?=[A-Z0-9\"\u201c])", field)
        if m:
            prefix = field[: m.start()].strip()
            if valid_answer(prefix):
                field = prefix
    field = re.sub(r"[\s.!:;,]+$", "", field)
    return re.sub(r"\s+", " ", field).strip()


def has_sentence_break(answer: str) -> bool:
    """True if the answer looks like multiple sentences rather than an
    abbreviation such as St. Louis, Mt. Everest, or U.S. Army."""
    for match in re.finditer(r"\.\s+[\"“A-Z0-9]", answer):
        before = answer[: match.start()]
        parts = before.split()
        if not parts:
            continue
        word = "".join(ch for ch in parts[-1] if ch.isalnum()).lower()
        if word in ABBREV_WORDS or len(word) <= 2:
            continue
        return True
    return False


def valid_answer(answer: str) -> bool:
    if not answer or "..." in answer:
        return False
    words = answer.split()
    if len(words) > 8:
        return False
    if len(content_tokens(answer)) < 1:
        return False
    if BAD.search(answer):
        return False
    if has_sentence_break(answer):
        return False
    if words and words[0].lower() in ANSWER_BAD_START:
        return False
    return True


def valid_clue(clue: str) -> bool:
    if not clue:
        return False
    # Short clues like "this gland" lose most words to STOP, but they are
    # still useful Q&A cells. Require at least two raw words and one
    # non-stop token so "what" alone does not become an evidence line.
    if len(clue.split()) < 2:
        return False
    if len(content_tokens(clue)) < 1:
        return False
    if BAD.search(clue):
        return False
    return True


def slot_profile(question: str) -> dict[str, str]:
    """Derive a deterministic slot contract for the question.

    The returned strings are intentionally short so they can be injected before
    the model reads the snippets without displacing evidence.
    """
    q = (question or "").strip()
    ql = q.lower()

    # COMPLETION: an explicit blank, or a quoted fragment that is genuinely
    # missing one side. A quotation with an internal ellipsis is usually a
    # title/quote clue, not a fill-in-the-blank, so it must have a leading
    # ellipsis or an explicit completion cue before we constrain the answer.
    if re.search(r"_{2,}", q):
        return {"role": "COMPLETION", "head": "", "plural": "no",
                "note": "Answer only the missing token(s); never repeat words already shown outside the blank."}
    if re.search(
        r"\b(?:the\s+\d+\s+words?\s+that\s+complete|complet(?:e|es|ing)\s+the\s+"
        r"(?:speech|quote|phrase|saying|line)|finish(?:es)?\s+this\s+"
        r"(?:quote|phrase|saying|line))\b",
        ql,
    ):
        return {"role": "COMPLETION", "head": "", "plural": "no",
                "note": "Answer only the missing text; never repeat words already shown in the prompt."}
    quote = re.search(r"[\"\u201c]([^\"\u201d]*\.\.\.[^\"\u201d]*)[\"\u201d]", q)
    if quote:
        inner = quote.group(1)
        leading_ellipsis = re.match(r"^\s*\.\.\.", inner) is not None
        completion_cue = re.search(
            r"\b(?:follows?\s+the\s+words?|this\s+term\s+for|finish(?:es)?\s+this|"
            r"complete\s+this|fill\s+in|missing\s+(?:word|words|part|text)|blank)\b",
            ql,
        )
        if leading_ellipsis or completion_cue:
            return {"role": "COMPLETION", "head": "", "plural": "no",
                    "note": "Answer only the missing part of the quoted fragment; never repeat the words already shown."}

    # TYPE_OF: the slot itself is a type/kind/sort.
    if re.search(r"\bthis\s+(?:type|kind|sort)\b|\bthese\s+(?:types|kinds|sorts)\b|\bor\s+this\s+type\b", ql):
        return {"role": "TYPE_OF", "head": "type", "plural": "no",
                "note": "Answer only the requested subtype/kind. Start from the strongest evidence's exact wording, then drop a category noun already stated in the question (such as the noun after 'type of') unless dropping it would leave an incomplete or non-idiomatic answer."}

    # Determine head noun after this/these for ENTITY slots.
    head = ""
    SKIP_ADJ = {
        "french", "english", "freckled", "beautiful", "louisiana", "american",
        "british", "german", "canadian", "australian", "chinese", "japanese",
        "russian", "italian", "spanish", "dutch", "irish", "scottish", "welsh",
        "mexican", "indian", "egyptian", "greek", "roman", "norse", "african",
        "asian", "european", "south", "north", "east", "west", "little", "big",
        "old", "new", "famous", "first", "last", "only", "same", "chewy",
        "yellowish", "brown", "red", "gray", "grey", "blue", "green", "black",
        "white", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "many",
    }
    m = re.search(r"\bthis\s+(.+?)(?=\s+(?:is|was|are|were|has|have|had|makes|named|called|known|features|means|played|wrote|said|became|comes|can|will|may|does|did|found|founded|began|returned|issued|published|released|took|put|gets|got|earned|starred|shared|commemorates|depicted|depicts|tells|complete|follows)\b)", ql)
    if m:
        words = [w for w in re.findall(r"[a-z]+", m.group(1).lower()) if w.isalpha()]
        for w in words:
            if w not in SKIP_ADJ:
                head = w
                break
    if not head:
        m = re.search(r"\bthese\s+(.+?)(?=\s+(?:is|are|were|have|has|had|makes|called|known|features|means|played|wrote|said|became|comes|can|will|may|does|did|found|founded|began|returned|issued|published|released|took|put|gets|got|earned|starred|shared|commemorates|depicted|depicts|tells|complete|follows)\b)", ql)
        if m:
            words = [w for w in re.findall(r"[a-z]+", m.group(1).lower()) if w.isalpha()]
            for w in words:
                if w not in SKIP_ADJ:
                    head = w
                    break
    if not head:
        m = re.search(r"\bthis\s+([a-z]+(?:\s+[a-z]+)?)", ql)
        if m:
            words = [w for w in re.findall(r"[a-z]+", m.group(1).lower()) if w.isalpha()]
            for w in words:
                if w not in SKIP_ADJ:
                    head = w
                    break
    if not head:
        # possessive forms: "this composer's death", "this country's wines"
        m = re.search(r"\bthis\s+([a-z]+)['\u2019]s\b", ql)
        if m:
            head = m.group(1).lower()

    # BARE_CLUE: no explicit slot word at all.
    has_slot_word = re.search(
        r"\b(this|these|he|she|it|they|who|what|which|whose|where|when|"
        r"name|named|called|known|term|word)\b",
        ql,
    )
    if not has_slot_word:
        return {"role": "BARE_CLUE", "head": "", "plural": "no",
                "note": "The clue is a title/name/fragment with no explicit slot. Supply the missing attribute in the shortest exact form the evidence uses; do not give a descriptive gloss."}

    if head in STRIP_HEADS:
        return {"role": "ENTITY", "head": head, "plural": "no",
                "note": "Answer the named entity itself. Do not repeat the category word shown after this/these, and do not add descriptors. Keep a legal/company suffix only if the strongest evidence's official name includes it; otherwise strip it."}
    return {"role": "ENTITY", "head": head, "plural": "no",
            "note": "Answer the named entity itself using the exact evidence form."}


def shorten_answer(answer: str, question: str) -> str:
    """Apply the slot contract to a single QA-cell answer when it is safe."""
    profile = slot_profile(question)
    if profile.get("role") not in {"ENTITY", "BARE_CLUE"}:
        return answer
    head = profile.get("head", "")
    if not head or head not in STRIP_SAFE_HEADS:
        return answer
    variants = STRIP_SAFE_HEADS[head]
    # Tokenize the answer preserving original words. Only strip whole final
    # tokens, so titles and abbreviations are never mangled.
    toks = re.findall(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?|[&]", answer)
    if not toks:
        return answer
    for variant in sorted(variants, key=len, reverse=True):
        vtoks = re.findall(r"[a-z0-9]+", normalize(variant))
        if not vtoks:
            continue
        if len(toks) <= len(vtoks):
            continue
        tail = [normalize(t) for t in toks[-len(vtoks):]]
        if tail == vtoks:
            prefix = " ".join(toks[:-len(vtoks)]).strip()
            if valid_answer(prefix):
                return prefix
    return answer


def parse_pipe_pairs(docs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Parse conventional ``CLUE | ANSWER`` cells."""
    pairs: list[tuple[str, str]] = []
    for _, paragraph in docs:
        if "|" not in paragraph:
            continue
        fields = [field.strip() for field in paragraph.split("|")]
        if len(fields) < 2:
            continue
        clue = TAG.sub(" ", fields[-2])
        clue = re.sub(r"\s+", " ", clue).strip()
        answer = clean_field(fields[-1])
        if valid_clue(clue) and valid_answer(answer):
            pairs.append((clue, answer))
    return pairs


def parse_flashcard_pairs(docs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Parse all-caps StudyStack/Quizlet style ``CLUE, ANSWER`` lines."""
    pairs: list[tuple[str, str]] = []
    for title, paragraph in docs:
        if "|" in paragraph or "," not in paragraph:
            continue
        clue, answer = paragraph.rsplit(",", 1)
        clue = clue.strip()
        answer = clean_field(answer)
        if not valid_clue(clue) or not valid_answer(answer):
            continue
        if len(clue.split()) < 6:
            continue
        letters = [ch for ch in clue if ch.isalpha()]
        if not letters:
            continue
        upper_ratio = sum(ch.isupper() for ch in letters) / len(letters)
        title_lower = title.lower()
        title_signal = any(
            key in title_lower
            for key in ("flashcard", "study", "quiz", "stack", "trivia", "jeopardy")
        )
        if not (title_signal or (upper_ratio >= 0.8 and CUE.search(clue))):
            continue
        pairs.append((clue, answer))
    return pairs


def parse_qa_pairs(docs: list[tuple[str, str]], question: str = "") -> list[tuple[str, str]]:
    pairs = parse_pipe_pairs(docs) + parse_flashcard_pairs(docs)
    if question:
        pairs = [(clue, shorten_answer(answer, question)) for clue, answer in pairs]
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for clue, answer in pairs:
        key = (normalize(clue), normalize(answer))
        if key in seen:
            continue
        seen.add(key)
        unique.append((clue, answer))
    return unique


def slot_context(question: str) -> str:
    profile = slot_profile(question)
    head = profile.get("head", "")
    show_head = bool(head) and (
        profile.get("role") == "TYPE_OF"
        or head in STRIP_HEADS
        or head in PERSON_HEADS
    )
    return (
        "SLOT CONTRACT (deterministic answer-form guide):\n"
        f"- role: {profile['role']}\n"
        + (f"- head: {head}\n" if show_head else "")
        + f"- {profile['note']}"
    )


def qa_context(pairs: list[tuple[str, str]], question: str, limit: int = 24) -> str:
    """Build a short, sorted evidence block from extracted Q&A cells."""
    if not pairs:
        return ""
    question_tokens = set(content_tokens(question))
    rows: list[tuple[float, int, int, str, str]] = []
    for clue, answer in pairs:
        clue_tokens = set(content_tokens(clue))
        overlap = question_tokens & clue_tokens
        if not overlap:
            continue
        rare = sum(1 for token in overlap if len(token) > 3)
        exact = 1 if normalize(clue) == normalize(question) else 0
        score = len(overlap) * 3.0 + rare * 2.0 + exact * 10.0
        rows.append((score, len(overlap), exact, clue, answer))
    rows.sort(key=lambda row: (-row[0], -row[1]))
    profile = slot_profile(question)
    person_head = profile.get("head", "") in PERSON_HEADS
    lines: list[str] = []
    for _, _, exact, clue, answer in rows[:limit]:
        if exact and person_head and len(normalize(answer).split()) == 1:
            tag = "EXACT-PARTIAL"
        else:
            tag = "EXACT" if exact else "close"
        lines.append(f'- [{tag}] "{clue}" => "{answer}"')
    if not lines:
        return ""
    return (
        "PRE-EXTRACTED ANSWER LINES (deterministically extracted from the "
        "supplied snippets; treat a matching clue as very strong evidence and "
        "use the exact answer text after =>):\n" + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# New: token-aligned prose evidence layer
# ---------------------------------------------------------------------------

def tokenize_text(text: str) -> list[dict]:
    """Tokenize text into word/punctuation tokens with char spans."""
    toks: list[dict] = []
    for m in TOKEN_RE.finditer(text):
        raw = m.group(0)
        norm = unicodedata.normalize("NFKD", raw)
        norm = norm.encode("ascii", "ignore").decode("ascii").lower()
        norm = "".join(ch for ch in norm if ch.isalnum())
        toks.append({
            "raw": raw,
            "norm": norm,
            "start": m.start(),
            "end": m.end(),
            "all_idx": 0,
        })
    for idx, tok in enumerate(toks):
        tok["all_idx"] = idx
    return toks


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences while protecting common abbreviations."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    i = 0
    n = len(text)
    while i < n:
        if text[i] not in ".!?":
            i += 1
            continue
        j = i + 1
        while j < n and text[j] == " ":
            j += 1
        if j >= n:
            sentences.append(text[start:i + 1].strip())
            start = j
            i = j
            break
        nxt = text[j]
        if nxt.isupper() or nxt.isdigit() or nxt in "\"\u201c([{":
            before = text[start:i].strip()
            prev_words = re.findall(r"[A-Za-z0-9]+$", before)
            if prev_words:
                w = prev_words[-1].lower()
                if w in ABBREV_WORDS or len(w) <= 1:
                    i += 1
                    continue
            # Decimal like 3.14: do not split between digits.
            prev_char = text[i - 1] if i - 1 >= start else ""
            if nxt.isdigit() and prev_char.isdigit():
                i += 1
                continue
            sentences.append(text[start:i + 1].strip())
            start = j
            i = j
            continue
        i += 1
    if start < n:
        sentences.append(text[start:].strip())
    return [s for s in sentences if s]


def align_tokens(text: str) -> list[str]:
    """Tokenize text the same way sentences are tokenized for alignment.

    ``content_tokens`` is deliberately grader-like (it compresses punctuation
    such as ``Moby-Dick`` to ``mobydick``), while ``tokenize_text`` splits on
    punctuation. For LCS alignment both sides must use the split form,
    otherwise hyphenated titles and decimal quantities never match.
    """
    return [
        t["norm"]
        for t in tokenize_text(text)
        if t["norm"] and t["norm"] not in STOP
    ]


def lcs_len(q: list[str], s: list[str]) -> int:
    """Length of the longest common subsequence of two token lists."""
    n, m = len(q), len(s)
    if n == 0 or m == 0:
        return 0
    prev = [0] * (m + 1)
    for i in range(n - 1, -1, -1):
        qi = q[i]
        cur = [0] * (m + 1)
        for j in range(m - 1, -1, -1):
            if qi == s[j]:
                cur[j] = prev[j + 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j + 1] else cur[j + 1]
        prev = cur
    return prev[0]


def lcs_alignment(q: list[str], s: list[str]) -> set[int]:
    """Return s indices used by one longest common subsequence.

    The tie-break skips question tokens before skipping sentence tokens, which
    tends to leave the answer-bearing prefix/suffix unmarked in the display.
    """
    n, m = len(q), len(s)
    if n == 0 or m == 0:
        return set()
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if q[i] == s[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = dp[i + 1][j] if dp[i + 1][j] >= dp[i][j + 1] else dp[i][j + 1]
    matched: set[int] = set()
    i = j = 0
    while i < n and j < m:
        if q[i] == s[j]:
            matched.add(j)
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return matched


def clean_span(raw: str, side: str) -> tuple[str, list[str]]:
    """Clean a candidate span and report the connector tokens removed.

    The returned string is a substring of ``raw``, so internal punctuation
    (hyphens, apostrophes, abbreviation periods) is preserved exactly.
    """
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = raw.strip(" \t\r\n.,;:!?\"'()[]{}")
    toks = tokenize_text(raw)
    start_idx = 0
    end_idx = len(toks)

    def drop_empty_ends() -> None:
        nonlocal start_idx, end_idx
        while start_idx < end_idx and toks[start_idx]["norm"] == "":
            start_idx += 1
        while end_idx > start_idx and toks[end_idx - 1]["norm"] == "":
            end_idx -= 1

    drop_empty_ends()
    stripped: list[str] = []
    changed = True
    while changed and start_idx < end_idx:
        changed = False
        if side == "prefix":
            while end_idx > start_idx and toks[end_idx - 1]["norm"] == "":
                end_idx -= 1
            if end_idx > start_idx and toks[end_idx - 1]["norm"] in TRAILING_STRIP:
                stripped.append(toks[end_idx - 1]["norm"])
                end_idx -= 1
                changed = True
        else:
            while start_idx < end_idx and toks[start_idx]["norm"] == "":
                start_idx += 1
            if start_idx < end_idx and toks[start_idx]["norm"] in LEADING_STRIP:
                stripped.append(toks[start_idx]["norm"])
                start_idx += 1
                changed = True

    drop_empty_ends()
    if start_idx >= end_idx:
        return "", stripped
    candidate = raw[toks[start_idx]["start"]:toks[end_idx - 1]["end"]].strip()
    return candidate, stripped


def candidate_ok(candidate: str, q_toks: list[str]) -> bool:
    if not candidate or "..." in candidate:
        return False
    if len(candidate.split()) > 4:
        return False
    if not valid_answer(candidate):
        return False
    cand_toks = set(align_tokens(candidate))
    q_set = set(q_toks)
    # The missing span should introduce new information. Requiring a
    # completely disjoint span keeps descriptor restatements ("the capital of
    # France") out of the leads; the model still sees the full highlighted
    # sentence for names that embed a clue word (East River, First Amendment).
    if not cand_toks:
        return False
    if cand_toks & q_set:
        return False
    return True


def align_sentences(
    question: str, docs: list[tuple[str, str]], limit: int = 10
) -> tuple[list[dict], list[dict]]:
    """Return (aligned rows, candidate leads) for ordinary prose snippets.

    Each aligned row: {score, title, display, lead, coverage, n_match}.
    """
    q_toks = align_tokens(question)
    if not q_toks:
        return [], []
    q_set = set(q_toks)
    rows: list[dict] = []
    leads: list[dict] = []

    for title, paragraph in docs:
        if not paragraph:
            continue
        for sentence in split_sentences(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            all_toks = tokenize_text(sentence)
            words = [t for t in all_toks if t["norm"]]
            content = [t for t in words if t["norm"] not in STOP]
            s_toks = [t["norm"] for t in content]
            if not s_toks:
                continue
            if not (q_set & set(s_toks)):
                continue
            matched = lcs_alignment(q_toks, s_toks)
            n_match = len(matched)
            coverage = n_match / len(q_toks)
            if n_match < 2 and len(q_toks) >= 2:
                continue
            if coverage < 0.34:
                continue

            # Highlight clue tokens in the original sentence.
            matched_all = {content[idx]["all_idx"] for idx in matched}
            parts: list[str] = []
            last = 0
            for tok in all_toks:
                if tok["norm"] and tok["all_idx"] in matched_all:
                    parts.append(sentence[last:tok["start"]])
                    parts.append("[[" + sentence[tok["start"]:tok["end"]] + "]]")
                    last = tok["end"]
            parts.append(sentence[last:])
            display = re.sub(r"\s+", " ", "".join(parts)).strip()

            row = {
                "score": coverage * 10.0 + min(3, n_match),
                "title": title,
                "display": display,
                "lead": "",
                "coverage": coverage,
                "n_match": n_match,
            }
            rows.append(row)

            # Candidate lead search. Only short, complete, disjoint spans.
            m = len(s_toks)
            max_span = 6
            best: tuple[float, str] | None = None

            # Prefix span: sentence tokens before the matched rest start.
            for p in range(1, min(max_span, m - 1) + 1):
                rest = s_toks[p:]
                cov = lcs_len(q_toks, rest) / len(q_toks)
                if cov < 0.55:
                    continue
                first_rest_all = content[p]["all_idx"]
                if first_rest_all <= 0:
                    continue
                raw = sentence[all_toks[0]["start"]:all_toks[first_rest_all - 1]["end"]]
                candidate, stripped = clean_span(raw, side="prefix")
                if not candidate_ok(candidate, q_toks):
                    continue
                if not (
                    any(tok in RELATION_VERBS for tok in stripped)
                    or s_toks[p] in RELATION_VERBS
                ):
                    # Without a connector (is/was/called/wrote...), the span may
                    # just be a modifier of the next clue word ("East" before
                    # "River"). Leave that to the highlighted sentence instead.
                    continue
                if any(tok in BAD_CONNECTOR_PREPS for tok in stripped):
                    # "X is in/on/of ..." is not an equative definition; X is
                    # usually a distractor, not the missing slot.
                    continue
                score = cov * 10.0 + (1.5 if len(candidate.split()) <= 3 else 0.3)
                if best is None or score > best[0]:
                    best = (score, candidate)

            # Suffix span: sentence tokens after the matched rest ends.
            for p in range(max(1, m - max_span), m):
                rest = s_toks[:p]
                cov = lcs_len(q_toks, rest) / len(q_toks)
                if cov < 0.55:
                    continue
                # Start just after the last matched rest token so connector
                # words such as "is" are available to the cleaner/completeness
                # check. The cleaner then strips them from the left edge.
                raw = sentence[content[p - 1]["end"]:all_toks[-1]["end"]]
                candidate, stripped = clean_span(raw, side="suffix")
                if not candidate_ok(candidate, q_toks):
                    continue
                # A suffix lead should be a simple, complete noun phrase. If the
                # span still contains a preposition (e.g. "Moby-Dick in 1851"),
                # the prepositional tail is an adjunct, not part of the answer
                # noun phrase. We skip the lead rather than guess where the
                # title/name ends; the highlighted sentence still shows the full
                # span and lets the model recover the complete title.
                if any(
                    tok["norm"] in BAD_CONNECTOR_PREPS
                    for tok in tokenize_text(candidate)
                    if tok["norm"]
                ):
                    continue
                if not (
                    any(tok in RELATION_VERBS for tok in stripped)
                    or (p > 0 and s_toks[p - 1] in RELATION_VERBS)
                ):
                    continue
                if any(tok in BAD_CONNECTOR_PREPS for tok in stripped):
                    continue
                score = cov * 10.0 + (1.5 if len(candidate.split()) <= 3 else 0.3)
                if best is None or score > best[0]:
                    best = (score, candidate)

            if best is not None and not LEAD_BLOCKER_RE.search(sentence):
                row["lead"] = best[1]
                leads.append(row)

    # De-duplicate by normalized sentence text; keep the best-scoring copy.
    seen_sent: set[str] = set()
    unique_rows: list[dict] = []
    for row in sorted(rows, key=lambda r: -r["score"]):
        key = normalize(row["display"])
        if key in seen_sent:
            continue
        seen_sent.add(key)
        unique_rows.append(row)
    rows = unique_rows[:limit]

    seen_lead: set[str] = set()
    unique_leads: list[dict] = []
    for row in sorted(leads, key=lambda r: -r["score"]):
        key = normalize(row["lead"])
        if key in seen_lead:
            continue
        seen_lead.add(key)
        unique_leads.append(row)
    leads = unique_leads[:limit]
    return rows, leads


def aligned_prose_context(
    question: str, docs: list[tuple[str, str]], limit: int = 10
) -> str:
    rows, _leads = align_sentences(question, docs, limit=limit)
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        lead = f'  => lead: "{row["lead"]}"' if row["lead"] else ""
        title = f"{row['title']} | " if row["title"] else ""
        lines.append(
            f'- [cov={row["coverage"]:.2f}] {title}{row["display"]}{lead}'
        )
    return (
        "ALIGNED PROSE EVIDENCE (ordinary sentences token-aligned with the "
        "clue; [[bracketed]] words are already stated in the clue, so the "
        "answer is normally the adjacent unmarked noun phrase -- stop before "
        "a trailing year or place, but expand to the full evidence name when "
        "the name embeds a bracketed word, e.g. East River / First "
        "Amendment):\n" + "\n".join(lines)
    )


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0

    prompt = request.get("prompt", "")
    if not prompt:
        print("{}")
        return 0

    try:
        question, context = split_prompt(prompt)
        if not context:
            print("{}")
            return 0
        docs = parse_docs(context)
        pairs = parse_qa_pairs(docs, question)
        additional_context = qa_context(pairs, question)
        slot_block = slot_context(question)
        profile = slot_profile(question)
        person_head = profile.get("head", "") in PERSON_HEADS
        has_exact = False
        has_exact_partial = False
        q_norm = normalize(question)
        for clue, answer in pairs:
            if normalize(clue) == q_norm:
                has_exact = True
                if person_head and len(normalize(answer).split()) == 1:
                    has_exact_partial = True
        if has_exact and not has_exact_partial:
            # A decisive exact QA cell already nails the answer; extra prose
            # would only add noise.
            prose_limit = 0
        else:
            prose_limit = 6 if additional_context else 10
        aligned_block = aligned_prose_context(question, docs, limit=prose_limit)
    except Exception:
        print("{}")
        return 0

    if not additional_context and not slot_block and not aligned_block:
        print("{}")
        return 0

    combined = "\n\n".join(
        block for block in (slot_block, additional_context, aligned_block) if block
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": combined,
        }
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
