"""RRSI on the framework's Worker, Benchmark and Snapshot.

Independent mechanism port reviewed against google-research/rrsi at
be50316e1db05914068a973f322770ef08ed7ba1; see docs/rrsi.md.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
from collections.abc import Mapping
from contextlib import ExitStack
from difflib import unified_diff
from pathlib import Path
from statistics import mean, pstdev, stdev
from tempfile import TemporaryDirectory

from flashrsi.algorithms import _replies
from flashrsi.algorithms.rrsi import _prompts as prompts
from flashrsi.core import Algorithm, Snapshot
from flashrsi.core.snapshot import discard_runtime_files

_COMPONENTS = frozenset(
    {
        "prompt",
        "control_flow",
        "config",
        "output_plumbing",
        "context_mgmt",
        "client_tool",
        "skill",
        "memory",
        "subagent",
    }
)

_GENERIC_SIGNALS = {
    "memory": [r"\bMemory\(", r"\.remember\(", r"\.recall\(", r"_STATE_DIR"],
    "skill": [
        r"skills/",
        r"SkillRegistry",
        r"skill_use",
        r"skill_catalog",
        r"upload_skills",
    ],
    "client_tool": [r"ToolRegistry", r"register_tool", r"tool_spec", r"CLIENT_TOOLS"],
    "subagent": [r"\bsubcall\(", r"sub_agent", r"subagent"],
}

_CREDENTIAL_PATTERN = (
    r"AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9]{20,}|api_key\s*=\s*[\"'][^\"']{8,}"
)

_STRUCTURAL = {"client_tool", "skill", "memory", "subagent"}

_ANALYSIS_MAX_TURNS = 30
_DIGEST_MAX_CHARS = 6000
_PROTOCOL_RETRIES = 3


class _InvalidMeasurement(ValueError):
    """A completed evaluation cannot support RRSI's score/cost comparison."""


class RRSI(Algorithm):
    """Anneal edit budgets and explore stalled components from trajectory evidence.

    Keep candidates under a historical score floor and token-cost rule.
    """

    name = "rrsi"
    description = (
        "Regularized harness evolution with history, critic and cost selection."
    )
    evolve_scope = {"*"}
    _defaults = {
        "T": 20,
        "k": 2,
        "m": 2,
        "b_min": 1,
        "b_max": 4,
        "w": 3,
        "m_draft": 1,
        "delta": None,
        "delta_z": 2.0,
        "beta0": 0.10,
        "beta1": 40.0,
        "w_s": 100.0,
        "w_c": 15.0,
        "w_n": 0.5,
        "n_prune": 4,
        "repair_rounds": 5,
        "invalid_missing_frac": 0.15,
        "seed": 7,
        "n_fail_traces": 22,
        "n_success_traces": 6,
        "calibration_evals": 1,
        "smoke_n": 2,
        "component_signals": {},
        "weight_metric": None,
        "guards": {},
    }
    _ranges = {
        "T": (int, 1),
        "k": (int, 1),
        "m": (int, 1),
        "b_min": (int, 1),
        "b_max": (int, 1),
        "w": (int, 1),
        "m_draft": (int, 0),
        "delta": (float | None, 0),
        "delta_z": (float, 0),
        "beta0": (float, 0),
        "beta1": (float, 0),
        "w_s": (float, 0),
        "w_c": (float, 0),
        "w_n": (float, 0),
        "n_prune": (int, 1),
        "repair_rounds": (int, 0),
        "invalid_missing_frac": (float, 0),
        "seed": int,
        "n_fail_traces": (int, 0),
        "n_success_traces": (int, 0),
        "calibration_evals": (int, 1),
        "smoke_n": (int, 0),
    }

    async def evolve(self) -> Snapshot:
        with ExitStack() as resources:
            resources.callback(setattr, self, "_run_dir", self._run_dir)
            if self._run_dir is None:
                self._run_dir = Path(resources.enter_context(TemporaryDirectory()))
                for name in ("snapshots", "trajectories", "working"):
                    (self._run_dir / name).mkdir()

            current = seed = self.target.snapshot
            incumbent = await self._measure(current, "baseline")
            delta = self.config.delta
            if delta is None:
                evaluations = [incumbent]
                for _ in range(self.config.calibration_evals - 1):
                    evaluations.append(await self._measure(current, "calibration-eval"))
                calibration = _calibrate(
                    evaluations, self.config.delta_z, self.config.seed
                )
                delta = calibration["delta"]
            else:
                calibration = {"delta": delta, "source": "configured", "n_evals": 0}
            self._record("calibration", calibration)
            best_score = incumbent["score"]
            scores, history = [best_score], []
            analysis = {"failure_modes": [], "success_habits": []}

            for step in range(self.config.T):
                traces = _select_traces(
                    incumbent, self.config.n_fail_traces, self.config.n_success_traces
                )
                analysis = await self._analyze(
                    current.id,
                    traces,
                    {key: analysis[key] for key in ("failure_modes", "success_habits")},
                )
                context = {
                    "step": step,
                    "incumbent_id": current.id,
                    "score": incumbent["score"],
                    "cost": incumbent["cost"],
                    "best_score": best_score,
                    "delta": delta,
                    "budget": _edit_budget(step, self.config),
                    "analysis": analysis,
                    "traces": {
                        task: trace["evidence"] for task, trace in traces.items()
                    },
                    "history": history,
                    **_directives(history, scores, step, delta, self.config),
                }
                self._record("rrsi-context", context)
                # Every sibling reads this fixed, framework-redacted record.
                evidence = max(
                    (self._run_dir / "trajectories").glob("*-rrsi-context.json")
                )
                proposals = [
                    await self._propose(current, variant, context, evidence)
                    for variant in range(self.config.m)
                ]
                current, incumbent = await self._select(
                    current, incumbent, proposals, context, history
                )
                best_score = max(best_score, incumbent["score"])
                scores.append(incumbent["score"])

            return self._promote(
                seed,
                current,
                score=incumbent["score"],
                cost=incumbent["cost"],
                best_score=best_score,
                delta=delta,
            )

    async def _select(self, parent, incumbent, proposals, context, history):
        accepted = {row["component"] for row in history if row["accepted"]}
        start = len(history)
        winner, winning_measurement = None, None
        winning_variant = None
        for variant, (snapshot, edits, changes, reason) in enumerate(proposals):
            decision = {
                "admissible": False,
                "reason": reason,
                "delta_S": None,
                "delta_C": None,
            }
            feedback = []
            if snapshot is not None:
                try:
                    measurement = await self._measure(snapshot, "candidate")
                except _InvalidMeasurement as error:
                    decision["reason"] = str(error)
                else:
                    decision = _judge(
                        measurement,
                        incumbent,
                        context["best_score"],
                        context["delta"],
                        edits,
                        accepted,
                        self.config,
                    )
                    feedback = _attribution(
                        edits, incumbent, measurement, 1 / self.config.k
                    )
                    if decision["admissible"] and (
                        winner is None
                        or measurement["score"] > winning_measurement["score"]
                    ):
                        winner, winning_measurement = snapshot, measurement
                        winning_variant = variant
            for index, edit in enumerate(edits or [{"component": None, "paths": []}]):
                history.append(
                    {
                        **edit,
                        "t": context["step"],
                        "variant": variant,
                        "parent_id": parent.id,
                        "candidate_id": snapshot.id if snapshot is not None else None,
                        "diff": changes,
                        "attribution": feedback[index] if feedback else None,
                        **decision,
                    }
                )
        for row in history[start:]:
            selected = row["variant"] == winning_variant
            row.update(
                accepted=selected,
                outcome="ACCEPTED"
                if selected
                else "LOST"
                if row["admissible"]
                else "REJECTED",
            )
            self._record("edit-history", row)

        return (parent, incumbent) if winner is None else (winner, winning_measurement)

    async def _measure(self, snapshot, label):
        trials = []
        for trial in range(self.config.k):
            results = await self._evaluate(snapshot, self.benchmark.train, label=label)
            scores = results.per_task
            for trajectory in results:
                score = scores[trajectory.task.task_id]
                if not 0 <= score <= 1:
                    raise ValueError("RRSI requires primary scores in [0, 1]")
                trials.append(
                    {
                        "task_id": trajectory.task.task_id,
                        "trial": trial,
                        "reward": score,
                        "weight": trajectory.metrics.get(self.config.weight_metric)
                        if self.config.weight_metric
                        else 1.0,
                        "tokens": _tokens(trajectory.usage),
                        "trajectory": self._trajectory_evidence(trajectory),
                    }
                )
        per_task, weights = {}, {}
        for row in trials:
            task = row["task_id"]
            if row["trajectory"]["status"] == "error":
                row["reward"] = 0.0
            per_task.setdefault(task, []).append(row["reward"])
            weights.setdefault(task, []).append(row["weight"])
        score = _weighted_score(
            [row["reward"] for row in trials], [row["weight"] for row in trials]
        )
        guards = {}
        for metric in self.config.guards:
            values = [row["trajectory"]["metrics"].get(metric) for row in trials]
            if None in values:
                raise _InvalidMeasurement(f"missing guard metric: {metric}")
            guards[metric] = mean(values)
        costs = [row["tokens"] for row in trials]
        cost = mean(costs) if None not in costs else None
        if cost is None or cost <= 0:
            raise _InvalidMeasurement(
                "complete positive policy-token accounting is required for every trial"
            )
        errors = sum(row["trajectory"]["status"] == "error" for row in trials)
        if errors > self.config.invalid_missing_frac * len(trials):
            raise _InvalidMeasurement("too many failed trials")
        measurement = {
            "score": score,
            "cost": cost,
            "per_task": per_task,
            "weights": weights,
            "guard_metrics": guards,
            "evidence": trials,
        }
        self._record("measurement", {"snapshot_id": snapshot.id, **measurement})
        # Framework recording owns redaction, including full file evidence.
        record = max((self._run_dir / "trajectories").glob("*-measurement.json"))
        measurement["evidence"] = json.loads(record.read_text())["evidence"]
        return measurement

    async def _analyze(self, snapshot_id, traces, prior):
        table = [
            {key: value for key, value in trace.items() if key != "evidence"}
            for trace in traces.values()
        ]
        interaction, digests = [], []
        for _ in range(_ANALYSIS_MAX_TURNS):
            raw = await self.worker.ask(
                prompts.ANALYZE.format(
                    incumbent=snapshot_id,
                    tasks=json.dumps(table),
                    prior=json.dumps(prior),
                    interaction=json.dumps(interaction),
                )
            )
            try:
                action = json.loads(_replies.tagged(raw, "ANALYSIS"))
                if not isinstance(action, dict):
                    raise ValueError("return one JSON action object")
                if action.get("action") == "report":
                    if not digests:
                        raise ValueError(
                            "investigate at least one trace before reporting"
                        )
                    report = {
                        key: action.get(key) or []
                        for key in (
                            "failure_modes",
                            "capability_gaps",
                            "success_habits",
                        )
                    }
                    if not all(
                        isinstance(rows, list)
                        and all(isinstance(row, dict) for row in rows)
                        for rows in report.values()
                    ):
                        raise ValueError("report sections must be lists of objects")
                    report["failure_modes"].sort(
                        key=lambda row: -(row.get("n_tasks") or 0)
                    )
                    return {**report, "digests": digests}
                if action.get("action") != "digest_many" or not isinstance(
                    action.get("requests"), list
                ):
                    raise ValueError("request digest_many or return report")
                requests = [
                    request
                    for request in action["requests"][:8]
                    if isinstance(request, dict) and request.get("task_id") in traces
                ]
                if not requests:
                    raise ValueError("request at least one task from the task table")
            except (ValueError, TypeError) as error:
                interaction.append({"reply": raw, "error": str(error)})
                continue
            results = [
                await self._digest(
                    traces[request["task_id"]],
                    request.get("lens", "failure"),
                    request.get("questions", []),
                )
                for request in requests
            ]
            digests.extend(results)
            interaction.append({"action": action, "results": results})
        raise ValueError("RRSI analyst exhausted its 30 turns without a report")

    async def _digest(self, trace, lens, questions):
        """Keep trace investigation outside every target checkout."""
        if not isinstance(lens, str) or lens not in prompts.DIGEST_SCHEMAS:
            lens = "failure"
        evidence = trace["evidence"]
        original = json.dumps(evidence, ensure_ascii=False).encode()
        objection = ""
        for _ in range(_PROTOCOL_RETRIES):
            with TemporaryDirectory(
                prefix="rrsi-digest-", dir=self._run_dir / "working"
            ) as temporary:
                directory = Path(temporary)
                path = directory / "trace.json"
                path.write_bytes(original)
                raw = await self.worker.edit(
                    directory,
                    prompts.DIGEST.format(
                        evidence="trace.json",
                        task_id=trace["task_id"],
                        lens=lens,
                        questions=json.dumps(questions),
                        max_chars=_DIGEST_MAX_CHARS,
                        schema=prompts.DIGEST_SCHEMAS[lens],
                        objection=objection,
                    ),
                )
                try:
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or path.read_bytes() != original
                    ):
                        raise ValueError("digester changed its read-only trace")
                    value = _replies.tagged(raw, "DIGEST")
                    if len(value) > _DIGEST_MAX_CHARS:
                        raise ValueError("digest exceeds 6000 characters")
                    result = json.loads(value)
                    if (
                        not isinstance(result, dict)
                        or result.get("task_id") != trace["task_id"]
                        or result.get("lens") != lens
                    ):
                        raise ValueError(
                            "digest must identify the requested task and lens"
                        )
                    quotes = result.get("evidence", [])
                    if not isinstance(quotes, list) or any(
                        not isinstance(row, dict)
                        or not isinstance(row.get("quote"), str)
                        or not row["quote"]
                        or not _quote_in_trace(row["quote"], evidence)
                        for row in quotes
                    ):
                        raise ValueError(
                            "digest quotes must occur in the supplied trace"
                        )
                    return result
                except ValueError as error:
                    objection = str(error)
        raise ValueError(f"RRSI digest invalid: {objection}")

    async def _propose(self, parent, variant, context, evidence_file):
        step, budget = context["step"], context["budget"]
        reserved = (
            context["untried"]
            if context["stalled"] and variant >= self.config.m - self.config.m_draft
            else []
        )
        edits, changes, objection = [], "", ""
        with parent.check_out(working_dir=self._run_dir / "working") as directory:
            for attempt in range(self.config.repair_rounds + 1):
                with TemporaryDirectory(
                    prefix="rrsi-evidence-", dir=directory
                ) as temporary:
                    reference = Path(temporary) / "context.json"
                    shutil.copy2(evidence_file, reference)
                    reply = await self.worker.edit(
                        directory,
                        prompts.PROPOSE.format(
                            step=step,
                            variant=variant,
                            evidence=reference.relative_to(directory).as_posix(),
                            budget=budget,
                            components=json.dumps(sorted(_COMPONENTS)),
                            permissions=json.dumps(dict(parent.component_rules)),
                            reserved=json.dumps(reserved),
                            objection=objection,
                        ),
                    )
                discard_runtime_files(directory)
                edits, changes = [], ""
                try:
                    snapshot = self._commit(parent, directory)
                    changed = parent.changed_paths(snapshot)
                    if not changed:
                        raise ValueError("the harness was left unchanged")
                    changes = _diff(parent, snapshot)
                    edits = _parse_edits(reply, changed, budget)
                    if re.search(_CREDENTIAL_PATTERN, changes):
                        raise ValueError("credential pattern matched the diff")
                except ValueError as error:
                    objection = str(error)
                else:
                    review = await self._review(
                        prompts.CRITIC.format(edits=json.dumps(edits), diff=changes)
                    )
                    self._record(
                        "critic", {"step": step, "variant": variant, "review": review}
                    )
                    objection = (
                        json.dumps(review) if review["verdict"] == "reject" else ""
                    )
                    if not objection:
                        for edit in edits:
                            tag = _normalize_component(
                                edit["component"],
                                _diff(parent, snapshot, edit["paths"]),
                                self.config.component_signals,
                            )
                            if tag != edit["component"]:
                                edit["declared_component"], edit["component"] = (
                                    edit["component"],
                                    tag,
                                )
                        if reserved and not any(
                            edit["component"] in reserved for edit in edits
                        ):
                            objection = f"reserved slot must exercise one of {reserved}, judged by the diff"
                    if not objection:
                        failure = await self._smoke(snapshot, context["traces"])
                        return (None if failure else snapshot), edits, changes, failure
                self._record(
                    "repair",
                    {
                        "step": step,
                        "variant": variant,
                        "attempt": attempt,
                        "objection": objection,
                        "diff": changes,
                    },
                )
        return None, edits, changes, objection

    async def _review(self, payload):
        for _ in range(_PROTOCOL_RETRIES):
            raw = await self.worker.ask(payload)
            try:
                review = json.loads(_replies.tagged(raw, "REVIEW"))
                if isinstance(review, dict) and review.get("verdict") in (
                    "accept",
                    "reject",
                ):
                    return review
            except ValueError:
                pass
        return {
            "verdict": "reject",
            "reasons": ["critic output unparseable after 3 attempts"],
        }

    async def _smoke(self, snapshot, traces):
        try:
            for path, entry in snapshot.files.items():
                if path.endswith(".py"):
                    compile(entry.content, path, "exec")
        except SyntaxError as error:
            self._record(
                "smoke-gate",
                {
                    "snapshot_id": snapshot.id,
                    "passed": False,
                    "stage": "compile",
                    "error": str(error),
                },
            )
            return "smoke compile failed: " + str(error)
        tasks = [task for task in self.benchmark.train if task.task_id in traces][
            : self.config.smoke_n
        ]
        smoke = await self._evaluate(snapshot, tasks, label="smoke") if tasks else ()
        failure = "smoke failed" if any(row.status == "error" for row in smoke) else ""
        self._record(
            "smoke-gate",
            {
                "snapshot_id": snapshot.id,
                "passed": not failure,
                "stage": "rollout" if tasks else "compile",
                "task_ids": [task.task_id for task in tasks],
            },
        )
        return failure

    def _check(self):
        config = self.config
        unknown = set(config) - self._defaults.keys() - {"name", "worker"}
        if unknown:
            raise ValueError(f"unknown RRSI options: {', '.join(sorted(unknown))}")
        if not self.benchmark.train:
            raise ValueError("RRSI requires a non-empty train split")
        ids = [task.task_id for task in self.benchmark.train]
        if len(set(ids)) != len(ids):
            raise ValueError("RRSI requires unique train task_id values")
        if (
            self.target is self.worker
            or self.worker.config.get("type", "agent") != "agent"
        ):
            raise ValueError("RRSI requires a separate file-editing Agent Worker")
        if config.b_min > config.b_max:
            raise ValueError("RRSI b_min must not exceed b_max")
        if config.m_draft > config.m:
            raise ValueError("RRSI m_draft must not exceed m")
        if config.delta is None and config.k < 2 and config.calibration_evals < 2:
            raise ValueError("RRSI automatic noise calibration requires k >= 2")
        if config.invalid_missing_frac > 1:
            raise ValueError("RRSI invalid_missing_frac must be in [0, 1]")
        if config.n_fail_traces + config.n_success_traces == 0:
            raise ValueError("RRSI analysis requires at least one representative trace")
        if (
            not isinstance(config.component_signals, Mapping)
            or set(config.component_signals) - _COMPONENTS
        ):
            raise ValueError(
                "component_signals must map semantic component names to regex lists"
            )
        for patterns in config.component_signals.values():
            if (
                not isinstance(patterns, list)
                or not patterns
                or not all(isinstance(pattern, str) for pattern in patterns)
            ):
                raise ValueError(
                    "component_signals values must be non-empty regex lists"
                )
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"invalid component signal: {error}") from None
        if config.weight_metric is not None and (
            not isinstance(config.weight_metric, str) or not config.weight_metric
        ):
            raise ValueError("weight_metric must be a metric name or null")
        if not isinstance(config.guards, Mapping):
            raise ValueError("guards must map metric names to max_drop/max_rise limits")
        for metric, limits in config.guards.items():
            if (
                not isinstance(metric, str)
                or not metric
                or not isinstance(limits, Mapping)
                or not limits
                or set(limits) - {"max_drop", "max_rise"}
            ):
                raise ValueError("invalid guard metric or limits")
            if any(
                type(limit) not in (int, float) or not math.isfinite(limit) or limit < 0
                for limit in limits.values()
            ):
                raise ValueError("guard limits must be finite nonnegative numbers")


def _edit_budget(t, config):
    value = (
        config.b_min
        + (config.b_max - config.b_min) * (1 + math.cos(math.pi * t / config.T)) / 2
    )
    return math.ceil(round(value, 9))


def _directives(history, scores, t, delta, config):
    measured = [row for row in history if row["delta_S"] is not None]
    tried = {row["component"] for row in measured}
    untried = sorted(_COMPONENTS - tried)
    stalled = t >= config.w and scores[t] - scores[t - config.w] <= delta
    prune = []
    for component in sorted(tried):
        recent = [
            row["delta_S"]
            for row in measured
            if row["component"] == component and t - row["t"] <= config.n_prune
        ]
        if not recent or max(recent) <= 0:
            prune.append(
                {
                    "component": component,
                    "recent_best_gain": max(recent) if recent else None,
                    "accepted_edits": [
                        row
                        for row in history
                        if row["component"] == component and row["accepted"]
                    ],
                }
            )
    return {"stalled": stalled, "untried": untried, "prune": prune}


def _noise_band(trials, z, seed, weights=None):
    """Bootstrap trials within each task, preserving the evolve-set weights."""
    rng = random.Random(seed)
    weights = weights or {task: [1.0] * len(values) for task, values in trials.items()}
    samples = []
    for _ in range(2000):
        numerator = denominator = 0.0
        for task, values in trials.items():
            for _ in values:
                index = rng.randrange(len(values))
                weight = weights[task][index]
                numerator += values[index] * weight
                denominator += weight
        samples.append(numerator / denominator)
    return round(z * math.sqrt(2) * pstdev(samples), 6)


def _calibrate(evaluations, z, seed):
    """Repeated baselines, falling back to the upstream pooled trial bootstrap."""
    scores = [evaluation["score"] for evaluation in evaluations]
    sd = stdev(scores) * math.sqrt(2) if len(scores) > 1 else 0.0
    if sd > 0:
        delta = round(z * sd, 6)
        source = "repeated base evaluations"
    else:
        trials = {task: [] for task in evaluations[0]["per_task"]}
        weights = {task: [] for task in trials}
        for evaluation in evaluations:
            for task in trials:
                trials[task].extend(evaluation["per_task"][task])
                weights[task].extend(evaluation["weights"][task])
        # Pooling increases k; rescale its SE to the original evaluation size.
        delta = _noise_band(trials, z * math.sqrt(len(evaluations)), seed, weights)
        source = "bootstrap within-task baseline trials"
    return {"delta": delta, "source": source, "n_evals": len(evaluations)}


def _judge(measurement, incumbent, best_score, delta, edits, accepted, config):
    ds = measurement["score"] - incumbent["score"]
    dc = (measurement["cost"] - incumbent["cost"]) / incumbent["cost"]
    novelty = len({edit["component"] for edit in edits} & _STRUCTURAL - accepted)
    if measurement["score"] < best_score - delta:
        admissible, reason = False, "below historical best minus noise band"
    elif ds > delta:
        admissible = dc <= config.beta0 + config.beta1 * ds
        reason = "gain/cost budget"
    else:
        admissible = config.w_s * ds - config.w_c * dc + config.w_n * novelty > 0
        reason = "within-band score/cost/novelty rule"
    violations = []
    for metric, limits in config.get("guards", {}).items():
        change = (
            measurement["guard_metrics"][metric] - incumbent["guard_metrics"][metric]
        )
        if "max_drop" in limits and -change > limits["max_drop"]:
            violations.append(f"{metric} fell {-change:.6f}")
        if "max_rise" in limits and change > limits["max_rise"]:
            violations.append(f"{metric} rose {change:.6f}")
    if admissible and violations:
        admissible, reason = False, "domain guard violated: " + "; ".join(violations)
    return {
        "admissible": admissible,
        "reason": reason,
        "delta_S": ds,
        "delta_C": dc,
        "novelty": novelty,
        "guards": violations,
    }


def _attribution(edits, incumbent, candidate, threshold):
    gains = {
        task: _task_score(candidate, task) - _task_score(incumbent, task)
        for task in incumbent["per_task"]
    }
    drops = [task for task, gain in gains.items() if gain <= -threshold]
    rows = []
    for edit in edits:
        predicted = [task for task in edit["predicted_affected"] if task in gains]
        hits = [task for task in predicted if gains[task] > 0]
        rows.append(
            {
                "n_predicted": len(predicted),
                "predicted_hit": hits,
                "hit_rate": len(hits) / len(predicted) if predicted else None,
                "unpredicted_regressions": [
                    task for task in drops if task not in predicted
                ],
            }
        )
    return rows


def _task_score(measurement, task):
    rewards = measurement["per_task"][task]
    weights = measurement.get("weights", {}).get(task, [1.0] * len(rewards))
    return _weighted_score(rewards, weights)


def _weighted_score(rewards, weights):
    if any(weight is None or weight <= 0 for weight in weights):
        raise _InvalidMeasurement(
            "complete positive weight_metric accounting is required"
        )
    return sum(reward * weight for reward, weight in zip(rewards, weights)) / sum(
        weights
    )


def _tokens(usage):
    """Count native provider usage once, including cached and delegated work."""
    if not isinstance(usage, Mapping):
        return None
    models = usage.get("model_usage")
    if isinstance(models, Mapping) and models:
        # Native session totals include delegated work absent from turn counters.
        # Partial session accounting must not fall back to the parent's counters.
        values = [_tokens(value) for value in models.values()]
        return sum(values) if None not in values else None
    if "total_tokens" in usage:
        value = usage["total_tokens"]
        return value if _counter(value) else None
    for input_key, output_key in (
        ("input_tokens", "output_tokens"),
        ("prompt_tokens", "completion_tokens"),
        ("inputTokens", "outputTokens"),
    ):
        if input_key in usage or output_key in usage:
            values = [usage.get(input_key), usage.get(output_key)]
            if input_key == "input_tokens":
                values += [
                    usage.get(key, 0)
                    for key in (
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                ]
            elif input_key == "inputTokens":
                values += [
                    usage.get(key, 0)
                    for key in ("cacheCreationInputTokens", "cacheReadInputTokens")
                ]
            return sum(values) if all(_counter(value) for value in values) else None
    calls = usage.get("model_calls")
    if isinstance(calls, (tuple, list)) and calls:
        values = [
            _tokens(call.get("usage")) for call in calls if isinstance(call, Mapping)
        ]
        return sum(values) if len(values) == len(calls) and None not in values else None
    return None


def _counter(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _select_traces(measurement, failures, successes):
    ranked = sorted(
        measurement["per_task"], key=lambda task: _task_score(measurement, task)
    )
    failed = ranked[:failures]
    passed = (
        [task for task in ranked[-successes:] if task not in failed]
        if successes
        else []
    )
    evidence = {}
    for row in measurement["evidence"]:
        evidence.setdefault(row["task_id"], []).append(row)
    selected = {}
    for task in failed + passed:
        rewards = measurement["per_task"][task]
        reward = min(rewards) if task in failed else max(rewards)
        index = rewards.index(reward)
        selected[task] = {
            "task_id": task,
            "rewards": rewards,
            "score": _task_score(measurement, task),
            "reward": reward,
            "trial": index,
            "lens": "failure" if task in failed else "success",
            "evidence": evidence[task][index],
        }
    return selected


def _quote_in_trace(quote, value):
    """Search decoded strings so multiline and Unicode quotes remain valid."""
    if isinstance(value, Mapping):
        return any(_quote_in_trace(quote, item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_quote_in_trace(quote, item) for item in value)
    return quote in str(value)


def _parse_edits(reply, changed, budget):
    value = json.loads(_replies.tagged(reply, "EDITS"))
    edits = value.get("edits") if isinstance(value, dict) else None
    if not isinstance(edits, list) or not 1 <= len(edits) <= budget:
        raise ValueError(f"declare between 1 and {budget} independent edits")
    covered = set()
    identifiers = set()
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("each edit must be an object")
        component = edit.get("component")
        if isinstance(component, str):
            component = edit["component"] = component.lower()
        if not isinstance(component, str) or component not in _COMPONENTS:
            raise ValueError("edit component must be an RRSI semantic tag")
        for key in ("id", "hypothesis", "targets_mode", "retroactive_check"):
            if not isinstance(edit.get(key), str) or not edit[key].strip():
                raise ValueError(f"each edit requires a non-empty {key}")
        if edit["id"] in identifiers:
            raise ValueError("edit ids must be unique within a candidate")
        identifiers.add(edit["id"])
        predictions = edit.get("predicted_affected")
        if (
            not isinstance(predictions, list)
            or not predictions
            or not all(isinstance(task, str) and task for task in predictions)
        ):
            raise ValueError("each edit requires predicted_affected task ids")
        if edit.get("operation", "change") not in ("change", "prune"):
            raise ValueError("edit operation must be change or prune")
        files = edit.get("paths")
        if not isinstance(files, list) or not files:
            raise ValueError("each edit requires a non-empty paths list")
        for path in files:
            if not isinstance(path, str) or path not in changed:
                raise ValueError("declared paths must actually change")
        covered.update(files)
    if covered != set(changed):
        raise ValueError("declare every changed file")
    return edits


def _diff(before, after, paths=None):
    """Include additions, deletions, modes and binary changes in the review."""
    chunks = []
    for path in before.changed_paths(after) if paths is None else paths:
        old, new = before.files.get(path), after.files.get(path)
        chunks.append(f"FILE {path}\n")
        chunks.append(
            f"executable: {old.executable if old else None} -> "
            f"{new.executable if new else None}\n"
        )
        try:
            first = old.content.decode("utf-8") if old else ""
            second = new.content.decode("utf-8") if new else ""
        except UnicodeDecodeError:
            # Opaque edits cannot be inspected by this text critic.
            raise ValueError(f"RRSI cannot review a binary edit: {path}") from None
        chunks.extend(
            unified_diff(
                first.splitlines(keepends=True),
                second.splitlines(keepends=True),
                fromfile=f"before/{path}" if old else "/dev/null",
                tofile=f"after/{path}" if new else "/dev/null",
            )
        )
    return "".join(chunks)


def _normalize_component(declared, changes, signals):
    """Match upstream diff evidence and fallback, independently of file scope."""
    rules = [*signals.items(), *_GENERIC_SIGNALS.items()]
    if any(
        component == declared
        and any(re.search(pattern, changes) for pattern in patterns)
        for component, patterns in rules
    ):
        return declared
    lines = [
        line[1:].strip()
        for line in changes.splitlines()
        if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
        and line[1:].strip()
    ]
    if lines and all(re.match(r"(?:[frb]?[\"']|#)", line) for line in lines):
        return "prompt"
    for component, patterns in rules:
        if any(re.search(pattern, changes) for pattern in patterns):
            return component
    return "prompt"


__all__ = ["RRSI"]
