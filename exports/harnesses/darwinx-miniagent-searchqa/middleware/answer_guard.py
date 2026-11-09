"""Conservative final-answer guard for short-answer QA.

The frozen model usually returns the short answer directly. This hook only
intervenes in two narrow cases so it cannot disturb compact, already-correct
answers:

1. The answer is wrapped in boilerplate ("The answer is ...", "Answer: ...",
   "It is ...", surrounding quotes). The wrapper is stripped deterministically.
2. The answer is a long, sentence-like draft. A side-model call rewrites it as
   the short answer, and the replacement is accepted only when it is grounded
   in the supplied question/context or the original draft.

Both paths are additive and leave any short answer byte-for-byte unchanged.
"""

from __future__ import annotations

import re
from typing import Any

_MAX_SHORT_WORDS = 6
_MAX_EXTRACT_WORDS = 10

_PREFIX_PATTERNS = [
    r"^(?:the\s+)?(?:correct\s+|right\s+)?answer\s*(?:is|:)?\s*",
    r"^answer\s*:\s*",
    r"^(?:it|this|that|the\s+(?:entity|person|place|thing|answer))\s+is\s+",
]
_WRAPPER_RE = re.compile("|".join(_PREFIX_PATTERNS), re.IGNORECASE)

_SENTENCE_SIGNALS = [
    r"\b(?:is|are|was|were|has|have|had)\b",
    r"\b(?:refers?\s+to|known\s+as|called|named|means?|stands?\s+for|describes?)\b",
    r"\b(?:the\s+answer\s+is|i\s+(?:think|believe)|it\s+is|this\s+is|that\s+is)\b",
]

_STOP_ANSWERS = {
    "a",
    "an",
    "it",
    "its",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "those",
    "what",
    "which",
    "who",
}


def _strip_wrappers(text: str) -> str:
    """Remove leading quotes and common answer prefixes, iteratively."""
    previous = None
    while previous != text:
        previous = text
        text = text.strip().strip('"\'`').strip()
        text = _WRAPPER_RE.sub("", text, count=1).strip()
    return text


def _strip_trailing_punct(text: str) -> str:
    """Remove trailing punctuation/whitespace from a wrapper-stripped answer."""
    return re.sub(r"[\s.!?;:]+$", "", text).strip()


def _looks_like_sentence(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _SENTENCE_SIGNALS)


def _contains_text(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    return needle.casefold() in haystack.casefold()


async def before_final(answer: str, ctx: Any) -> dict | None:
    if not isinstance(answer, str) or not answer.strip():
        return None

    candidate = answer.strip()
    stripped = _strip_wrappers(candidate)
    had_wrapper = stripped != candidate
    if had_wrapper:
        stripped = _strip_trailing_punct(stripped)

    words = stripped.split()
    if not words:
        return None

    # Deterministic path: a compact answer hidden under boilerplate/quotes.
    if had_wrapper:
        if len(words) <= _MAX_EXTRACT_WORDS:
            return {"action": "replace", "answer": stripped}
        candidate_for_extraction = stripped
    else:
        candidate_for_extraction = candidate

    # Already a compact answer — leave it untouched.
    if len(words) <= _MAX_SHORT_WORDS:
        return None

    # Verbose, sentence-like draft: ask the side model to reduce it. This is a
    # guarded fallback; it only runs for long sentence-shaped answers and the
    # replacement must be grounded in the evidence already available.
    if not _looks_like_sentence(candidate_for_extraction):
        return None

    question_context = getattr(ctx, "question", "") or ""
    prompt = (
        "Answer the short-answer question below using the supplied context. "
        "The draft answer is provided only as a hint and may be too long or "
        "worded awkwardly. Return the single short answer that directly "
        "answers the question. Preserve exact names, numbers, and dates from "
        "the context. Do not include explanations, citations, or closing "
        "punctuation unless the answer itself requires it.\n\n"
        f"Question and context:\n{question_context}\n\n"
        f"Draft answer:\n{candidate_for_extraction}\n\n"
        "Short answer:"
    )
    extracted = await ctx.side_text(
        prompt,
        purpose="answer_guard_extract",
        max_tokens=80,
    )
    if not isinstance(extracted, str):
        return None

    extracted = _strip_trailing_punct(_strip_wrappers(extracted.strip()))
    extracted_words = extracted.split()
    if not (1 <= len(extracted_words) <= _MAX_EXTRACT_WORDS):
        return None
    if extracted.casefold() in _STOP_ANSWERS:
        return None
    if extracted.casefold() == candidate.casefold():
        return None

    # Accept the rewrite only when it is grounded in the original draft or the
    # supplied question/context; otherwise keep the model's original answer.
    if _contains_text(candidate_for_extraction, extracted) or _contains_text(
        question_context, extracted
    ):
        return {"action": "replace", "answer": extracted}

    return None
