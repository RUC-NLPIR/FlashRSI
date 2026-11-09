#!/usr/bin/env python3
"""Deterministic evidence-map preprocessor for supplied-context QA prompts.

Runs as a Claude Code UserPromptSubmit hook. It parses the standard
``Context:`` / ``Question:`` wrapper, splits evidence into sentence-level
units, extracts copyable candidate spans (names, dates, numbers, quoted
strings, choice letters, digit-containing proper names, category phrases,
official-company names), builds a query-focused entity graph over those units
with morphological/country aliases, and injects:

  1. a QUERY FRAME (provisional target type and question shape),
  2. a CANDIDATE BOARD (top copyable spans with supporting lines and
     TITLE/FIRST/OBJECT surface-role hints),
  3. BRIDGE PATH WITNESSES (explicit two-sentence chains that share a named
     entity), and
  4. EXPANDED EVIDENCE (direct-overlap lines plus graph-expanded lines that
     share an entity with a direct line, up to two hops).

Nothing is removed from the full context. The injected map is deliberately a
hypothesis shortlist and a prioritized view, not an authoritative answer. Any
parse failure prints ``{}`` and changes nothing.
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

# Common capitalized sentence-initial words that are almost never answer spans.
COMMON_CAP = {
    "The", "This", "That", "These", "Those", "However", "Although", "Because",
    "While", "Where", "When", "After", "Before", "During", "According",
    "Despite", "Instead", "Moreover", "Further", "Finally", "Additionally",
    "In", "On", "At", "From", "With", "Without", "Under", "Over", "Between",
    "Among", "It", "Its", "He", "She", "They", "We", "You", "A", "An", "And",
    "But", "Or", "For", "Nor", "So", "Yet", "If", "Then", "There", "Here",
    "What", "Which", "Who", "Whom", "Whose", "How", "Why", "Not", "No", "Yes",
    "As", "By", "To", "Of",
}

# Month names and generic titles are copied from the text often enough that a
# deterministic extractor will otherwise flood the board with them.
MONTH_NAMES = {
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Jan", "Feb", "Mar", "Apr",
    "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
}

GENERIC_TITLES = {
    "Chief", "Commander", "General", "Admiral", "President", "Director",
    "Officer", "Operations", "Operation", "Force", "Forces", "Command",
    "Institute", "University", "Army", "Navy", "Air", "War", "Battle",
    "State", "City", "County", "National", "United", "World", "Pacific",
    "International", "Supreme", "Major", "Captain", "Colonel", "Lieutenant",
    "Sergeant", "Secretary", "Minister", "Ambassador", "Senator",
    "Congress", "Congressman", "Representative", "Governor", "Mayor",
    "Judge", "Justice", "King", "Queen", "Prince", "Princess", "Emperor",
    "Empire", "Republic", "Kingdom", "Province", "River", "Mountain",
}

TAG = re.compile(r"\[(?:DOC|TLE|PAR)\]", re.IGNORECASE)

MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
DATE_RES = [
    re.compile(r"\b" + MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b", re.I),
    re.compile(r"\b\d{1,2}\s+" + MONTH + r"\.?,?\s+\d{4}\b", re.I),
    re.compile(r"\b" + MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?\b", re.I),
    re.compile(r"\b\d{4}\b"),
]
NAME_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z'\u2019-]+\.?\s+){1,4}(?:[A-Z][a-zA-Z'\u2019-]+)\b"
)
SINGLE_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'\u2019-]{2,}\b")
NUM_RE = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?(?:%|st|nd|rd|th)?\s*(?:years?|year|days?|day|"
    r"months?|month|weeks?|week|hours?|hour|minutes?|minute|seconds?|second|"
    r"people|men|women|children|times|miles?|km|kg|g|lb|tons?|percent|%|"
    r"goals?|points?|runs?|awards?|songs?|albums?|books?|films?|movies?|"
    r"records?|medals?|wins?|losses?)?\b",
    re.I,
)
QUOTE_RE = re.compile(r'"([^"]{1,120})"|\'([^\']{1,120})\'')
OPTION_RE = re.compile(r"\(\s*([A-Da-d])\s*\)")

PERSON_NICK_RE = re.compile(
    r"\b[A-Z][a-zA-Z'\u2019-]+(?:\s+[A-Z][a-zA-Z'\u2019-]+){0,3}"
    r"\s+[\"\u201c][^\"\u201d]{1,40}[\"\u201d]"
    r"\s+[A-Z][a-zA-Z'\u2019-]+(?:\s+(?:[A-Z][a-zA-Z'\u2019-]+|Jr\.?|Sr\.?|III|IV))?\b"
)
PROPER_DIGIT_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9]*(?:\s+(?:[A-Za-z0-9]+|of|the|and|in|for|at|on|with|by|"
    r"de|la|van|von|der|den|di|da|del|della|el|al|san|santa|sao|ibn|bin|bint|ben|mac|mc)){0,5}\b"
)
_SUFFIX = r"Co\.?,?|Ltd\.?,?|Inc\.?,?|Corp\.?,?|LLC|S\.p\.A\.|S\.A\.|AG|GmbH|plc|LP|LLP"
ORG_SUFFIX_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9'\u2019-]+(?:\s+(?:(?!" + _SUFFIX + r")[A-Z][A-Za-z0-9'\u2019-]+|of|the|and|in|for|"
    r"at|on|with|by|de|la|van|von|der|den|di|da|del|della|el|al|san|santa|sao|ibn|bin|bint|ben|mac|mc)){0,6}"
    r"(?:\s+(?:" + _SUFFIX + r")){0,2}\b"
)
_PREDICATE_RE = (
    r"(?:known as|called|refers? to|means?|meaning|becomes?|became|is|was|are|were|both)"
)
TYPE_PRED_RE = re.compile(
    r"\b" + _PREDICATE_RE + r"\s+"
    r"(?!" + _PREDICATE_RE + r"\b)"
    r"(?:(?:a|an|the)\s+)?([a-z][a-z0-9]*(?:\s+[a-z][a-z0-9]*){0,4})\b"
)

# Title-case phrases with small connector words, e.g. "Night of the Black Snow".
_CAP_TOKEN = r"[A-Z][A-Za-z0-9'\u2019-]+"
_CONNECTOR = (
    r"(?:of|the|and|in|for|on|at|with|without|by|from|de|la|du|van|von|der|"
    r"den|zu|und|di|da|del|della|el|al|y|e|san|santa|sao|s\u00e3o|ibn|bin|"
    r"bint|ben|mac|mc)"
)
TITLE_PHRASE_RE = re.compile(
    r"\b" + _CAP_TOKEN + r"(?:\s+(?:" + _CAP_TOKEN + r"|" + _CONNECTOR + r")){0,5}\b"
)
_CONNECTOR_WORDS = {
    "of", "the", "and", "in", "for", "on", "at", "with", "without", "by",
    "from", "de", "la", "du", "van", "von", "der", "den", "zu", "und", "di",
    "da", "del", "della", "el", "al", "y", "e", "san", "santa", "sao",
    "s\u00e3o", "ibn", "bin", "bint", "ben", "mac", "mc",
}
_CAP_WORD_RE = re.compile(r"^[A-Z][A-Za-z0-9'\u2019-]+$")

# Split after sentence-ending punctuation unless it is a single-letter initial
# such as "E." in "Emmett E. O'Donnell" or the "U.S." abbreviation.
SENT_SPLIT_RE = re.compile(r"(?<!\b[A-Z]\.)(?<=[.!?])\s+(?=[A-Z0-9\"'])")

STOP_WORDS_LOWER = {w.lower() for w in STOP}

DEMONYM = {
    "american": "america", "british": "britain", "english": "england",
    "french": "france", "spanish": "spain", "italian": "italy",
    "german": "germany", "japanese": "japan", "chinese": "china",
    "indian": "india", "russian": "russia", "canadian": "canada",
    "australian": "australia", "brazilian": "brazil", "dutch": "netherlands",
    "swiss": "switzerland", "swedish": "sweden", "norwegian": "norway",
    "danish": "denmark", "finnish": "finland", "polish": "poland",
    "turkish": "turkey", "greek": "greece", "mexican": "mexico",
    "peruvian": "peru", "chilean": "chile", "argentine": "argentina",
    "iranian": "iran", "iraqi": "iraq", "syrian": "syria",
    "lebanese": "lebanon", "israeli": "israel", "palestinian": "palestine",
    "egyptian": "egypt", "south african": "south africa",
}


def token_aliases(tok: str) -> set[str]:
    """Return morphological/country aliases for a normalized content token."""
    out = {tok}
    if tok in DEMONYM:
        out.add(DEMONYM[tok])
    else:
        for dem, place in DEMONYM.items():
            if tok == place:
                out.add(dem)
                break
    if tok.endswith("ese") and len(tok) > 5:
        root = tok[:-3]
        out.add(root)
        out.add(root + "e")
    elif tok.endswith("ian") and len(tok) > 5:
        root = tok[:-3]
        out.add(root)
        out.add(root + "a")
        out.add(root + "ia")
    elif tok.endswith("ish") and len(tok) > 5:
        out.add(tok[:-3])
    if tok.endswith("s") and len(tok) > 5:
        out.add(tok[:-1])
    return {t for t in out if len(t) > 2}


def token_alias_set(text: str) -> set[str]:
    """Alias-expanded set of non-stop content tokens (rare tokens only)."""
    out: set[str] = set()
    for tok in normalize(text).split():
        if tok not in STOP and len(tok) > 3:
            out |= token_aliases(tok)
    return out


def normalize(text: str) -> str:
    """Grader-like comparison key: ASCII, lowercase, alnum tokens only."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def content_tokens(text: str) -> list[str]:
    return [tok for tok in normalize(text).split() if tok not in STOP]


def split_prompt(prompt: str) -> tuple[str, str]:
    """Return (question, context) from the standard QA prompt wrapper."""
    match = re.search(
        r"(?is)Context:\s*\n(.*)\n\s*Question:\s*\n(.*)$", prompt
    )
    if not match:
        # Also accept prompts that use no blank line between sections.
        match = re.search(r"(?is)Context:\s*\n(.*)\nQuestion:\s*\n(.*)$", prompt)
    if not match:
        # Some wrappers keep the question on the same line as its marker.
        match = re.search(r"(?is)Context:\s*\n(.*)\n\s*Question:\s*(.*)$", prompt)
    if not match:
        return "", prompt.strip()
    return match.group(2).strip(), match.group(1).strip()


def split_sentences(text: str) -> list[str]:
    """A conservative sentence splitter for candidate extraction."""
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
    return parts or [text.strip()]


def parse_lines(context: str) -> list[tuple[str, str]]:
    """Split titled-line contexts into (title, sentence) units.

    Falls back to sentence-level units when the context does not look like a
    sequence of ``Title: sentence`` lines.
    """
    raw_lines = [line.strip() for line in context.splitlines() if line.strip()]
    titled_count = sum(1 for line in raw_lines if ": " in line)
    if titled_count >= max(1, len(raw_lines) // 2):
        units: list[tuple[str, str]] = []
        for line in raw_lines:
            line = TAG.sub(" ", line)
            if ": " in line:
                title, body = line.split(": ", 1)
            else:
                title, body = "", line
            title = re.sub(r"\s+", " ", title).strip()
            body = re.sub(r"\s+", " ", body).strip()
            if not body:
                continue
            # HotpotQA-style contexts join several sentences on one titled
            # line; keep the sentence-level units promised by the evidence map.
            for sent in split_sentences(body):
                if sent:
                    units.append((title, sent))
        return units

    units = []
    for block in context.split("\n\n"):
        block = TAG.sub(" ", block)
        block = re.sub(r"\s+", " ", block).strip()
        for sent in split_sentences(block):
            if sent:
                units.append(("", sent))
    return units


def parse_tagged(context: str) -> list[tuple[str, str]]:
    """Split ``[DOC]/[TLE]/[PAR]`` contexts into (title, sentence) units."""
    units: list[tuple[str, str]] = []
    for part in re.split(r"\[DOC\]", context, flags=re.IGNORECASE):
        part = part.strip()
        if not part:
            continue
        title_match = re.search(
            r"\[TLE\]\s*(.*?)(?:\n|\[PAR\])", part, re.IGNORECASE | re.DOTALL
        )
        title = title_match.group(1).strip() if title_match else ""
        paragraphs = re.findall(
            r"\[PAR\](.*?)(?=\[PAR\]|$)", part, re.IGNORECASE | re.DOTALL
        )
        if paragraphs:
            for block in paragraphs:
                block = TAG.sub(" ", block)
                block = re.sub(r"\s+", " ", block).strip()
                for sent in split_sentences(block):
                    if sent:
                        units.append((title, sent))
        else:
            body = TAG.sub(" ", part)
            body = re.sub(r"\s+", " ", body).strip()
            for sent in split_sentences(body):
                if sent:
                    units.append((title, sent))
    return units


def evidence_units(context: str) -> list[tuple[str, str]]:
    if re.search(r"\[DOC\]", context, re.IGNORECASE):
        return parse_tagged(context)
    return parse_lines(context)


def add_candidate(cands: dict[str, dict], cand: str, typ: str) -> None:
    text = re.sub(r"\s+", " ", cand).strip(" ,.;:\"'()")
    if not text:
        return
    if len(text) > 120:
        return
    key = normalize(text)
    if not key or key in STOP or text in COMMON_CAP:
        return
    if text in MONTH_NAMES or text in GENERIC_TITLES:
        return
    # One- and two-digit bare numbers are usually fragments of dates, ranges,
    # or lists, not the answer surface.
    if re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?", text):
        return
    if key in cands:
        old = cands[key]
        if len(text) > len(old["text"]):
            old["text"] = text
        if typ not in old["types"]:
            old["types"].append(typ)
        return
    cands[key] = {"text": text, "types": [typ], "norm": key}


def _add_proper_digit_spans(cands: dict[str, dict], sent: str) -> None:
    """Add digit-containing proper-name phrases from a sentence.

    ``PROPER_DIGIT_RE`` starts at sentence-initial words too often, so this
    scanner walks word runs and starts a run only at a non-common capitalized
    word; the run may contain connectors, capitalized words, and digit tokens.
    """
    words = sent.split()
    i = 0
    n = len(words)
    while i < n:
        word = words[i].strip(" ,.;:\"'()")
        if (
            not word
            or word in COMMON_CAP
            or word.lower() in STOP_WORDS_LOWER
            or not word[0].isupper()
        ):
            i += 1
            continue
        j = i + 1
        while j < n:
            w = words[j].strip(" ,.;:\"'()")
            if not w:
                break
            if w in COMMON_CAP:
                break
            if (
                (w[0].isupper() or w.isdigit())
                or (
                    w.lower() in _CONNECTOR_WORDS
                    and not (words[j - 1].strip(" ,.;:\"'()").isdigit() if j > i else False)
                )
            ):
                j += 1
                continue
            break
        span = " ".join(words[i:j]).strip(" ,.;:\"'()")
        if any(ch.isdigit() for ch in span):
            add_candidate(cands, span, "NAME")
        i = j if j > i + 1 else i + 1


def extract_candidates(text: str) -> list[dict]:
    """Extract copyable candidate spans from one unit's title/body text."""
    cands: dict[str, dict] = {}
    # Dates and numbers over the full text.
    for date_re in DATE_RES:
        for m in date_re.finditer(text):
            add_candidate(cands, m.group(0), "DATE")
    for m in NUM_RE.finditer(text):
        add_candidate(cands, m.group(0), "NUM")
    for m in QUOTE_RE.finditer(text):
        add_candidate(cands, m.group(1) or m.group(2), "QUOTE")
    for m in OPTION_RE.finditer(text):
        add_candidate(cands, m.group(1), "OPTION")

    # Names and title phrases are extracted per sentence so they never cross
    # sentence boundaries.
    multiword_spans: list[str] = []
    for sent in split_sentences(text):
        for m in NAME_RE.finditer(sent):
            span = m.group(0)
            multiword_spans.append(span)
            add_candidate(cands, span, "NAME")
        for m in TITLE_PHRASE_RE.finditer(sent):
            span = m.group(0)
            words = span.split()
            if len(words) < 2:
                continue
            if words[0] in _CONNECTOR_WORDS or words[-1] in _CONNECTOR_WORDS:
                continue
            cap_words = [w for w in words if _CAP_WORD_RE.match(w)]
            if len(cap_words) < 2:
                continue
            if any(ch.isdigit() for ch in span):
                continue
            multiword_spans.append(span)
            add_candidate(cands, span, "NAME")
        for m in SINGLE_NAME_RE.finditer(sent):
            word = m.group(0)
            if (
                word in COMMON_CAP
                or word in MONTH_NAMES
                or word in GENERIC_TITLES
                or word.lower() in STOP_WORDS_LOWER
            ):
                continue
            # Sentence-initial single capitals are usually sentence subjects
            # or discourse markers, not answer spans; they are still allowed
            # if the word appears elsewhere in the same sentence.
            start = sent[:m.start()].strip()
            if not start:
                if sent[m.end():].strip().find(word) == -1:
                    continue
            # Suppress components of a longer name (e.g. "Nobel", "Prize"
            # when "Nobel Prize" is already a candidate).
            if any(word in span for span in multiword_spans):
                continue
            add_candidate(cands, word, "NAME")
    # Full person names with a quoted nickname and optional generational suffix.
    for sent in split_sentences(text):
        for m in PERSON_NICK_RE.finditer(sent):
            add_candidate(cands, m.group(0), "NAME")

    # Digit-containing proper names and company/official names that the
    # title-phrase extractor deliberately skipped.
    for sent in split_sentences(text):
        _add_proper_digit_spans(cands, sent)
        for m in ORG_SUFFIX_RE.finditer(sent):
            span = m.group(0)
            if not re.search(r"(?:\bCo\.?|\bLtd\.?|\bInc\.?|\bCorp\.?|\bLLC|\bS\.p\.A\.|\bS\.A\.|\bAG|\bGmbH|\bplc|\bLP|\bLLP)", span):
                continue
            add_candidate(cands, span, "NAME")

    # Short lowercase category/type phrases after copulas and similar verbs.
    for sent in split_sentences(text):
        for m in TYPE_PRED_RE.finditer(sent):
            phrase = m.group(1)
            words = phrase.split()
            if not (1 <= len(words) <= 5):
                continue
            if any(len(w) <= 1 for w in words):
                continue
            if all(w.lower() in STOP for w in words):
                continue
            add_candidate(cands, phrase, "TYPE")

    return list(cands.values())


def detect_question_type(question: str) -> tuple[str, bool]:
    """Return (target_type, is_comparison). Target type is only a hint."""
    q = question.lower()
    comparison = bool(re.search(
        r"\b(than|older|younger|more|less|fewer|fewest|taller|shorter|larger|"
        r"smaller|bigger|biggest|wider|widest|farther|further|furthest|closer|"
        r"closest|newer|newest|earlier|later|first|last|longest|shortest|"
        r"highest|lowest|most|least|before|after|between|among)\b",
        q,
    ))
    if re.search(r"\b(who|whom|whose)\b", q):
        return "NAME", comparison
    if re.search(r"\b(when|what year|what date|which year)\b", q):
        return "DATE", comparison
    if re.search(r"\bhow (many|much|old|long|far|tall)\b", q):
        return "NUM", comparison
    if re.search(r"\b(which of|choose|select|options?|\(a\)|\(b\)|\(c\)|\(d\))", q):
        return "CHOICE", comparison
    if re.search(
        r"\bwhere\b|\bwhich\s+(?:city|cities|town|village|state|province|county|"
        r"district|country|countries|nation|island|region|continent|territory|capital)\b",
        q,
    ):
        return "PLACE", comparison
    has_wh = re.search(r"\b(who|what|when|where|why|how|which|whom|whose)\b", q)
    if not has_wh and re.search(
        r"^\s*(did|does|do|is|are|was|were|has|have|had|can|could|will|would)\b", q
    ):
        return "YESNO", comparison
    if comparison:
        return "NAME", True
    return "ENTITY", False


def rare_count(tokens: list[str]) -> int:
    return sum(1 for tok in tokens if len(tok) > 3)


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0

    prompt = request.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        print("{}")
        return 0

    try:
        question, context = split_prompt(prompt)
        if not question or not context:
            print("{}")
            return 0
        q_norm = normalize(question)
        question_tokens = content_tokens(question)
        if not question_tokens:
            print("{}")
            return 0
        qset = set(question_tokens)
        units = evidence_units(context)
        if not units:
            print("{}")
            return 0
    except Exception:
        print("{}")
        return 0

    # ---- Unit feature extraction -------------------------------------------
    unit_info = []
    for index, (title, body) in enumerate(units):
        full = f"{title} {body}".strip() if title else body
        full_norm = normalize(full)
        full_tokens = [tok for tok in full_norm.split() if tok not in STOP]
        full_set = set(full_tokens)
        overlap = qset & full_set
        title_bonus = 1 if title else 0
        direct_score = (
            len(overlap) * 3 + rare_count(list(overlap)) * 2 + title_bonus
            if overlap
            else 0
        )
        cands = extract_candidates(title)
        cands += extract_candidates(body)
        # Deduplicate candidates that may have come from title and body.
        merged: dict[str, dict] = {}
        for c in cands:
            key = c["norm"]
            if key in merged:
                old = merged[key]
                if len(c["text"]) > len(old["text"]):
                    old["text"] = c["text"]
                old["types"] = list(dict.fromkeys(old["types"] + c["types"]))
            else:
                merged[key] = {
                    "text": c["text"],
                    "norm": key,
                    "types": c["types"],
                }
        cands = list(merged.values())
        cand_norms = {c["norm"] for c in cands}
        rare_set = {tok for tok in full_tokens if len(tok) > 3}
        rare_alias_set = token_alias_set(full)
        unit_info.append({
            "index": index,
            "title": title,
            "body": body,
            "full": full,
            "full_norm": full_norm,
            "full_set": full_set,
            "overlap": overlap,
            "direct_score": direct_score,
            "candidates": cands,
            "cand_norms": cand_norms,
            "rare_set": rare_set,
            "rare_alias_set": rare_alias_set,
        })

    # ---- Query-focused graph expansion (up to two hops) --------------------
    scores = {u["index"]: u["direct_score"] for u in unit_info if u["direct_score"] > 0}
    active = set(scores.keys())
    frontier = set(active)

    def shared_score(i: int, j: int) -> int:
        a = unit_info[i]
        b = unit_info[j]
        shared_cands = len(a["cand_norms"] & b["cand_norms"])
        shared_rare = len(a["rare_alias_set"] & b["rare_alias_set"])
        title_bonus = 0
        a_title = normalize(a["title"])
        b_title = normalize(b["title"])
        if a_title and (a_title in b["cand_norms"] or a_title in b["rare_alias_set"]):
            title_bonus += 2
        if b_title and (b_title in a["cand_norms"] or b_title in a["rare_alias_set"]):
            title_bonus += 2
        return shared_cands * 3 + shared_rare * 2 + title_bonus

    for _ in range(2):
        new_active = set()
        for u in unit_info:
            idx = u["index"]
            if idx in active:
                continue
            best = 0
            for fdx in frontier:
                s = shared_score(idx, fdx)
                if s > best:
                    best = s
            if best > 0:
                old = scores.get(idx, 0)
                scores[idx] = max(old, best)
                new_active.add(idx)
        if not new_active:
            break
        active |= new_active
        frontier = new_active

    ranked_units = sorted(
        unit_info,
        key=lambda u: (
            -scores.get(u["index"], 0),
            -u["direct_score"],
            -len(u["overlap"]),
        ),
    )

    # ---- Candidate scoring -------------------------------------------------
    qtype, is_comparison = detect_question_type(question)
    cand_map: dict[str, dict] = {}
    for u in unit_info:
        relevance = scores.get(u["index"], 0)
        for c in u["candidates"]:
            key = c["norm"]
            if key in cand_map:
                old = cand_map[key]
                if len(c["text"]) > len(old["text"]):
                    old["text"] = c["text"]
                old["support"] += relevance
                old["support_lines"].append((u["title"], u["body"], relevance))
                old["types"] = list(dict.fromkeys(old["types"] + c["types"]))
                continue
            cand_map[key] = {
                "text": c["text"],
                "norm": key,
                "types": c["types"],
                "support": relevance,
                "support_lines": [(u["title"], u["body"], relevance)],
            }

    for cand in cand_map.values():
        score = cand["support"]
        types = cand["types"]
        if qtype == "NAME" and "NAME" in types:
            score += 6
        elif qtype == "DATE" and "DATE" in types:
            score += 6
        elif qtype == "PLACE" and "NAME" in types:
            score += 6
        elif qtype == "NUM" and ("NUM" in types or "DATE" in types):
            score += 4
        elif qtype == "CHOICE" and "OPTION" in types:
            score += 8
        elif qtype == "ENTITY" and "TYPE" in types:
            score += 4
        if is_comparison and "NAME" in types:
            score += 2
        toks = cand["norm"].split()
        score += min(4, rare_count(toks))
        if len(toks) >= 2:
            score += 2
        # Known question-mentioned spans are almost always constraints, not
        # answers; keep them off the board unless they are also the only
        # plausible copyable surface.
        if (
            qtype != "CHOICE"
            and not is_comparison
            and set(cand["norm"].split()) <= set(q_norm.split())
        ):
            score -= 100
        best_line = max((r for _, _, r in cand["support_lines"]), default=0)
        score += min(6, best_line // 6)
        cand["score"] = score

    board = [
        c for c in sorted(cand_map.values(), key=lambda c: -c["score"])
        if c["score"] > 0
    ][:14]
    if not board:
        board = sorted(cand_map.values(), key=lambda c: -c["score"])[:5]

    # ---- Build explicit two-sentence bridge path witnesses -----------------
    direct_idx = [u["index"] for u in unit_info if u["direct_score"] >= 6]
    edges: list[tuple[int, int, int, set[str]]] = []
    for i in range(len(unit_info)):
        for j in range(i + 1, len(unit_info)):
            if unit_info[i]["title"] and unit_info[i]["title"] == unit_info[j]["title"]:
                continue
            shared_cands = unit_info[i]["cand_norms"] & unit_info[j]["cand_norms"]
            shared_rare = unit_info[i]["rare_alias_set"] & unit_info[j]["rare_alias_set"]
            if not shared_cands and not shared_rare:
                continue
            # Prefer bridges that are named entities, not dates or bare numbers.
            shared_names: set[str] = set()
            for norm_key in shared_cands:
                for u in (unit_info[i], unit_info[j]):
                    for c in u["candidates"]:
                        if c["norm"] == norm_key and "NAME" in c["types"]:
                            shared_names.add(c["text"])
                            break
                    if norm_key in shared_names:
                        break
            if not shared_names:
                continue
            score = len(shared_names) * 3 + min(4, len(shared_rare))
            edges.append((score, i, j, shared_names))
    edges.sort(key=lambda e: (-e[0], e[1], e[2]))
    path_witnesses: list[tuple[int, int, set[str], str, str]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for score, i, j, shared_names in edges:
        if i not in direct_idx and j not in direct_idx:
            continue
        key = (min(i, j), max(i, j))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        a = unit_info[i]
        b = unit_info[j]
        a_text = f"{a['title']} | " if a["title"] else ""
        a_text += a["body"]
        b_text = f"{b['title']} | " if b["title"] else ""
        b_text += b["body"]
        path_witnesses.append((score, i, j, shared_names, a_text, b_text))
        if len(path_witnesses) >= 12:
            break

    # ---- Surface role for each board candidate -----------------------------
    def surface_role(cand: dict) -> str:
        if not cand["support_lines"]:
            return "SPAN"
        title, body, _rel = cand["support_lines"][0]
        if title and normalize(title) == cand["norm"]:
            return "TITLE"
        body_norm = normalize(body)
        # First-sentence subject/definition forms are usually at the start of
        # the unit body (allow a leading article).
        start = body_norm
        if start.startswith("the "):
            start = start[4:]
        if start.startswith(cand["norm"]):
            return "FIRST"
        return "OBJECT"

    # ---- Build the injected map -------------------------------------------
    lines: list[str] = []
    lines.append(
        "DETERMINISTIC EVIDENCE MAP (a prioritized hypothesis shortlist; the "
        "full context below is authoritative and must still be read):"
    )
    lines.append(
        f"QUERY FRAME: target_type={qtype} comparison={is_comparison}"
    )

    lines.append("CANDIDATE BOARD (copyable spans to verify; role hints TITLE/FIRST/OBJECT):")
    for c in board:
        supp = c["support_lines"][:2]
        shown = []
        for title, body, rel in supp:
            prefix = f"{title} | " if title else ""
            text = prefix + body
            if len(text) > 220:
                text = text[:219] + "\u2026"
            shown.append(f"{text} [rel={rel}]")
        role = surface_role(c)
        lines.append(
            f"- \"{c['text']}\" [{','.join(c['types'])} role={role}] score={c['score']} | "
            + " || ".join(shown)
        )

    if path_witnesses:
        lines.append("BRIDGE PATH WITNESSES (two-sentence chains to verify; shared span in braces):")
        for score, i, j, shared_names, a_text, b_text in path_witnesses:
            bridge = ", ".join(sorted(shared_names)[:3]) if shared_names else "shared token"
            if len(a_text) > 170:
                a_text = a_text[:169] + "\u2026"
            if len(b_text) > 170:
                b_text = b_text[:169] + "\u2026"
            lines.append(f"- {a_text} --{{{bridge}}}--> {b_text} [edge={score}]")

    lines.append("EXPANDED EVIDENCE (direct + graph-expanded lines):")
    for u in ranked_units[:15]:
        prefix = f"{u['title']} | " if u["title"] else ""
        text = prefix + u["body"]
        if len(text) > 300:
            text = text[:299] + "\u2026"
        lines.append(f"- {text} [rel={scores.get(u['index'], 0)}]")

    additional_context = "\n".join(lines)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
