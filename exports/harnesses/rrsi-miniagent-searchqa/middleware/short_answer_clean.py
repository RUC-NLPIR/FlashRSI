"""Conservative deterministic short-answer surface cleaner.

Runs only when the task explicitly says to return only the short answer.
It performs lexical-only, context-gated normalization:

  * strip code fences and one matched pair of surrounding quotes
  * strip "answer is / answer:" lead-ins
  * strip True/False/Yes/No discourse lead-ins ("True — ...")
  * strip a trailing sentence period or repeated !/? only when the remaining
    phrase is supported verbatim by the supplied context
  * strip trailing parenthetical/bracket glosses only when the remaining
    phrase is a verbatim context phrase
  * strip trailing em/en-dash glosses only when the remaining phrase is a
    verbatim context phrase

For three recurring generic clue shapes it also reduces a verbose draft to
the requested head phrase, but only when the extracted phrase is itself a
verbatim context phrase:

  * factual-person statements ("he/his/her ...") -> leading name run
  * bare role/title clues ("President X", "Sultan Y") -> associated place
  * bare pair/list clues ("A,B") -> shared label after of/from/in

It never calls a model, never changes the selected entity, and deliberately
does NOT strip leading articles, shorten an organization/term to its first
word, or rewrite surface punctuation (case/hyphenation). Those decisions are
left to the bounded primary-model retry hook.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_MARKER = re.compile(r"^\[(?:DOC|TLE|PAR)\]$", re.IGNORECASE)
_DISCOURSE_LEAD_RE = re.compile(
    r"^(?:true|false|yes|no|correct|right|indeed)\s*[—–:]\s*(?P<tail>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_ANSWER_LEAD_RE = re.compile(
    r"^(?:(?:the\s+)?(?:correct|final|short)\s+)?answer\s*(?:is|:)?\s*",
    re.IGNORECASE,
)
_DASH_GLOSS_RE = re.compile(r"\s+[—–]\s+(?P<gloss>.+)$", re.DOTALL)
_TRAILING_GLOSS_RE = re.compile(r"\s*[\(\[][^\(\)\[\]]{0,120}[\)\]]\s*[.!?]*$")
_ABBREV_RE = re.compile(r"\b[A-Za-z]\.([A-Za-z]\.)?$")
_NAME_TOKEN_RE = re.compile(r"^[A-ZÀ-Þ][A-Za-zÀ-ÿ'\-]+$")

_DEF_DEMO_RE = re.compile(
    r"\b(this|that|these|those|it|its|term|name|who|what|which|when|where|why|how)\b",
    re.IGNORECASE,
)
_PERSON_PRONOUN_RE = re.compile(r"\b(he|his|him|she|her|hers)\b", re.IGNORECASE)
_PERSON_DEMO_RE = re.compile(r"\b(this|whose)\b", re.IGNORECASE)


def _short_answer_requested(question: str) -> bool:
    return "return only the short answer" in (question or "").lower()


def _question_line(question: str) -> str:
    if "Question:" in question:
        return question.rsplit("Question:", 1)[1].strip()
    return (question or "").strip()


def _context_text(question: str) -> str:
    if "Context:" not in question:
        return ""
    after = question.split("Context:", 1)[1]
    if "Question:" in after:
        after = after.rsplit("Question:", 1)[0]
    return after


def _norm_token(tok: str) -> str:
    s = tok.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s if ch.isalnum())


def _norm_text(text: str) -> str:
    return "".join(_norm_token(t) for t in text.split() if _norm_token(t))


def _context_keys(question: str) -> set[str]:
    """Return normalized n-gram keys for the supplied context (up to 6 tokens)."""
    ctx = _context_text(question)
    keys: set[str] = set()
    if not ctx:
        return keys

    for doc in re.split(r"\[DOC\]", ctx, flags=re.IGNORECASE):
        seq: list[str] = []
        for raw in doc.split():
            if _MARKER.match(raw.strip()):
                if seq:
                    max_n = min(6, len(seq))
                    for n in range(1, max_n + 1):
                        for i in range(len(seq) - n + 1):
                            keys.add("".join(seq[i : i + n]))
                    seq = []
                continue
            norm = _norm_token(raw)
            if not norm:
                if seq:
                    max_n = min(6, len(seq))
                    for n in range(1, max_n + 1):
                        for i in range(len(seq) - n + 1):
                            keys.add("".join(seq[i : i + n]))
                    seq = []
                continue
            seq.append(norm)
        if seq:
            max_n = min(6, len(seq))
            for n in range(1, max_n + 1):
                for i in range(len(seq) - n + 1):
                    keys.add("".join(seq[i : i + n]))
    return keys


def _strip_code_fences_and_quotes(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```") and t.endswith("```") and len(t) > 6:
        inner = t[3:-3].strip()
        inner = re.sub(r"^[A-Za-z]+\s*\n", "", inner)
        if inner:
            t = inner
    for quote in ('"', "'", "`"):
        if len(t) >= 2 and t.startswith(quote) and t.endswith(quote):
            inner = t[1:-1].strip()
            if inner:
                t = inner
                break
    return t.strip()


def _strip_discourse_lead(text: str) -> str:
    match = _DISCOURSE_LEAD_RE.match(text)
    if match:
        tail = match.group("tail").strip()
        if tail:
            return tail
    return text


def _strip_answer_lead(text: str) -> str:
    return _ANSWER_LEAD_RE.sub("", text).strip()


def _strip_trailing_punct(text: str, keys: set[str]) -> str:
    t = text
    while True:
        if t.endswith(".") and not t.endswith("..") and len(t) > 2:
            if _ABBREV_RE.search(t):
                return t
            if re.search(r"\b(?:Jr|Sr|St|Dr|Mr|Mrs|Ms|Mt)\.$", t, re.IGNORECASE):
                return t
            nxt = t[:-1].rstrip()
            if _norm_text(nxt) in keys:
                t = nxt
                continue
            return t

        match = re.search(r"[!?]+$", t)
        if not match:
            return t
        run = match.group(0)
        nxt = t[: match.start()].rstrip()
        if not nxt:
            return t
        if len(run) >= 2 or _norm_text(nxt) in keys:
            t = nxt
            continue
        return t


def _strip_trailing_parenthetical(text: str, keys: set[str]) -> str:
    match = _TRAILING_GLOSS_RE.search(text)
    if not match:
        return text
    nxt = text[: match.start()].strip()
    if nxt and _norm_text(nxt) in keys:
        return nxt
    return text


def _strip_trailing_dash_gloss(text: str, keys: set[str]) -> str:
    match = _DASH_GLOSS_RE.search(text)
    if not match:
        return text
    before = text[: match.start()].strip()
    if before and _norm_text(before) in keys:
        return before
    return text


def _looks_factual_person_statement(question_line: str) -> bool:
    return bool(_PERSON_PRONOUN_RE.search(question_line)) and not bool(
        _PERSON_DEMO_RE.search(question_line)
    )


def _extract_person_name_run(text: str, keys: set[str]) -> str | None:
    words = text.split()
    if len(words) < 2:
        return None
    run: list[str] = []
    for word in words:
        cleaned = word.strip(".,;:!?\"'`")
        if cleaned and _NAME_TOKEN_RE.match(cleaned):
            run.append(cleaned)
            if len(run) == 3:
                break
        else:
            break
    for length in range(len(run), 1, -1):
        candidate = " ".join(run[:length])
        if _norm_text(candidate) in keys:
            return candidate
    return None


def _looks_role_title_clue(question_line: str) -> bool:
    if not question_line or "," in question_line or _DEF_DEMO_RE.search(question_line):
        return False
    words = question_line.split()
    if not (2 <= len(words) <= 6):
        return False
    return all(word[:1].isupper() for word in words if word)


def _extract_role_title_place(text: str, keys: set[str]) -> str | None:
    matches = re.findall(r"\bof\s+([A-Z][A-Za-z]+)", text)
    for candidate in reversed(matches):
        if _norm_text(candidate) in keys:
            return candidate
    match = re.search(r"\bfrom\s+([A-Z][A-Za-z]+)", text)
    if match and _norm_text(match.group(1)) in keys:
        return match.group(1)
    return None


def _looks_pair_list_clue(question_line: str) -> bool:
    if not question_line or "," not in question_line or _DEF_DEMO_RE.search(question_line):
        return False
    parts = [p.strip() for p in question_line.split(",") if p.strip()]
    if not (2 <= len(parts) <= 5):
        return False
    for part in parts:
        words = part.split()
        if not (1 <= len(words) <= 5):
            return False
        if not all(word[:1].isupper() for word in words if word):
            return False
    return True


def _extract_pair_list_label(text: str, keys: set[str]) -> str | None:
    match = re.search(r"\b(?:from|of|in)\s+([A-Z][A-Za-z]+)(?=\s+(?:and|,)|$)", text)
    if match:
        candidate = match.group(1)
        if _norm_text(candidate) in keys:
            return candidate
    return None


def _clean(text: str, question: str) -> str:
    t = " ".join((text or "").split())
    if not t:
        return t

    keys = _context_keys(question)

    t = _strip_code_fences_and_quotes(t)
    t = _strip_discourse_lead(t)
    t = _strip_answer_lead(t)

    # Iteratively remove one trailing surface wrapper at a time. Every removal
    # is gated on the remaining phrase being a verbatim context n-gram, so the
    # pass never changes the selected entity.
    for _ in range(10):
        prev = t
        t = _strip_trailing_punct(t, keys)
        if t != prev:
            continue
        t = _strip_trailing_parenthetical(t, keys)
        if t != prev:
            continue
        t = _strip_trailing_dash_gloss(t, keys)
        if t != prev:
            continue
        break

    q = _question_line(question)
    if _looks_factual_person_statement(q) and len(t.split()) > 3:
        extracted = _extract_person_name_run(t, keys)
        if extracted:
            t = extracted
    elif _looks_role_title_clue(q):
        extracted = _extract_role_title_place(t, keys)
        if extracted:
            t = extracted
    elif _looks_pair_list_clue(q):
        extracted = _extract_pair_list_label(t, keys)
        if extracted:
            t = extracted

    return " ".join(t.split())


async def before_final(candidate: str, ctx: Any) -> dict | None:
    """Clean a final short answer into its bare requested surface form."""
    original = (candidate or "").strip()
    if not original or not _short_answer_requested(ctx.question):
        return None

    state = ctx.state.setdefault("short_answer_clean", {})
    state["replaced_this_turn"] = False

    cleaned = _clean(original, ctx.question)
    if cleaned and cleaned != original:
        state["replaced_this_turn"] = True
        ctx.trace.event(
            "short_answer_clean_replace",
            candidate=original,
            cleaned=cleaned,
        )
        return {"action": "replace", "answer": cleaned}
    return None
