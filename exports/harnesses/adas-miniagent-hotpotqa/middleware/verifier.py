"""Reference-first span calibration gate for context-based QA.

The previous span-lock gate treated any literal candidate as good.  That is not
enough: a candidate like "Air Italy" is a literal substring of "Air Italy
S.p.A." (or a title prefix of a fuller name), and the gate accepted it even
though the requested answer was the fuller exact phrase.  Symmetrically, a
candidate like "the Dallas Cowboys and Denver Broncos" is literal but has an
extra leading article.

This gate therefore extracts an independent reference answer span from the
exact evidence *before* judging, and uses it to calibrate the candidate's
boundaries.  When both candidate and reference are literal spans and one is a
small fuller/shorter form of the other, the independently extracted reference
wins and is returned verbatim.  The side-LLM semantic verdict is still used for
outright wrong answers, for yes/no and other non-span answers, and as a
continue/revision channel.
"""

from __future__ import annotations

import copy
import difflib
import re
import unicodedata
from pathlib import Path

_VERIFY_MAX_TOKENS = 500
_EXTRACT_MAX_TOKENS = 400
_MAX_EVIDENCE = 8000
_MAX_POOL_CHARS = 40000
_MAX_SEARCH_ITEMS = 3
_MAX_READ_CHARS = 2000
_MAX_SNIPPET = 300


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _extracted_notes(artifact_path):
    if not artifact_path:
        return ""
    path = Path(artifact_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    marker = "## Extracted Notes"
    if marker in text:
        text = text.split(marker, 1)[1]
    if "## Raw Page Snapshot" in text:
        text = text.split("## Raw Page Snapshot", 1)[0]
    return text.strip()


def _build_evidence(ctx):
    """Optional tool evidence, used only if the agent gathered any."""
    parts = []

    for sr in ctx.searches:
        parts.append(f"SEARCH: {sr.query}")
        for item in (sr.items or [])[:_MAX_SEARCH_ITEMS]:
            title = str(item.get("title", ""))[:200]
            url = str(item.get("url", ""))[:300]
            snippet = str(item.get("snippet", ""))[:_MAX_SNIPPET]
            parts.append(f"- {title} | {url}")
            parts.append(f"  {snippet}")

    for rd in ctx.reads:
        content = _extracted_notes(rd.artifact_path)
        if not content:
            content = rd.content_preview or ""
        parts.append(
            f"READ: {rd.url} (focus: {rd.focus}, success: {rd.success})"
        )
        parts.append(content[:_MAX_READ_CHARS])

    evidence = "\n".join(parts).strip()
    if len(evidence) > _MAX_EVIDENCE:
        evidence = evidence[:_MAX_EVIDENCE] + "\n[evidence truncated]"
    return evidence or ""


_ANSWER_LABEL_RE = re.compile(
    r"^\s*(?:\*\*|__)?\s*(?:final\s+answer|answer|response)\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _clean_answer(value):
    """Return a stripped, quote/bold/answer-label-normalized answer string."""
    text = (value or "").strip()
    for _ in range(4):
        changed = False
        line = _strip_markdown_line(text)
        if line != text:
            text = line
            changed = True
        m = _ANSWER_LABEL_RE.match(text)
        if m and (m.group(1) or "").strip():
            text = m.group(1).strip()
            changed = True
        if len(text) >= 2:
            if text[0] == text[-1] and text[0] in {'"', "'"}:
                text = text[1:-1].strip()
                changed = True
            elif text[0] == "\u201c" and text[-1] == "\u201d":
                text = text[1:-1].strip()
                changed = True
            elif text[0] == "\u2018" and text[-1] == "\u2019":
                text = text[1:-1].strip()
                changed = True
        if len(text) >= 4:
            if text.startswith("**") and text.endswith("**"):
                text = text[2:-2].strip()
                changed = True
            elif text.startswith("__") and text.endswith("__"):
                text = text[2:-2].strip()
                changed = True
        if not changed:
            break
    return text


_CONNECTIVE_RE = re.compile(r"^\s*(?:is|was|equals?|=)\s+", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_VERDICT_RE = re.compile(
    r"^\s*(?:\*\*|__)?(GOOD|ANSWER|CONTINUE)\b\s*(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*(.*)$",
    re.IGNORECASE,
)
_EXTRACT_RE = re.compile(
    r"^\s*(?:\*\*|__)?ANSWER\b\s*(?:\*\*|__)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*$")


def _strip_markdown_line(line):
    """Remove a leading markdown bullet and one pair of bold markers."""
    line = _BULLET_RE.sub("", line).strip()
    if line.startswith("**") and line.endswith("**") and len(line) >= 4:
        line = line[2:-2].strip()
    elif line.startswith("__") and line.endswith("__") and len(line) >= 4:
        line = line[2:-2].strip()
    return line


def _is_subsequence(tokens_a, tokens_b):
    """True if every token in `tokens_a` appears in `tokens_b` in order."""
    it = iter(tokens_b)
    return all(any(t == b for b in it) for t in tokens_a)


def _related_answer(candidate, extracted, max_extra=2, allow_same_tokens=True):
    """Conservative wording-fix heuristic used for span-boundary calibration.

    ``max_extra`` bounds how many tokens may be added or removed when one
    answer is a fuller/shorter form of the other.  The default remains small,
    but calibration between two literal spans uses a slightly larger budget so
    full legal names (e.g. "Casio" -> "Casio Computer Co., Ltd." or
    "Ted Shackelford" -> "Theodore Tillman \"Ted\" Shackelford III") can be
    recovered without opening the door to arbitrary sentence replacements.
    """
    cand_norm = _normalize(candidate)
    ext_norm = _normalize(extracted)
    if not cand_norm or not ext_norm:
        return False
    if cand_norm == ext_norm:
        return True

    cand_tokens = cand_norm.split()
    ext_tokens = ext_norm.split()

    # Same tokens, different order/punctuation.  This is useful for cleaning up
    # a side-LLM paraphrase, but is deliberately disabled for literal-span
    # calibration, where a different order is a different context span.
    if allow_same_tokens:
        if len(cand_tokens) == len(ext_tokens) and sorted(cand_tokens) == sorted(ext_tokens):
            return True

    # One is a slightly fuller/shorter form of the other.  The >= 2 guard
    # avoids matching a single stop-word inside a long phrase, but a one-token
    # answer (a bare number, surname, or company short name) still needs to be
    # expandable/trimmable when the other side is a short literal span.
    if len(cand_tokens) >= 2 and _is_subsequence(cand_tokens, ext_tokens):
        if len(ext_tokens) <= len(cand_tokens) + max_extra:
            return True
    if len(ext_tokens) >= 2 and _is_subsequence(ext_tokens, cand_tokens):
        if len(cand_tokens) <= len(ext_tokens) + max_extra:
            return True
    if len(cand_tokens) == 1 and _is_subsequence(cand_tokens, ext_tokens):
        if len(ext_tokens) <= 1 + max_extra:
            return True
    if len(ext_tokens) == 1 and _is_subsequence(ext_tokens, cand_tokens):
        if len(cand_tokens) <= 1 + max_extra:
            return True

    return False


def _calibration_related(candidate, extracted):
    """Relatedness test for two literal spans.

    This is deliberately wider than the original repair heuristic because both
    sides are already guaranteed to be verbatim evidence spans.  The calibration
    only changes boundaries (adds/removes a small number of tokens), never
    invents text or reorders an accepted span.
    """
    return _related_answer(
        candidate, extracted, max_extra=4, allow_same_tokens=False
    )


def _parse_verdict(verdict):
    text = (verdict or "").strip()
    if not text:
        return "accept", None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for raw_line in lines:
        line = _strip_markdown_line(raw_line)
        m = _VERDICT_RE.match(line)
        if not m:
            continue
        marker = m.group(1).upper()
        rest = (m.group(2) or "").strip()
        rest = re.sub(r"^\s*(?:\*\*|__)\s*", "", rest).strip()
        rest = re.sub(r"\s*(?:\*\*|__)\s*$", "", rest).strip()

        if marker == "GOOD":
            return "accept", None
        if marker == "ANSWER":
            corrected = _clean_answer(_CONNECTIVE_RE.sub("", rest, count=1).strip())
            if corrected:
                return "replace", corrected
        if marker == "CONTINUE":
            feedback = _CONNECTIVE_RE.sub("", rest, count=1).strip()
            return "continue", feedback or "Re-read the supplied context and revise the answer."

    # No marker found: treat as implicit acceptance rather than rewriting.
    return "accept", None


# ---------------------------------------------------------------------------
# Literal span locking
# ---------------------------------------------------------------------------


def _fold_char(ch):
    """Return the lowercase ASCII alphanumeric form of one character, if any."""
    if not ch.isalnum():
        return None
    folded = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
    if not folded:
        return None
    return folded.lower()


def _norm_chars(text):
    out = []
    for ch in str(text or ""):
        folded = _fold_char(ch)
        if folded:
            out.append(folded)
    return "".join(out)


def _edge_punctuation(needle):
    """Return (leading_punctuation, trailing_punctuation) from `needle`."""
    text = str(needle or "")
    lead = ""
    i = 0
    while i < len(text) and _fold_char(text[i]) is None:
        lead += text[i]
        i += 1
    trail = ""
    j = len(text) - 1
    while j >= 0 and _fold_char(text[j]) is None:
        trail = text[j] + trail
        j -= 1
    return lead, trail


def _find_span(needle, haystack):
    """Return the exact original substring in `haystack` matching `needle`.

    Matching is case/punctuation/accent-insensitive, but when the same
    normalized characters occur more than once, the occurrence whose original
    spelling/punctuation is closest to `needle` is preferred.  The returned
    span is copied verbatim from `haystack`.  Matches must start and end on
    token boundaries so a short answer cannot be matched inside an unrelated
    word.  Punctuation that the candidate itself carries at its edges is
    preserved in the returned span.
    """
    needle_text = str(needle or "")
    needle_norm = _norm_chars(needle_text)
    if not needle_norm:
        return None

    hay = str(haystack or "")
    hay_norm_chars = []
    norm_to_orig = []
    for i, ch in enumerate(hay):
        folded = _fold_char(ch)
        if folded:
            for sub in folded:
                hay_norm_chars.append(sub)
                norm_to_orig.append(i)

    hay_norm = "".join(hay_norm_chars)
    if not hay_norm:
        return None

    lead, trail = _edge_punctuation(needle_text)
    best = None
    best_key = None

    pos = hay_norm.find(needle_norm)
    while pos != -1:
        start = norm_to_orig[pos]
        end = norm_to_orig[pos + len(needle_norm) - 1] + 1

        prev_ok = start == 0 or _fold_char(hay[start - 1]) is None
        next_ok = end >= len(hay) or _fold_char(hay[end]) is None
        if prev_ok and next_ok:
            if lead and start >= len(lead) and hay[start - len(lead):start] == lead:
                start -= len(lead)
            if trail and end + len(trail) <= len(hay) and hay[end:end + len(trail)] == trail:
                end += len(trail)
            span = hay[start:end]
            # Avoid accepting a fake match that jumps across the blank line
            # between two different messages/tool outputs.
            if not ("\n\n" in span and "\n\n" not in needle_text):
                # Prefer exact original spelling/punctuation; otherwise prefer
                # the occurrence most similar to the candidate, then the
                # earliest occurrence.
                if span == needle_text:
                    return span
                ratio = difflib.SequenceMatcher(None, needle_text, span).ratio()
                key = (-ratio, pos)
                if best_key is None or key < best_key:
                    best_key = key
                    best = span

        pos = hay_norm.find(needle_norm, pos + 1)

    return best


def _snapshot_pool(ctx):
    """Reconstruct the evidence text the main agent actually saw."""
    messages = (ctx.state.get("span_lock") or {}).get("messages") or []
    parts = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in {"user", "tool"}:
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content)

    if not parts:
        question = ctx.question or ""
        if question:
            parts.append(question)

    return "\n\n".join(parts).strip()


def _clip_for_llm(text, limit=_MAX_POOL_CHARS):
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + "\n\n[...truncated middle of evidence...]\n\n"
        + text[-half:]
    )


def _build_pool(ctx):
    parts = [_snapshot_pool(ctx)]
    evidence = _build_evidence(ctx)
    if evidence:
        parts.append(evidence)
    return "\n\n".join(p for p in parts if p).strip()


def _verdict_prompt(context_block, candidate):
    return f"""You are the final-answer gate for a context-based question-answering agent.

Question and supplied context (user/tool messages and any tool output):
{_clip_for_llm(context_block)}

Proposed final answer:
{candidate}

Decide whether the proposed final answer is correct and formatted exactly as requested.

Rules:
- The answer must be factually supported by the supplied context.
- It must answer every part of the question.
- It must use the exact wording from the context for names, numbers, dates, and technical terms. Do not allow abbreviations, nicknames, paraphrases, rounded values, or omitted middle names when the context gives a fuller exact form.
- Keep units and qualifiers only when they are part of the exact answer phrase in the context; otherwise remove them.
- If the user asked to return only the short answer, the answer must contain no explanation, citations, leading phrases, or extra punctuation.
- If the proposed answer is already correct and exact, reply exactly:
GOOD
- If the proposed answer is wrong, incomplete, or not exact, reply with the corrected short answer copied exactly from the context:
ANSWER: <corrected short answer>
- Use CONTINUE only when the context is genuinely ambiguous and the agent should re-read a specific part:
CONTINUE: <specific instruction>
"""


def _extract_prompt(context_block, variant):
    focus_line = {
        1: (
            "Identify the type of answer requested (person, place, company, date, "
            "year, number, yes/no, etc.). Then find the exact phrase that is the "
            "short answer. For a person, company, or place prefer the fullest exact "
            "name used in the relevant evidence sentence (include middle names, "
            "legal suffixes, and leading \"The\" only when they are part of that "
            "phrase). For dates and numbers return only the component the question "
            "asks for. Do not copy a title prefix when the sentence contains the "
            "fuller exact form."
        ),
        2: (
            "Independently re-read the context from the beginning. Do not rely on "
            "any previous answer; locate the shortest exact phrase that directly "
            "answers the question. Pay special attention to boundaries: do not "
            "include a leading article, trailing unit, parenthetical, or suffix "
            "unless the question asks for that full phrase."
        ),
    }[variant]
    return f"""You are an exact-span extractor for a context question-answering agent.

Question and supplied context (user/tool messages and any tool output):
{_clip_for_llm(context_block)}

{focus_line}

Return the exact contiguous span of text from the evidence that is the short answer to the question.

Rules:
- Copy the span exactly: same spelling, punctuation, word order, units, dates, and middle names as the evidence.
- The span must appear verbatim in the evidence text above.
- Do not normalize, round, abbreviate, reorder, explain, or add units.
- If the question requires a yes/no or other answer that is not literally present in the evidence, reply exactly:
NONE
- Otherwise reply exactly:
ANSWER: <exact span>
"""


async def _extract_once(pool, ctx, question, variant=1):
    raw = await ctx.side_text(
        _extract_prompt(pool, variant),
        purpose=f"span_extract_{variant}",
        max_tokens=_EXTRACT_MAX_TOKENS,
    )
    if not raw:
        return None

    stripped_lines = []
    for raw_line in raw.splitlines():
        line = _strip_markdown_line(raw_line)
        if not line:
            continue
        stripped_lines.append(line)
        upper = line.upper()
        if re.match(r"^NONE\b", upper):
            return None
        m = _EXTRACT_RE.match(line)
        if m:
            value = _clean_answer(
                _CONNECTIVE_RE.sub("", (m.group(1) or ""), count=1).strip()
            )
            if value:
                return _find_span(value, pool)
            return None

    # Some models return only the bare span instead of the requested marker.
    if len(stripped_lines) == 1:
        value = _clean_answer(
            _CONNECTIVE_RE.sub("", stripped_lines[0], count=1).strip()
        )
        if value:
            return _find_span(value, pool)

    return None


def _looks_like_title_prefix(span, pool):
    """True when `span` appears as a context title/label immediately before ':'.

    This is the main way a main model produces a too-short person/company name:
    the linearized context has "Christian Clemenson: Christian Dayton Clemenson
    (...)" and the model copies the title prefix.  Such candidates should be
    challenged with a second extractor; ordinary sentence spans should not.
    """
    needle = str(span or "")
    if not needle or not pool:
        return False
    idx = pool.find(needle)
    while idx != -1:
        end = idx + len(needle)
        if end < len(pool) and pool[end] == ":":
            # Prefer only when it looks like a standalone label, not an in-text
            # colon such as "said Air Italy: it was ...".  A line-start,
            # newline-separated title prefix, or markdown list-item label is
            # the reliable case.
            prefix = pool[:idx]
            if (
                prefix == ""
                or prefix.endswith("\n")
                or prefix.endswith("\r")
                or _LIST_PREFIX_RE.match(prefix)
            ):
                return True
        idx = pool.find(needle, idx + 1)
    return False


async def _extract_reference(pool, ctx, question, candidate_span=None):
    """Return the best independent reference span.

    The first extractor is answer-type aware and is usually sufficient.  If it
    disagrees with a literal candidate, its independent span is trusted.  If it
    agrees with the candidate, we normally keep that agreement; only when the
    candidate is a context title prefix do we ask a second boundary-focused
    extractor to re-read from scratch, because "Air Italy" or
    "Christian Clemenson" can be a too-short title while the full answer is in
    the next sentence.
    """
    first = await _extract_once(pool, ctx, question, variant=1)
    if first is None:
        return await _extract_once(pool, ctx, question, variant=2)

    if candidate_span is None:
        return first

    if _normalize(first) != _normalize(candidate_span):
        return first

    # First extractor agrees with a literal candidate.  Only challenge that
    # agreement when the candidate is a context title prefix, because that is
    # exactly where a fuller form usually exists one sentence later.  In normal
    # sentence spans, the agreement is strong and we keep the candidate.
    if not _looks_like_title_prefix(candidate_span, pool):
        return first

    second = await _extract_once(pool, ctx, question, variant=2)
    if second is None:
        return first
    return second


async def before_llm(messages, ctx):
    """Snapshot the exact messages the main model sees.

    The final gate uses this snapshot so it checks the real supplied context and
    tool output rather than relying only on ctx.question.
    """
    ctx.state.setdefault("span_lock", {})["messages"] = copy.deepcopy(messages)
    return messages


async def before_final(answer, ctx):
    original = _clean_answer(answer)

    def _lower_yes_no(value):
        norm = _normalize(value)
        if norm == "yes":
            return "yes"
        if norm == "no":
            return "no"
        return value

    candidate = _lower_yes_no(original)
    yesno = candidate in {"yes", "no"}

    pool = _build_pool(ctx)
    candidate_span = _find_span(candidate, pool)

    # 1. Independent reference extraction.  This runs even when the candidate is
    #    literal, because a literal substring may still have the wrong boundaries.
    ref_span = await _extract_reference(pool, ctx, ctx.question, candidate_span)

    # 2. Semantic verdict for wrong answers, yes/no, and revision requests.
    verdict = await ctx.side_text(
        _verdict_prompt(pool, candidate),
        purpose="final_verify",
        max_tokens=_VERIFY_MAX_TOKENS,
    )
    action, value = _parse_verdict(verdict)

    if action == "continue":
        return {"action": "continue", "feedback": value}

    if action == "replace":
        corrected = _lower_yes_no(_clean_answer(value))
        if yesno or corrected in {"yes", "no"}:
            return {"action": "replace", "answer": corrected}

        corrected_span = _find_span(corrected, pool)
        if corrected_span:
            return {"action": "replace", "answer": corrected_span}

        # The verifier's correction may be paraphrased; use the independent
        # literal reference when it is a conservative wording fix.
        if ref_span and (
            _related_answer(corrected, ref_span)
            or _calibration_related(candidate, ref_span)
        ):
            return {"action": "replace", "answer": ref_span}

        # If the candidate is already literal and means the same as the
        # correction, prefer the context's own wording.
        if candidate_span and _normalize(candidate_span) == _normalize(corrected):
            return {"action": "replace", "answer": candidate_span}

        # If the side LLM's "correction" is only a case/punctuation echo of the
        # candidate, do not send the agent back for wording that cannot be made
        # more literal.
        if _normalize(candidate) == _normalize(corrected):
            return {"action": "accept"}

        return {
            "action": "continue",
            "feedback": (
                "Re-read the supplied context and copy the exact wording of the "
                "answer. Do not paraphrase, round, abbreviate, or add units that "
                "are not part of the context phrase."
            ),
        }

    # 3. Verdict accepted.  Calibrate span boundaries against the independent
    #    reference when both are literal and one is a small fuller/shorter form
    #    of the other.
    if candidate_span and ref_span:
        if _normalize(candidate_span) != _normalize(ref_span):
            if _calibration_related(candidate_span, ref_span):
                return {"action": "replace", "answer": ref_span}

    if candidate_span:
        if yesno:
            if original != candidate:
                return {"action": "replace", "answer": candidate}
            return {"action": "accept"}
        if candidate_span != candidate:
            # Lock to the exact context spelling/punctuation.
            return {"action": "replace", "answer": candidate_span}
        return {"action": "accept"}

    # Accepted but not literal.  If the independent reference is a conservative
    # wording fix for the candidate, lock to that span; otherwise keep the side
    # LLM's semantic acceptance.
    if ref_span and _calibration_related(candidate, ref_span):
        return {"action": "replace", "answer": ref_span}

    if yesno and original != candidate:
        return {"action": "replace", "answer": candidate}

    return {"action": "accept"}
