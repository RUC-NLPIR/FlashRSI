"""Final-answer artifact gate.

Several verifiers check for required files at exact paths rather than reading the
assistant's final text. Agents sometimes finish with a passing candidate in a
scratch location, or declare completion after analysis, while the required file
was never written. This hook scans the question for deliverable paths (under
/app, plus quoted/backticked relative file names), and if any are missing when
the model tries to finalize, it returns `continue` with concrete feedback instead
of accepting the answer.

The check is deliberately conservative:
  * only sentences containing a write/save/create/generate/download/... cue are
    considered, so provided inputs are not mistaken for outputs;
  * paths explicitly described as provided/given are skipped;
  * alternatives joined by "or" only need one member to exist;
  * a per-run continue budget prevents endless loops.

It uses only local filesystem existence checks and never fabricates or grades
task content.
"""

from __future__ import annotations

import re
from pathlib import Path

_CUE_RE = re.compile(
    r"\b(write|writes|written|save|saves|saved|store|stores|stored|"
    r"create|creates|created|output|outputs|generate|generates|generated|"
    r"implement|implements|implemented|download|downloads|downloaded|"
    r"clone|clones|cloned|place|places|placed)\b",
    re.IGNORECASE,
)
_ABS_RE = re.compile(r"/app(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*/?")
_REL_RE = re.compile(r"[`'\"]([A-Za-z0-9_][A-Za-z0-9_.-]*\.[A-Za-z0-9_]+)[`'\"]")
_PROVIDED_RE = re.compile(r"\b(provided|given)\s+.{0,40}?$", re.IGNORECASE)

_MAX_CONTINUES = 2


def _sentences(question: str) -> list[str]:
    """Split into sentence-ish chunks without breaking common abbreviations."""
    out: list[str] = []
    for line in re.split(r"\n+", question):
        line = line.strip()
        if not line:
            continue
        # Split at ". " only when the next token starts a new sentence with an
        # uppercase letter. This keeps "e.g. /app/answer.txt" together.
        for part in re.split(r"(?<=\.)\s+(?=[A-Z])", line):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _clean_path(value: str) -> str:
    return value.strip().strip("`'\"").rstrip(".,;:")


def _is_provided_input(sentence: str, path: str) -> bool:
    """True when a path appears after 'provided'/'given' in the same clause."""
    for m in re.finditer(re.escape(path), sentence):
        prefix = sentence[: m.start()]
        if _PROVIDED_RE.search(prefix):
            return True
    return False


def _resolve(path: str, ctx) -> Path:
    if path.startswith("/"):
        return Path(path)
    return ctx.working_dir / path


def _required_groups(question: str, ctx):
    """Return a list of required-path groups inferred from the question."""
    groups: list[dict] = []
    for sentence in _sentences(question):
        if not _CUE_RE.search(sentence):
            continue

        raw_paths: list[str] = []
        for m in _ABS_RE.finditer(sentence):
            p = _clean_path(m.group(0))
            if p.startswith("/app"):
                raw_paths.append(p)
        for m in _REL_RE.finditer(sentence):
            raw_paths.append(_clean_path(m.group(1)))

        # Keep order, drop duplicates, drop explicitly-provided inputs.
        seen: set[str] = set()
        paths: list[str] = []
        for p in raw_paths:
            if p in seen:
                continue
            seen.add(p)
            if _is_provided_input(sentence, p):
                continue
            paths.append(p)

        if not paths:
            continue

        labels = [str(_resolve(p, ctx)) for p in paths]
        any_of = False
        if len(paths) > 1:
            first = sentence.find(paths[0])
            last = sentence.rfind(paths[-1])
            span = sentence[first : last + len(paths[-1])]
            any_of = bool(re.search(r"\bor\b", span, re.IGNORECASE))
        groups.append(
            {
                "paths": paths,
                "labels": labels,
                "any_of": any_of,
            }
        )
    return groups


async def before_final(answer, ctx):
    state = ctx.state.setdefault("artifact_gate", {})
    groups = state.get("groups")
    if groups is None:
        groups = _required_groups(ctx.question, ctx)
        state["groups"] = groups

    if not groups:
        return None

    missing: list[str] = []
    for group in groups:
        exists = [_resolve(p, ctx).exists() for p in group["paths"]]
        satisfied = any(exists) if group["any_of"] else all(exists)
        if not satisfied:
            if group["any_of"]:
                missing.append("(" + " or ".join(group["labels"]) + ")")
            else:
                missing.extend(group["labels"])

    if not missing:
        return None

    continues = state.get("continues", 0)
    if continues >= _MAX_CONTINUES:
        ctx.trace.event(
            "artifact_gate_accept",
            reason="continue_budget_exhausted",
            missing=missing,
        )
        return None

    state["continues"] = continues + 1
    ctx.trace.event(
        "artifact_gate_continue",
        count=continues + 1,
        missing=missing,
    )
    feedback = (
        "Before you finish, the task still requires these deliverables to exist: "
        + ", ".join(missing)
        + ". Use the available tools to create or write them at the exact required "
        "paths, verify each one exists and matches the requested format, then stop. "
        "Do not end the run while any required deliverable is still missing."
    )
    return {"action": "continue", "feedback": feedback}
