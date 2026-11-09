"""Final-answer gate for short-answer exact-match tasks.

This is a formatting backstop only. It never looks at any ground truth and
only rewrites surface-form violations for a narrow set of generic question
shapes:
  * yes/no questions: keep only the lower-case decision
  * how-many questions: keep only the numeric/word-number answer
  * where questions: drop a leading locative preposition before a
    proper-noun place ("on Broadway" -> "Broadway")
  * "from where to where" questions: restore the leading "from [the]" when
    the completed phrase is verbatim in the supplied context
  * surrounding quotes when the whole answer is quoted

Anything that requires span completion, title expansion, name normalization,
or other evidence interpretation is intentionally out of scope.
"""

from __future__ import annotations

import re

_NUMBER_WORDS = {
    "one": "one",
    "two": "two",
    "three": "three",
    "four": "four",
    "five": "five",
    "six": "six",
    "seven": "seven",
    "eight": "eight",
    "nine": "nine",
    "ten": "ten",
    "eleven": "eleven",
    "twelve": "twelve",
    "thirteen": "thirteen",
    "fourteen": "fourteen",
    "fifteen": "fifteen",
    "sixteen": "sixteen",
    "seventeen": "seventeen",
    "eighteen": "eighteen",
    "nineteen": "nineteen",
    "twenty": "twenty",
}

_YES_NO_QUESTION = re.compile(
    r"^(?:are|do|does|did|was|were|is|am|can|could|will|would|has|have|should|shall|may|might)\b",
    re.IGNORECASE,
)
_HOW_MANY = re.compile(r"how many", re.IGNORECASE)
_WHERE_QUESTION = re.compile(r"\bwhere\b", re.IGNORECASE)
_FROM_TO_QUESTION = re.compile(r"\bfrom\s+where\s+to\s+where\b", re.IGNORECASE)


def _question_text(ctx) -> str:
    text = ctx.question or ""
    match = re.search(r"Question:\s*\n(.*)$", text, re.DOTALL | re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else text


def _how_many_unit(question: str) -> str:
    """Return the noun phrase following 'how many' in a question, lower-cased."""
    match = re.search(
        r"how many\s+(.*?)\s*[?.]*\s*$", question, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return ""
    return re.sub(r"[^a-z0-9 -]", "", match.group(1).lower()).strip()


def _strip_unit(answer: str, unit: str) -> str | None:
    """Return the leading number if `answer` is that number plus `unit`."""
    if not unit:
        return None
    unit_re = re.escape(unit)
    match = re.match(
        r"^([0-9][0-9,]*(?:\.\d+)?)\s+" + unit_re + r"\s*[.]?$",
        answer,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    number_word_alt = "|".join(_NUMBER_WORDS)
    match = re.match(
        r"^(" + number_word_alt + r")\s+" + unit_re + r"\s*[.]?$",
        answer,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).lower()
    return None


def _strip_where_preposition(answer: str) -> str | None:
    """Drop a leading locative preposition before a proper-noun place.

    Only fires when the remainder is a proper-noun place phrase (each word
    capitalized), so phrases such as ``in the north`` or ``on the west bank``
    are left untouched.
    """
    match = re.match(
        r"^(?:on|in|at)\s+((?:[A-Z][A-Za-z0-9'.-]*(?:\s+[A-Z][A-Za-z0-9'.-]*)*))"
        r"\s*[.]?$",
        answer,
    )
    if not match:
        return None
    place = match.group(1).strip()
    if not place or place.lower() in {"the", "a", "an"}:
        return None
    return place


def _restore_from_to_prefix(answer: str, question: str, full_text: str) -> str | None:
    """Restore a leading 'from [the]' dropped from a complete evidence phrase.

    Only fires for ``from where to where`` questions, and only when the exact
    answer appears in the supplied context immediately after ``from``, so no
    content is invented.
    """
    if not _FROM_TO_QUESTION.search(question):
        return None
    clean = answer.strip()
    if not clean or clean.lower().startswith("from "):
        return None
    clean = clean.rstrip(".")
    if not clean:
        return None
    match = re.search(
        r"\bfrom\s+(?:the\s+)?" + re.escape(clean),
        full_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(0)


async def before_final(answer: str, ctx) -> dict | None:
    if "Return only the short answer" not in (ctx.question or ""):
        return None

    clean = answer.strip()
    if not clean:
        return None

    # Drop surrounding quotes only when the entire answer is quoted.
    if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in ('"', "'"):
        inner = clean[1:-1].strip()
        if inner:
            clean = inner

    question = _question_text(ctx)
    full_text = ctx.question or ""

    # Yes/no questions: keep only the lower-case yes/no decision.
    if _YES_NO_QUESTION.match(question):
        match = re.match(r"^(yes|no)\b", clean, re.IGNORECASE)
        if match:
            return {"action": "replace", "answer": match.group(1).lower()}

    # How-many questions: keep only the numeric answer when a unit was echoed.
    if _HOW_MANY.search(question):
        unit = _how_many_unit(question)
        stripped = _strip_unit(clean, unit) if unit else None
        if stripped:
            return {"action": "replace", "answer": stripped}
        # Hedge phrase before a bare number: "Around 2,300." -> "2,300".
        match = re.match(
            r"^(?:around|approximately|about|roughly|nearly|over|under)\s+"
            r"([0-9][0-9,]*(?:\.\d+)?)\s*[.]?$",
            clean,
            re.IGNORECASE,
        )
        if match:
            return {"action": "replace", "answer": match.group(1)}

    # Where questions: drop a leading locative preposition before a
    # proper-noun place, but only when that place is present in the context.
    if _WHERE_QUESTION.search(question):
        stripped = _strip_where_preposition(clean)
        if stripped and stripped in full_text:
            return {"action": "replace", "answer": stripped}

    # From-where-to-where questions: restore the leading "from [the]" only
    # when the completed phrase is verbatim in the supplied context.
    restored = _restore_from_to_prefix(clean, question, full_text)
    if restored:
        return {"action": "replace", "answer": restored}

    # If only surrounding quotes were removed, persist the cleaner form.
    if clean != answer:
        return {"action": "replace", "answer": clean}

    return None
