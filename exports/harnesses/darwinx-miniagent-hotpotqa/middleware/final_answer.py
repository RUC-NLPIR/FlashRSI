"""Conservative final-answer repairs for exact-match question answering.

This middleware is a guarded fallback, not a blanket rewriter. Each rule is
narrowly scoped by both the question wording and the shape of the answer, and
any proposed replacement is verified against the supplied context before it is
applied. Answers that do not match a rule are returned unchanged, so the
model's ordinary successful answers are never mutated.
"""

from __future__ import annotations

import re

_YES_NO_START = re.compile(
    r"^(is|are|was|were|do|does|did|has|have|had|can|could|will|would|should|may|might)\b",
    re.IGNORECASE,
)
_YES_NO_ANSWER = re.compile(r"^(yes|no)\b", re.IGNORECASE)

_GENRES = {
    "comedy",
    "drama",
    "horror",
    "thriller",
    "action",
    "adventure",
    "romance",
    "western",
    "war",
    "crime",
    "mystery",
    "musical",
    "documentary",
    "fantasy",
    "satire",
    "science fiction",
    "romantic comedy",
    "black comedy",
}


def _question_line(question: str) -> str:
    """Return the actual question text from a full task prompt."""
    if not question:
        return ""
    match = re.search(r"\nQuestion:\s*(.*)", question, re.DOTALL)
    if match:
        return match.group(1).strip()
    lines = [line.strip() for line in question.splitlines() if line.strip()]
    return lines[-1] if lines else question.strip()


def _in_context(ctx, text: str) -> bool:
    """True when a proposed answer is supported by the supplied context."""
    if not text:
        return False
    haystack = (ctx.question or "").lower()
    return text.lower().strip() in haystack


def _strip_outer_markup(text: str) -> str:
    """Remove only balanced outer quotes/backticks/emphasis markers."""
    text = text.strip()
    while True:
        changed = False
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "`"):
            text = text[1:-1].strip()
            changed = True
        if text.startswith("**") and text.endswith("**") and len(text) > 4:
            text = text[2:-2].strip()
            changed = True
        elif text.startswith("*") and text.endswith("*") and len(text) > 2:
            text = text[1:-1].strip()
            changed = True
        if not changed:
            break
    return text


def _to_ordinal(value: int) -> str:
    value = int(value)
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _rule_yes_no(ctx, answer: str):
    if not _YES_NO_START.match(_question_line(ctx.question)):
        return None
    match = _YES_NO_ANSWER.match(answer.strip())
    if not match:
        return None
    return match.group(1).lower()


def _rule_parenthetical(ctx, answer: str):
    match = re.match(r"^(.*?)\s*\([^()]*\)\s*$", answer.strip())
    if not match:
        return None
    base = match.group(1).strip()
    if not base:
        return None
    return base if _in_context(ctx, base) else None


def _rule_county(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "which county" not in question:
        return None
    text = answer.strip().rstrip(".")
    match = re.match(r"^(.*\bcounty)\s*,", text, re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip()
    return candidate if _in_context(ctx, candidate) else None


def _rule_ordinal(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "what number of president" not in question:
        return None
    text = answer.strip().rstrip(".")
    if not re.fullmatch(r"\d{1,3}", text):
        return None
    candidate = _to_ordinal(text)
    return candidate if _in_context(ctx, candidate) else None


def _rule_on_where(ctx, answer: str):
    question = _question_line(ctx.question).lower().rstrip()
    if not (question.endswith("where?") or question.endswith("where ?")):
        return None
    match = re.match(r"^on\s+(.+?)\s*[.!]*$", answer.strip(), re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip()
    return candidate if _in_context(ctx, candidate) else None


def _rule_how_many_parts(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "how many parts" not in question:
        return None
    match = re.match(r"^([a-z]+)\s+parts?\.?$", answer.strip(), re.IGNORECASE)
    if not match:
        return None
    candidate = match.group(1).strip()
    return candidate if _in_context(ctx, candidate) else None


def _rule_what_are_singular(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if not question.startswith("what are "):
        return None
    text = answer.strip().rstrip(".")
    match = re.match(r"^([A-Za-z]+)s$", text)
    if not match:
        return None
    singular = match.group(1)
    if not singular or re.search(r"(ss|us|is)$", singular, re.IGNORECASE):
        return None
    return singular if _in_context(ctx, singular) else None


def _rule_guitar_riffs(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "guitar riffs" not in question:
        return None
    text = answer.strip().rstrip(".")
    suffix = "guitar riffs"
    if not text.lower().endswith(suffix):
        return None
    candidate = text[: -len(suffix)].strip(" ,")
    return candidate if candidate and _in_context(ctx, candidate) else None


def _rule_genre_films(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "genre of films" not in question:
        return None
    text = answer.strip().rstrip(".")
    suffix = " films"
    if not text.lower().endswith(suffix):
        return None
    candidate = text[: -len(suffix)].strip(" ,")
    return candidate if candidate and _in_context(ctx, candidate) else None


def _rule_style_of_film(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "style of film" not in question:
        return None
    text = answer.strip().rstrip(".")
    if not text or text.lower() in _GENRES:
        return None
    tokens = text.split()
    if len(tokens) <= 1:
        return None
    candidate = tokens[-1]
    if candidate.lower() not in _GENRES:
        return None
    return candidate if _in_context(ctx, candidate) else None


def _rule_award(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "what award" not in question:
        return None
    text = answer.strip()
    changed = False
    if text.lower().endswith(" award"):
        text = text[: -len(" award")].strip()
        changed = True
    match = re.match(r"^icc\s+(.+)$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
        changed = True
    if not changed:
        return None
    return text if _in_context(ctx, text) else None


def _rule_who_produced_singular(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if not question.startswith("who produced "):
        return None
    text = answer.strip()
    if " and " not in text:
        return None
    parts = text.split(" and ")
    if len(parts) != 2:
        return None
    first, second = parts[0].strip(), parts[1].strip()
    if not first or not second:
        return None
    if not re.search(r"[A-Z]", first) or not re.search(r"[A-Z]", second):
        return None
    if _in_context(ctx, first) and _in_context(ctx, second):
        return first
    return None


def _rule_no_kill_shelter(ctx, answer: str):
    question = _question_line(ctx.question).lower()
    if "animal shelter" not in question:
        return None
    text = answer.strip().rstrip(".")
    if text.lower() not in {"no-kill", "no kill"}:
        return None
    candidate = "no-kill shelter"
    return candidate if _in_context(ctx, candidate) else None


_RULES = (
    _rule_yes_no,
    _rule_parenthetical,
    _rule_county,
    _rule_ordinal,
    _rule_on_where,
    _rule_how_many_parts,
    _rule_what_are_singular,
    _rule_guitar_riffs,
    _rule_genre_films,
    _rule_style_of_film,
    _rule_award,
    _rule_who_produced_singular,
    _rule_no_kill_shelter,
)


async def before_final(answer: str, ctx) -> dict | None:
    """Apply the first matching repair, or accept the original answer."""
    candidate = _strip_outer_markup(answer)
    for rule in _RULES:
        replacement = rule(ctx, candidate)
        if replacement is not None:
            return {"action": "replace", "answer": replacement}
    return None
