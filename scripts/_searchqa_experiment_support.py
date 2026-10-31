"""Paper metric and equal initial skills for the two-harness SearchQA experiment.

The answer extraction, normalization, exact match and F1 below follow
``microsoft/SkillOpt`` at 79124b37e9a6371e13b753f8bcd7adb1e493ade1:
https://github.com/microsoft/SkillOpt/blob/79124b37e9a6371e13b753f8bcd7adb1e493ade1/skillopt/envs/searchqa/evaluator.py
``rollout.py`` maps its ``em`` to ``hard`` and its ``f1`` to ``soft``.
The initial skill comes from ``skillopt/envs/searchqa/skills/initial.md``.
These experiment helpers do not change the Lite benchmark's prompt or metrics.

Upstream portions are licensed under the MIT License:
Copyright (c) 2026 Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import re
import shutil
import string
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import flashrsi.agents
from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.core import Trajectory

UPSTREAM_REVISION = "79124b37e9a6371e13b753f8bcd7adb1e493ade1"
INITIAL_SKILL = (
    "# Question Answering Skill\n\n"
    "(No learned rules yet. Rules will be added through the reflection process.)\n"
)


def _normalize_answer(s: str) -> str:
    """The upstream SQuAD normalization, including ASCII-only punctuation."""
    s = s.lower()
    s = "".join(ch for ch in s if ch not in string.punctuation)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = " ".join(s.split())
    return s.strip()


def _extract_answer(text: str) -> str:
    """Use the last answer tag, then the last nonempty line, as upstream does."""
    matches = re.findall(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        return lines[-1]
    return text.strip()


def _exact_match(prediction: str, gold_answers: Sequence[str]) -> float:
    norm_pred = _normalize_answer(prediction)
    for gold in gold_answers:
        if _normalize_answer(gold) == norm_pred:
            return 1.0
    return 0.0


def _f1_score(prediction: str, gold_answers: Sequence[str]) -> float:
    """The upstream token F1, taking the maximum across all references."""
    norm_pred = _normalize_answer(prediction)
    pred_tokens = norm_pred.split()

    if not pred_tokens:
        for gold in gold_answers:
            if not _normalize_answer(gold).split():
                return 1.0
        return 0.0

    best_f1 = 0.0
    for gold in gold_answers:
        gold_tokens = _normalize_answer(gold).split()
        if not gold_tokens:
            continue
        common = Counter(pred_tokens) & Counter(gold_tokens)
        n_common = sum(common.values())
        if n_common == 0:
            continue
        precision = n_common / len(pred_tokens)
        recall = n_common / len(gold_tokens)
        f1 = 2 * precision * recall / (precision + recall)
        best_f1 = max(best_f1, f1)

    return best_f1


def official_metrics(prediction: str, gold_answers: Sequence[str]) -> dict[str, float]:
    """Return SkillOpt's hard/EM and F1 after its official answer extraction."""
    answer = _extract_answer(prediction)
    return {
        "hard": _exact_match(answer, gold_answers),
        "f1": _f1_score(answer, gold_answers),
    }


class ExperimentSearchQA(SearchQA):
    """Select by official hard score while retaining Lite metrics for diagnosis."""

    primary_metric = "hard"

    def grade(self, trajs: tuple[Trajectory, ...]) -> tuple[Trajectory, ...]:
        # Reuse Lite's task validation and canonical references. This also keeps
        # failed trajectories at zero for the two original diagnostic metrics.
        graded = super().grade(trajs)
        results = []
        for trajectory in graded:
            task = self._tasks_by_id[trajectory.task.task_id]
            scores = (
                official_metrics(trajectory.output, task.metadata["answers"])
                if trajectory.status == "finished"
                else {"hard": 0.0, "f1": 0.0}
            )
            results.append(
                replace(
                    trajectory,
                    metrics={
                        **trajectory.metrics,
                        "lite_f1": trajectory.metrics["f1"],
                        **scores,
                    },
                )
            )
        return tuple(results)


def create_seed(harness: str, destination: Path) -> Path:
    """Copy a bundled harness and install the shared official empty skill.

    The caller owns the new directory and passes it as ``agent.source_dir``.
    Existing destinations are never replaced. Neither bundled system prompts
    nor the Claude native system-prompt selection are changed.
    """
    if harness not in {"miniagent", "claude_code"}:
        raise ValueError(f"Unsupported experiment harness: {harness}")
    source = Path(flashrsi.agents.__file__).parent / harness
    destination = Path(destination).expanduser().absolute()
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if harness == "miniagent":
        (destination / "skills" / "main.md").write_text(INITIAL_SKILL, encoding="utf-8")
    else:
        skill_dir = destination / "skills" / "searchqa"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: searchqa\n"
            "description: Use for every supplied-context question-answering task "
            "in this SearchQA experiment.\n"
            "---\n\n" + INITIAL_SKILL,
            encoding="utf-8",
        )
        (destination / "CLAUDE.md").write_text(
            "Before answering each question, invoke the Skill tool with skill "
            '"flashrsi:searchqa" and follow that skill. Then answer the question '
            "in the requested format.\n",
            encoding="utf-8",
        )
    return destination
