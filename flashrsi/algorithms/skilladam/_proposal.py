"""SkillAdam's text Worker protocol for issue observations and bounded edits."""

import json


def apply_proposal(reply, text, budget, memory):
    # Do not unwrap fences inside a JSON skill replacement.
    raw = reply.strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.partition("\n")[2][:-3]
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("expected an issues array")
    edits = data.get("edits")
    if not isinstance(edits, list) or len(edits) > budget:
        raise ValueError("expected an edits array within the current budget")

    labels = set(memory)
    observations = []
    for issue in data["issues"]:
        label = _string(issue, "label")
        status = _string(issue, "status")
        if status not in ("open", "resolved"):
            raise ValueError("issue status must be open or resolved")
        observations.append((label, status, _string(issue, "evidence")))
        labels.add(label)

    # Model replies commonly use LF even when Git checked out the skill as CRLF.
    # Translate only the edit fragments, preserving all untouched file bytes.
    crlf = "\r\n" in text and "\n" not in text.replace("\r\n", "")
    attempts = []
    for edit in edits:
        label = _string(edit, "label")
        if label not in labels:
            raise ValueError("edit refers to an unreported issue")
        before = _string(edit, "before")
        after = edit.get("after")
        if not isinstance(after, str):
            raise ValueError("edit requires a replacement string")
        if crlf or "\r\n" not in text:
            newline = "\r\n" if crlf else "\n"
            before = before.replace("\r\n", "\n").replace("\n", newline)
            after = after.replace("\r\n", "\n").replace("\n", newline)
        start = text.find(before)
        if start < 0 or text.find(before, start + 1) >= 0:
            raise ValueError("edit requires a unique exact excerpt")
        text = text.replace(before, after, 1)
        attempts.append((label, _string(edit, "approach")))
    return text, observations, attempts


def _string(item, field):
    value = item.get(field) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"expected a non-empty string for {field}")
    return value
