"""Bounded primary-model self-correction for short-answer QA.

Runs after the deterministic cleaner. It asks the *primary* model for one more
bounded attempt when the cleaned candidate is still unlikely to be the bare
exact-match short answer:

1. Prose-like candidate under an explicit "return only the short answer"
   instruction.
2. Candidate that is not a verbatim n-gram from the supplied context, so it
   cannot be the exact short answer the task expects.
3. Candidate that is a verbatim context phrase with a shorter context-phrase
   prefix/suffix and the question explicitly asks for a short name form
   (surname, nickname, acronym, initials, or a "known as" target). Generic
   "this ..." person/company clues are deliberately not shortened.
4. Candidate whose normalized phrase has a more frequent space-separated
   context surface (for example "Picture-in-picture" vs "Picture in Picture").

The primary model remains the only author of the final answer; this hook only
supplies feedback. Each trigger fires at most once per task and the runtime's
remaining-turn and final-continue budgets bound every retry, so this cannot
loop.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_MARKER = re.compile(r"^\[(?:DOC|TLE|PAR)\]$", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"\$[0-9][0-9,]*")
_ALPHA_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_DOC_SPLIT_RE = re.compile(r"\[DOC\]", re.IGNORECASE)
_LEADING_ARTICLE = {"a", "an", "the"}
_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")
_GLOSS_PUNCT_RE = re.compile(r"[()\[\]{}<>—–,;:]")
_PROSE_LEAD_RE = re.compile(r"^(?:true|false|yes|no|correct|right|indeed)\b", re.I)
_NAME_TOKEN_RE = re.compile(r"^[A-ZÀ-Þ][A-Za-zÀ-ÿ'\-]+$")

# Strong cues that the requested form is shorter than the full context phrase.
_SHORT_FORM_MARKERS = (
    "surname",
    "nickname",
    "nicknamed",
    "acronym",
    "short name",
    "initials",
    "known as",
    "referred to as",
    "called it",
    "term for",
    "type of",
)

_PRODUCE_PLANT_CUE_RE = re.compile(
    r"\b(this|that|these|those)\s+"
    r"(fruit|fruits|vegetable|vegetables|berry|berries|plant|plants|crop|crops)\b",
    re.IGNORECASE,
)


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


def _context_phrase_keys(question: str) -> set[str]:
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


def _context_surfaces(question: str) -> dict[str, dict[str, int]]:
    """Return normalized n-gram key -> surface form counts."""
    ctx = _context_text(question)
    surfaces: dict[str, dict[str, int]] = {}
    if not ctx:
        return surfaces

    for doc in re.split(r"\[DOC\]", ctx, flags=re.IGNORECASE):
        seq: list[tuple[str, str]] = []
        for raw in doc.split():
            if _MARKER.match(raw.strip()):
                if seq:
                    max_n = min(6, len(seq))
                    for n in range(1, max_n + 1):
                        for i in range(len(seq) - n + 1):
                            toks = seq[i : i + n]
                            key = "".join(t[0] for t in toks)
                            phrase = " ".join(t[1] for t in toks)
                            bucket = surfaces.setdefault(key, {})
                            bucket[phrase] = bucket.get(phrase, 0) + 1
                    seq = []
                continue
            norm = _norm_token(raw)
            if not norm:
                if seq:
                    max_n = min(6, len(seq))
                    for n in range(1, max_n + 1):
                        for i in range(len(seq) - n + 1):
                            toks = seq[i : i + n]
                            key = "".join(t[0] for t in toks)
                            phrase = " ".join(t[1] for t in toks)
                            bucket = surfaces.setdefault(key, {})
                            bucket[phrase] = bucket.get(phrase, 0) + 1
                    seq = []
                continue
            seq.append((norm, raw))
        if seq:
            max_n = min(6, len(seq))
            for n in range(1, max_n + 1):
                for i in range(len(seq) - n + 1):
                    toks = seq[i : i + n]
                    key = "".join(t[0] for t in toks)
                    phrase = " ".join(t[1] for t in toks)
                    bucket = surfaces.setdefault(key, {})
                    bucket[phrase] = bucket.get(phrase, 0) + 1
    return surfaces


def _passages(question: str) -> list[tuple[list[str], str]]:
    """Split the supplied context into [DOC]-bounded documents.

    Each document is returned as (normalized_tokens, raw_text) so callers can
    check both normalized containment and raw surface details like ``$20``.
    """
    ctx = _context_text(question)
    passages: list[tuple[list[str], str]] = []
    for part in _DOC_SPLIT_RE.split(ctx):
        raw = " ".join(part.split())
        if not raw.strip():
            continue
        tokens = [_norm_token(tok) for tok in raw.split() if _norm_token(tok)]
        if tokens:
            passages.append((tokens, raw))
    return passages


def _currency_amounts(text: str) -> list[str]:
    return sorted(set(_CURRENCY_RE.findall(text or "")))


def _candidate_key(candidate: str) -> str | None:
    """Return the first non-article alphabetic token of the candidate.

    Only the head token is used for document lookup. Using all tokens would
    let a generic trailing word (``Mint``, ``Company``, ``Network``) match the
    question restatement itself and hide the gap we are trying to detect.
    """
    for token in _ALPHA_TOKEN_RE.findall(candidate or ""):
        if token.lower() not in _LEADING_ARTICLE:
            return token
    return None


def _looks_prose(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    words = text.split()
    if len(words) >= 6:
        return True
    if len(words) >= 3 and (
        _SENTENCE_END_RE.search(text) or _GLOSS_PUNCT_RE.search(text)
    ):
        return True
    if len(words) >= 2 and _PROSE_LEAD_RE.match(text):
        return True
    return False


def _looks_overexpanded(text: str, question: str) -> bool:
    q = _question_line(question).lower()
    words = text.split()
    if len(words) < 2:
        return False

    keys = _context_phrase_keys(question)
    key = _norm_text(text)
    if key not in keys:
        return False

    # Only explicit short-name requests justify asking for a shorter phrase.
    # Generic "this ..." person/company clues and organization/association
    # clues are deliberately excluded because evidence shows they make the
    # model over-shorten correct full names (Oliver Brown -> Brown,
    # Ace Hardware -> Ace, Lord Robert Baden-Powell -> Robert Baden-Powell).
    if not any(marker in q for marker in _SHORT_FORM_MARKERS):
        return False

    for n in range(1, len(words)):
        if _norm_text(" ".join(words[:n])) in keys:
            return True
    last = _norm_text(words[-1])
    if last in keys and last != key:
        return True
    return False


def _surface_needs_verification(text: str, surfaces: dict[str, dict[str, int]]) -> bool:
    """True when a clean space-separated context surface is clearly more frequent.

    This is deliberately narrow: it only asks the model to re-check a
    hyphenated/single-token candidate when the same normalized phrase has a
    more frequent multi-word, space-separated surface with no surrounding
    punctuation. It never rewrites the answer itself, so legitimate
    hyphenated terms such as "look-alike" are only kept or re-emitted by the
    primary model.
    """
    key = _norm_text(text)
    bucket = surfaces.get(key)
    if not bucket:
        return False

    cand_cf = (text or "").casefold()
    cand_best = 0
    space_best = 0
    for surface, count in bucket.items():
        if surface.casefold() == cand_cf:
            cand_best = max(cand_best, count)
        # A clean space-separated variant: no surrounding punctuation, at
        # least one internal space, and no hyphen.
        if surface == surface.strip(" .,;:!?\"'`") and " " in surface and "-" not in surface:
            space_best = max(space_best, count)
    return space_best > cand_best


def _inflection_variants(key: str) -> set[str]:
    """Return plausible singular/plural inflections of a single-token key.

    This is deliberately narrow (``s``, ``es``, ``y -> ies`` and their
    reverse) so compounds such as ``strawberryland`` are never linked to
    ``strawberry``.
    """
    variants: set[str] = set()
    if not key:
        return variants
    if key.endswith("y") and len(key) > 2:
        variants.add(key[:-1] + "ies")
    variants.add(key + "s")
    variants.add(key + "es")
    if key.endswith("ies") and len(key) > 4:
        variants.add(key[:-3] + "y")
    if key.endswith("es") and len(key) > 3:
        variants.add(key[:-2])
    if key.endswith("s") and not key.endswith("ss") and len(key) > 2:
        variants.add(key[:-1])
    return variants


def _single_token_context_keys(question: str) -> set[str]:
    """Return normalized single-token forms present anywhere in the context."""
    ctx = _context_text(question)
    keys: set[str] = set()
    if not ctx:
        return keys
    for doc in re.split(r"\[DOC\]", ctx, flags=re.IGNORECASE):
        for raw in doc.split():
            if _MARKER.match(raw.strip()):
                continue
            norm = _norm_token(raw)
            if norm:
                keys.add(norm)
    return keys


def _looks_single_token_inflection_gap(text: str, question: str) -> bool:
    """Detect a one-word produce/plant candidate with a same-stem variant in
    the context (for example ``Strawberry`` when the context also contains
    ``strawberries``). The primary model decides which number is requested."""
    words = text.split()
    if len(words) != 1:
        return False
    if not _PRODUCE_PLANT_CUE_RE.search(_question_line(question)):
        return False
    key = _norm_text(text)
    if not key:
        return False
    variants = _inflection_variants(key)
    for other in _single_token_context_keys(question):
        if other != key and other in variants:
            return True
    return False


def _prose_feedback(draft: str) -> str:
    return (
        "The instruction says: \"Return only the short answer.\" "
        "Your previous answer was not the bare short answer.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the question and the supplied context. Identify the single "
        "requested item and reply with only that item, using the exact surface "
        "form from the supplied context. No lead-in, explanation, parenthetical, "
        "gloss, date, or trailing punctuation."
    )


def _exact_phrase_feedback(draft: str) -> str:
    return (
        "The instruction says: \"Return only the short answer.\"\n"
        "Your previous answer is not a verbatim phrase from the supplied "
        "context, so it cannot be the exact short answer.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the question and the supplied context. Identify the single "
        "requested item and reply with only that item, copied verbatim from "
        "the supplied context. Do not include any lead-in, explanation, "
        "parenthetical, gloss, date, or extra punctuation. If the question is "
        "a definition or category clue (\"An X that does Y\", \"this type "
        "of ...\", \"the term for ...\"), return the general category or "
        "term whose function the context states, not a specific example that "
        "shares only one property."
    )


def _short_form_feedback(draft: str) -> str:
    return (
        "The instruction says: \"Return only the short answer.\"\n"
        "Your previous answer appears to be longer than the requested short "
        "form, or uses a fuller name than the clue asks for.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the question. Determine the shortest exact phrase from the "
        "supplied context that still satisfies every clue (for example a "
        "nickname, term, acronym, surname, or short company/network/mint/"
        "association name). For a definition or category clue (\"An X that "
        "does Y\", \"this type of ...\", \"the term for ...\"), return "
        "the general category or term whose function the context states, not "
        "a specific example sharing only one property. If the shorter phrase "
        "no longer satisfies every clue or no longer names the same entity, "
        "keep the full phrase. Do not drop given names, honorifics, or "
        "required company words, and do not replace a name with an epithet "
        "or descriptor. Return only the correct exact phrase."
    )


def _surface_feedback(draft: str) -> str:
    return (
        "The instruction says: \"Return only the short answer.\"\n"
        "Your previous answer may not use the exact spacing and hyphenation "
        "of the supplied context.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the supplied context and copy the requested phrase exactly "
        "as it appears there, preserving spaces, hyphens, capitalization, and "
        "punctuation. Return only the corrected phrase."
    )


def _single_token_feedback(draft: str) -> str:
    return (
        "The instruction says: \"Return only the short answer.\"\n"
        "Your one-word answer may be the right entity but the wrong number or "
        "surface form.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the supplied context and find how the requested item is written "
        "there (singular or plural, exact spelling and capitalization). For a "
        "fruit/vegetable/berry/plant clue, return the noun form the context uses "
        "for the food itself, not the attributive form used in festival or brand "
        "names. Return only that exact form."
    )


def _missing_currency_feedback(amounts: list[str], draft: str) -> str:
    joined = ", ".join(amounts)
    return (
        "The instruction says: \"Return only the short answer.\"\n"
        "A constraint check found that the question explicitly mentions the "
        f"amount(s) {joined}, but the document supporting your previous answer "
        "does not state that amount.\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "Re-read the supplied context and find the entity whose own document "
        f"states the amount(s) {joined} and satisfies every other clue. "
        "Discard candidates that match only a keyword but not the amount. "
        "Return only that entity's short name, using the exact surface form "
        "from the supplied context. No explanation or extra formatting."
    )


async def before_final(candidate: str, ctx: Any) -> dict | None:
    original = (candidate or "").strip()
    if not original or not _short_answer_requested(ctx.question):
        return None

    state = ctx.state.setdefault("short_answer_retry", {})
    if state.get("fired", 0) >= 5:
        return None
    if getattr(ctx, "remaining_turns", 0) <= 0:
        return None
    if getattr(ctx, "_final_continues", 0) >= getattr(ctx, "_final_continue_max", 3):
        return None

    # Trigger 0: currency-amount constraint gap. Runs before the general
    # format/non-context triggers so a wrong keyword-only candidate gets the
    # more specific amount feedback instead.
    if state.get("currency_fired", 0) < 1:
        amounts = _currency_amounts(_question_line(ctx.question))
        if amounts:
            passages = _passages(ctx.question)
            key = _candidate_key(original)
            if passages and key:
                key_norm = _norm_text(key)
                candidate_docs: list[str] = []
                for _, raw in passages:
                    if key_norm in _norm_text(raw):
                        candidate_docs.append(raw)
                if candidate_docs:
                    context_raw = _context_text(ctx.question)
                    missing = [
                        amount
                        for amount in amounts
                        if amount in context_raw
                        and all(amount not in raw for raw in candidate_docs)
                    ]
                    if missing:
                        state["currency_fired"] = 1
                        state["fired"] = state.get("fired", 0) + 1
                        ctx.trace.event(
                            "short_answer_retry_currency_gap",
                            candidate=original,
                            missing_amounts=missing,
                        )
                        return {
                            "action": "continue",
                            "feedback": _missing_currency_feedback(missing, original),
                        }

    # Trigger 1: prose-like candidate under an explicit short-answer request.
    if state.get("prose_fired", 0) < 1 and _looks_prose(original):
        state["prose_fired"] = 1
        state["fired"] = state.get("fired", 0) + 1
        ctx.trace.event("short_answer_retry_prose", candidate=original)
        return {"action": "continue", "feedback": _prose_feedback(original)}

    # Trigger 2: candidate is not a verbatim phrase from the supplied context.
    if state.get("non_context_fired", 0) < 1:
        context_keys = _context_phrase_keys(ctx.question)
        if _norm_text(original) not in context_keys:
            state["non_context_fired"] = 1
            state["fired"] = state.get("fired", 0) + 1
            ctx.trace.event("short_answer_retry_non_context", candidate=original)
            return {
                "action": "continue",
                "feedback": _exact_phrase_feedback(original),
            }

    # Trigger 3: candidate is a context phrase but longer than the requested
    # short form. The primary model decides whether a shorter phrase is valid.
    if state.get("overexpanded_fired", 0) < 1 and _looks_overexpanded(
        original, ctx.question
    ):
        state["overexpanded_fired"] = 1
        state["fired"] = state.get("fired", 0) + 1
        ctx.trace.event("short_answer_retry_overexpanded", candidate=original)
        return {"action": "continue", "feedback": _short_form_feedback(original)}

    # Trigger 4: hyphen/space surface ambiguity for the same phrase.
    if state.get("surface_fired", 0) < 1:
        surfaces = _context_surfaces(ctx.question)
        if _surface_needs_verification(original, surfaces):
            state["surface_fired"] = 1
            state["fired"] = state.get("fired", 0) + 1
            ctx.trace.event("short_answer_retry_surface", candidate=original)
            return {"action": "continue", "feedback": _surface_feedback(original)}

    # Trigger 5: one-word produce/plant candidate with a same-stem context
    # variant (usually singular vs plural). Ask the primary model to copy the
    # exact context form rather than rewriting the answer deterministically.
    if state.get("single_form_fired", 0) < 1:
        if _looks_single_token_inflection_gap(original, ctx.question):
            state["single_form_fired"] = 1
            state["fired"] = state.get("fired", 0) + 1
            ctx.trace.event("short_answer_retry_single_form", candidate=original)
            return {"action": "continue", "feedback": _single_token_feedback(original)}

    return None
