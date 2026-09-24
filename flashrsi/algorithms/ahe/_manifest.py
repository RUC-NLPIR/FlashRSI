"""AHE's own contract: what the Evolve Agent declared, and whether it held.

The paper's contribution is not "let a coding agent edit the harness" -- it is
making that edit *falsifiable*. Before anything is measured the agent must say
which tasks each file it touched will fix, and which it might break. Those
declarations are :class:`Change`; the check against what actually happened is
:func:`attribute` and :func:`evaluate`.

Upstream: https://github.com/china-qijizhifeng/agentic-harness-engineering
Commit: 8b2a55d97590363fe50c3cc6b5e833b020a4bb4c
Port reference: FlashRSI 5efe9b438483710060183c6c3ecbc5062b410a58.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class ManifestError(ValueError):
    """The declaration is missing, malformed, or does not match the diff."""


@dataclass(frozen=True, slots=True)
class Change:
    """One edited file and the outcome the agent predicted for it."""

    path: str
    fixes: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Manifest:
    """Why the agent edited, what it edited, and what it expects to happen.

    Only ``changes`` is graded. The three prose fields are required anyway,
    and their reader is the *next* Evolve Agent: ``as_record`` puts them in the
    verdict it is shown, so a round can see the reasoning it is now judging.
    """

    evidence: tuple[str, ...]
    root_cause: str
    targeted_fix: str
    changes: tuple[Change, ...] = ()

    @classmethod
    def parse(cls, reply: str, changed: Sequence[str]) -> Manifest:
        """Read the declaration and hold it to the diff it claims to describe.

        The paths must match exactly. An agent that edited a file it did not
        declare has made an unfalsifiable change -- nothing predicts what that
        file was for, so nothing can later find it wanting.
        """
        try:
            value = json.loads(reply)
        except json.JSONDecodeError as error:
            raise ManifestError(f"manifest is not valid JSON: {error}") from None
        if not isinstance(value, Mapping):
            raise ManifestError("manifest must be a JSON object")
        evidence = value.get("failure_evidence")
        if not isinstance(evidence, list) or not all(
            isinstance(item, str) and item.strip() for item in evidence
        ):
            raise ManifestError("failure_evidence must be a list of strings")
        text = {}
        for name in ("root_cause", "targeted_fix"):
            if not isinstance(value.get(name), str) or not value[name].strip():
                raise ManifestError(f"{name} must be a non-empty string")
            text[name] = value[name].strip()

        overall = _impact(value.get("predicted_impact", {}), "predicted_impact")
        raw = value.get("changes", [])
        if not isinstance(raw, list):
            raise ManifestError("changes must be a list")
        changes = []
        for item in raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
                raise ManifestError("each change requires a string path")
            changes.append(Change(item["path"], *_impact(item, item["path"], overall)))
        # A whole-diff prediction is still a prediction: apply it per file.
        if not changes:
            changes = [Change(path, *overall) for path in changed]
        declared = tuple(sorted(change.path for change in changes))
        if declared != tuple(sorted(changed)):
            raise ManifestError(
                f"manifest declares {list(declared)} but the edit changed "
                f"{sorted(changed)}"
            )
        return cls(tuple(evidence), changes=tuple(changes), **text)

    def as_record(self) -> dict:
        """The declaration as it is recorded and shown to the next agent."""
        return {
            "failure_evidence": list(self.evidence),
            "root_cause": self.root_cause,
            "targeted_fix": self.targeted_fix,
            "changes": [
                {
                    "path": change.path,
                    "predicted_fix_tasks": list(change.fixes),
                    "risk_tasks": list(change.risks),
                }
                for change in self.changes
            ],
        }


def _impact(
    value: Mapping,
    name: str,
    default: tuple[tuple[str, ...], tuple[str, ...]] = ((), ()),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read one ``(fix_tasks, risk_tasks)`` prediction, overall or per file."""
    if not isinstance(value, Mapping):
        raise ManifestError(f"{name} must be an object")
    result = []
    for key, fallback in (("fix_tasks", default[0]), ("risk_tasks", default[1])):
        # A per-file entry names its own keys; the overall block nests them.
        raw = value.get(key, value.get(f"predicted_{key}"))
        if raw is None:
            result.append(fallback)
            continue
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ManifestError(f"{name}.{key} must be a list of strings")
        result.append(tuple(raw))
    return result[0], result[1]


def attribute(
    before: Mapping[str, float], after: Mapping[str, float]
) -> dict[str, dict]:
    """Per-task movement between two rollouts of the same tasks.

    ``flip`` is the categorical form the verdicts below are written in: a task
    the edit fixed, one it broke, or one it left alone.
    """
    result = {}
    for task_id in sorted(set(before) | set(after)):
        first, second = before.get(task_id, 0.0), after.get(task_id, 0.0)
        result[task_id] = {
            "before": first,
            "after": second,
            "delta": second - first,
            "flip": "fail_to_pass"
            if first <= 0 < second
            else "pass_to_fail"
            if first > 0 >= second
            else "unchanged",
        }
    return result


def evaluate(manifest: Manifest, attribution: Mapping[str, Mapping]) -> dict:
    """Grade every declared change against what the rollout actually did.

    This report is what the next Evolve Agent reads: the published mode does
    not gate on score, it hands the previous round's verdicts back and lets the
    agent decide whether to keep, improve, or roll each one back.
    """
    flipped = _flipped(attribution, "fail_to_pass")
    regressed = _flipped(attribution, "pass_to_fail")
    declared: set[str] = set()
    changes = []
    for change in manifest.changes:
        predicted, risks = set(change.fixes), set(change.risks)
        declared |= predicted | risks
        fixed = predicted & flipped
        realized = risks & regressed
        if realized and not fixed:
            verdict = "HARMFUL"
        elif realized:
            verdict = "MIXED"
        elif predicted and fixed == predicted:
            verdict = "EFFECTIVE"
        elif fixed:
            verdict = "PARTIALLY_EFFECTIVE"
        else:
            verdict = "INEFFECTIVE"
        changes.append(
            {
                "path": change.path,
                "predicted_fixes": sorted(predicted),
                "actually_fixed": sorted(fixed),
                "still_failed": sorted(predicted - flipped),
                "predicted_risks": sorted(risks),
                "risk_realized": sorted(realized),
                "verdict": verdict,
            }
        )
    return {
        "tasks": dict(attribution),
        "changes": changes,
        # A regression nobody predicted is the signal that the manifest missed
        # something, so it is reported on its own rather than folded into the
        # verdict of a change that never claimed to affect that task.
        "unattributed_regressions": sorted(regressed - declared),
    }


def _flipped(attribution: Mapping[str, Mapping], flip: str) -> set[str]:
    return {task_id for task_id, row in attribution.items() if row.get("flip") == flip}


__all__ = [
    "Change",
    "Manifest",
    "ManifestError",
    "attribute",
    "evaluate",
]
