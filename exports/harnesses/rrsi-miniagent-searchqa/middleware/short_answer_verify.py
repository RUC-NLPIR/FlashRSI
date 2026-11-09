"""Bounded side-model verification gate for short-answer QA.

Runs after the deterministic cleaner and the primary-model retry hooks, so it
only inspects candidates those hooks already accepted. It asks a side model to
re-derive the answer and judge the draft. When the verdict is WRONG it returns
a bounded ``continue`` so the primary model gets one more attempt with the
reason.

The side model never authors the final answer: it only supplies a verdict and
a short reason. The primary model remains the sole author of the final message.

Bounds:
  * at most two side calls per task
  * at most one ``continue`` from this hook per task
  * candidates that the deterministic cleaner just produced are trusted and
    skipped (the cleaner only strips surface wrappers around a selected entity)
  * single-token candidates are skipped; the retry hook handles their
    inflection/plural mismatches
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_MARKER = re.compile(r"^\[(?:DOC|TLE|PAR)\]$", re.IGNORECASE)
_PERSON_DEMO_RE = re.compile(r"\b(this|that|these|those|whose)\b", re.IGNORECASE)
_SHORT_NAME_MARKERS = ("surname", "nickname", "acronym", "short name", "initials")
_NAME_TOKEN_RE = re.compile(r"^[A-ZÀ-Þ][A-Za-zÀ-ÿ'\-.]*$")


def _short_answer_requested(question: str) -> bool:
    return "return only the short answer" in (question or "").lower()


def _question_line(question: str) -> str:
    if "Question:" in question:
        return question.rsplit("Question:", 1)[1].strip()
    return (question or "").strip()


def _is_full_name_demo_clue(question: str, draft: str) -> bool:
    """True for a context-backed full-name answer to a generic this/whose
    person clue. These are deliberately skipped so the side model cannot
    demand a surname-only shortening that would break exact match."""
    q = _question_line(question).lower()
    if not _PERSON_DEMO_RE.search(q):
        return False
    if any(marker in q for marker in _SHORT_NAME_MARKERS):
        return False
    words = draft.split()
    if not (2 <= len(words) <= 4):
        return False
    return all(_NAME_TOKEN_RE.match(word) for word in words)


def _norm_token(tok: str) -> str:
    s = tok.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s if ch.isalnum())


def _norm_text(text: str) -> str:
    return "".join(_norm_token(t) for t in text.split() if _norm_token(t))


def _context_text(question: str) -> str:
    if "Context:" not in question:
        return ""
    after = question.split("Context:", 1)[1]
    if "Question:" in after:
        after = after.rsplit("Question:", 1)[0]
    return after


def _context_phrase_keys(question: str) -> set[str]:
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


def _prompt(question: str, draft: str) -> str:
    return (
        "You are checking a short-answer draft for an exact-match grader. "
        "Use ONLY the supplied context below.\n\n"
        "Step 1: Determine the single correct short answer.\n"
        "- Apply every clue and constraint in the question.\n"
        "- Choose the context passage that satisfies all of them.\n"
        "- For a definition/category clue (\"An X that does Y\", \"the term for ...\", "
        "\"this type of ...\"), return the general category or term whose function "
        "is stated, not a salient example sharing only one property.\n"
        "- For a person clue, verify every stated fact, number, date, or role is "
        "stated in the chosen person's passage. For a factual statement about a "
        "person (\"he/his/her ...\"), keep the person's full name as introduced "
        "in the context; do not shorten a full name to a surname or drop an "
        "honorific unless the question explicitly asks for a surname, nickname, "
        "or initials.\n"
        "- For a Jeopardy-style \"this ...\" or \"whose ...\" person clue, "
        "accept a context-supported full name unless the question explicitly asks "
        "for a surname, nickname, or initials.\n"
        "- Use the exact wording from the supplied context for the requested form "
        "(short name, surname, plural, hyphenation).\n\n"
        "Step 2: Compare your answer to the draft below. Do not write out your answer.\n\n"
        + question
        + "\n\nDraft answer:\n"
        + draft
        + "\n\n"
        "End your reply with exactly one line, either:\n"
        "CORRECT\n"
        "or\n"
        "WRONG <brief reason the draft fails, without stating the correct answer>"
    )


def _parse_verdict(text: str) -> tuple[str | None, str]:
    """Return (verdict, reason) from the last recognizable verdict line."""
    verdict: str | None = None
    reason = ""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for i, line in enumerate(lines):
        match = re.match(r"^(CORRECT|WRONG)\b[:\-]?\s*(.*)$", line, re.IGNORECASE)
        if not match:
            continue
        verdict = match.group(1).lower()
        reason = match.group(2).strip()
        if not reason and verdict == "wrong" and i + 1 < len(lines):
            nxt = lines[i + 1]
            if not re.match(r"^(CORRECT|WRONG)\b", nxt, re.IGNORECASE):
                reason = nxt
    return verdict, reason


def _feedback(draft: str, reason: str) -> str:
    reason_text = f" It said: {reason}" if reason else ""
    return (
        "The instruction says: \"Return only the short answer.\" "
        "An independent check found that your previous answer may not satisfy "
        "every clue in the question or may not be the exact requested form."
        + reason_text
        + "\n"
        "Previous answer:\n"
        + draft
        + "\n\n"
        "If your previous answer already satisfies every clue and is copied "
        "verbatim from the supplied context, return it unchanged. Otherwise list "
        "every explicit clue and constraint, find the single context phrase that "
        "satisfies all of them, and discard a specific example or partial match "
        "when the question asks for a general category or term. Return only the "
        "corrected short answer, copied verbatim from the supplied context."
    )


async def before_final(candidate: str, ctx: Any) -> dict | None:
    """Judge a settled short-answer candidate and, on a wrong verdict, ask the
    primary model for one more bounded attempt."""
    original = (candidate or "").strip()
    if not original or not _short_answer_requested(ctx.question):
        return None

    words = original.split()
    if len(words) < 2:
        return None

    # The deterministic cleaner only removes wrappers around a selected entity.
    # Trusting its replacement avoids spending side calls on already-cleaned
    # surface form and keeps this gate focused on wrong-entity selection.
    clean_state = ctx.state.get("short_answer_clean") or {}
    if clean_state.get("replaced_this_turn"):
        return None

    context_keys = _context_phrase_keys(ctx.question)
    if _norm_text(original) not in context_keys:
        return None

    # Full-name answers to generic this/whose person clues are correct as-is;
    # do not spend a side call that could over-shorten them to a surname.
    if _is_full_name_demo_clue(ctx.question, original):
        return None

    state = ctx.state.setdefault("short_answer_verify", {})
    if state.get("continued", 0) >= 1:
        return None
    if state.get("side_calls", 0) >= 2:
        return None
    if getattr(ctx, "remaining_turns", 0) <= 0:
        return None
    if getattr(ctx, "_final_continues", 0) >= getattr(ctx, "_final_continue_max", 3):
        return None

    state["side_calls"] = state.get("side_calls", 0) + 1
    try:
        extracted = await ctx.side_text(
            _prompt(ctx.question, original),
            purpose="short_answer_verify",
            max_tokens=120,
        )
    except Exception as e:
        ctx.trace.event("short_answer_verify_error", error=str(e))
        return None

    if not extracted:
        return None

    verdict, reason = _parse_verdict(extracted)
    if verdict == "correct":
        ctx.trace.event("short_answer_verify_accept", draft=original)
        return None

    if verdict != "wrong":
        ctx.trace.event(
            "short_answer_verify_ignored",
            reason="unrecognized_verdict",
            side=extracted,
        )
        return None

    ctx.trace.event("short_answer_verify_wrong", draft=original, reason=reason)
    state["continued"] = 1
    return {"action": "continue", "feedback": _feedback(original, reason)}
