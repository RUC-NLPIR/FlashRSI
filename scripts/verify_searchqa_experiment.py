"""Independently verify saved SearchQA evidence; never call a model or read .env.

The experiment artifacts are read only. JSON is printed to stdout; --output
optionally writes a separate verification artifact. Exit codes: 0 verified,
1 inconsistent evidence, 2 incomplete experiments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flashrsi.algorithms.skillopt import _dump  # noqa: E402
from flashrsi.algorithms.skillopt import _prompts as prompts  # noqa: E402
from flashrsi.algorithms.skillopt._patch import (  # noqa: E402
    _apply_guidance,
    _field,
    _Patch,
    _PatchError,
)
from flashrsi.core import Snapshot  # noqa: E402
from scripts._searchqa_experiment_support import official_metrics  # noqa: E402

EXPECTED = {
    "smoke": {"counts": {"train": 4, "dev": 4, "test": 8}, "epochs": 1, "batches": 1},
    "pilot": {
        "counts": {"train": 40, "dev": 40, "test": 100},
        "epochs": 1,
        "batches": 1,
    },
    "full": {
        "counts": {"train": 400, "dev": 200, "test": 1400},
        "epochs": 4,
        "batches": 40,
    },
}
HARNESS_NAMES = ("miniagent", "claude_code")


class VerificationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise VerificationError(message)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _equal_number(actual, expected, label):
    _require(
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
        f"{label} does not match recomputed evidence",
    )


def _data(profile_dir, profile):
    manifest = _read(profile_dir / "data-manifest.json")
    result, all_ids = {}, set()
    for split, count in EXPECTED[profile]["counts"].items():
        path = profile_dir / "data" / f"{split}.jsonl"
        raw = path.read_bytes()
        rows = [
            json.loads(line)
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
        ids = [row["id"] for row in rows]
        _require(
            len(rows) == count, f"Fixed {split} count differs from {profile} profile"
        )
        _require(len(ids) == len(set(ids)), f"Duplicate IDs in fixed {split} data")
        _require(not all_ids.intersection(ids), "Fixed train/dev/test data overlap")
        all_ids.update(ids)
        recorded = manifest["selected"][split]
        _require(recorded["ids"] == ids, f"Fixed {split} IDs differ from data manifest")
        _require(
            recorded["count"] == count,
            f"Fixed {split} count differs from data manifest",
        )
        _require(
            hashlib.sha256(raw).hexdigest() == recorded["sha256"],
            f"Fixed {split} checksum differs from data manifest",
        )
        result[split] = {row["id"]: row for row in rows}
    return result


def _score_rows(rows, reference, label):
    ids = [row["task"]["task_id"] for row in rows]
    _require(len(ids) == len(set(ids)), f"{label}: duplicate trajectory task IDs")
    _require(set(ids) <= set(reference), f"{label}: task outside its allowed split")
    scores = []
    for row, task_id in zip(rows, ids, strict=True):
        _require(
            row["status"] in {"finished", "error"}, f"{label}: unknown task status"
        )
        score = (
            official_metrics(row["output"], reference[task_id]["answers"])
            if row["status"] == "finished"
            else {"hard": 0.0, "f1": 0.0}
        )
        for metric in ("hard", "f1"):
            _equal_number(
                row["metrics"][metric], score[metric], f"{label}: recorded {metric}"
            )
        scores.append(score)
    _require(bool(rows), f"{label}: empty evaluation")
    finished = sum(row["status"] == "finished" for row in rows)
    return (
        ids,
        {
            "tasks": len(rows),
            "finished": finished,
            "errors": len(rows) - finished,
            "hard": mean(score["hard"] for score in scores),
            "f1": mean(score["f1"] for score in scores),
        },
        [score["hard"] for score in scores],
    )


def _paired(before, after):
    differences = [b - a for a, b in zip(before, after, strict=True)]
    rng = random.Random(42)
    samples = sorted(
        mean(rng.choices(differences, k=len(differences))) for _ in range(2000)
    )
    return {
        "delta_percentage_points": mean(differences) * 100,
        "improved_tasks": differences.count(1.0),
        "regressed_tasks": differences.count(-1.0),
        "paired_bootstrap_95pct_pp": [samples[49] * 100, samples[1949] * 100],
    }


def _skill_text(snapshot):
    files = {}
    for name, entry in sorted(snapshot.files.items()):
        if entry.component == "skill":
            try:
                files[name] = entry.content.decode("utf-8")
            except UnicodeDecodeError:
                continue
    return files


def _verify_invalid_patch(record, plan, attempt, selected_id):
    _require(
        plan.get("config", {}).get("algorithm", {}).get("invalid_patch_policy")
        == "reject_without_score",
        "Unscored invalid patch requires the recorded rejection policy",
    )
    _require(record["accepted"] is False, "Invalid patch was accepted")
    _require(record["parent_id"] == selected_id, "Invalid patch has wrong parent")
    _require(
        not {"score", "baseline_score", "candidate_id"}.intersection(record),
        "Invalid patch has an invented score or candidate",
    )
    snapshot = Snapshot.load(attempt / "snapshots" / f"{selected_id}.json")
    files = _skill_text(snapshot)
    kind = record["kind"]
    _require(kind in {"fast", "meta", "slow"}, "Unknown invalid-patch decision kind")
    # A fast parse failure is intentionally terminal, not an application rejection.
    patch = _Patch.parse(json.dumps(record["patch"])) if kind == "fast" else None
    try:
        if kind == "fast":
            patch.apply(files, plan["config"]["algorithm"]["edit_budget"])
        elif kind == "meta":
            _field(record["response"], "meta_skill_content")
        else:
            _apply_guidance(files, record["response"])
    except _PatchError as error:
        _require(
            str(error) == record["error"], "Invalid-patch error does not reproduce"
        )
    else:
        raise VerificationError("Recorded invalid patch is actually valid")


def _verify_slow_epochs(attempt, plan, training, profile):
    """Consume each sequential epoch comparison block, including its exact gate."""
    expected = EXPECTED[profile]
    if expected["epochs"] == 1:
        return []
    config = plan["config"]["algorithm"]
    use_meta = config.get("use_meta_skill", True)
    use_slow = config.get("use_slow_update", True)
    _require(
        type(use_meta) is bool and type(use_slow) is bool, "Invalid slow/meta flags"
    )
    size, seed = config.get("slow_update_samples", 20), config.get("seed", 42)
    _require(type(size) is int and size == 20, "Full slow comparison requires 20 tasks")
    _require(type(seed) is int, "Invalid comparison sampling seed")
    benchmark = plan["config"].get("benchmark", {})
    benchmark_seed = benchmark.get("seed", 0)
    _require(type(benchmark_seed) is int, "Invalid benchmark ordering seed")
    _require(
        benchmark.get("split", "auto") == "auto", "Expected fixed benchmark splits"
    )
    # SearchQA's auto split preserves membership but hash-sorts each provided split.
    # SkillOpt samples from that benchmark order, not the source JSONL order.
    ordered_training = sorted(
        training,
        key=lambda task_id: (
            hashlib.sha256(f"{benchmark_seed}:{task_id}".encode()).digest(),
            task_id,
        ),
    )
    paths = iter(sorted((attempt / "trajectories").glob("*.json")))
    per_epoch = expected["batches"] // expected["epochs"]
    selected, best, meta_skill = plan["initial_snapshot"], None, ""
    epoch_end, verified, fast_steps = {}, [], 0

    def label(path):
        return path.name.split("-", 1)[1].removesuffix(".json")

    def take(wanted, epoch):
        path = next(paths, None)
        _require(
            path is not None and label(path) == wanted,
            f"Epoch {epoch}: expected {wanted} in the slow-update sequence",
        )
        return _read(path)

    def evidence(row):
        return {
            **row,
            "messages": [
                item
                for item in row.get("messages", [])
                if item.get("type") != "RunConfig"
            ],
        }

    def worker_reply(kind, epoch, fields):
        record = take(kind, epoch)
        template = prompts.META_SKILL if kind == "meta" else prompts.SLOW_UPDATE
        _require(
            record["prompt"] == template.format(**fields),
            f"Epoch {epoch}: {kind} prompt differs from its comparison evidence",
        )
        _require(
            record["trajectory"]["status"] == "finished", f"Unfinished {kind} Worker"
        )
        return record["trajectory"]["output"]

    def invalid(kind, epoch, response):
        record = take("decision", epoch)
        _require(
            record.get("kind") == kind
            and record.get("epoch") == epoch
            and record.get("reason") == "invalid_patch"
            and record.get("response") == response,
            f"Epoch {epoch}: missing or mismatched invalid {kind} rejection",
        )
        _verify_invalid_patch(record, plan, attempt, selected)

    for path in paths:
        stage = label(path)
        if stage in {"comparison_before", "comparison_after", "meta", "slow"}:
            raise VerificationError(
                "Slow/meta evidence appears outside its epoch boundary"
            )
        if stage in {"failure", "success"}:
            _require(
                _read(path)["prompt"].endswith(
                    "\nOPTIMIZER MEMORY:\n" + meta_skill + "\n"
                ),
                "Reflection did not retain the latest valid meta skill",
            )
            continue
        if stage == "baseline":
            best = mean(row["metrics"]["hard"] for row in _read(path)["trajectories"])
        if stage != "decision":
            continue
        decision = _read(path)
        _require(
            decision["kind"] == "fast", "Slow/meta decision is outside its epoch block"
        )
        fast_steps += 1
        if decision["accepted"]:
            selected, best = decision["candidate_id"], decision["score"]
        if fast_steps % per_epoch:
            continue
        epoch = fast_steps // per_epoch - 1
        if epoch == 0 or not (use_meta or use_slow):
            epoch_end[epoch] = selected
            continue

        previous = Snapshot.load(attempt / "snapshots" / f"{epoch_end[epoch - 1]}.json")
        current = Snapshot.load(attempt / "snapshots" / f"{selected}.json")
        ids = random.Random(seed + epoch * 2000).sample(ordered_training, size)
        before, after = (
            take("comparison_before", epoch),
            take("comparison_after", epoch),
        )
        for kind, record, snapshot in (
            ("before", before, previous),
            ("after", after, current),
        ):
            _require(
                record["snapshot_id"] == snapshot.id,
                f"Epoch {epoch}: comparison {kind} snapshot mismatch",
            )
            _require(
                [row["task"]["task_id"] for row in record["trajectories"]] == ids,
                f"Epoch {epoch}: comparison {kind} tasks differ from the fixed 20-task sample",
            )
        files = _skill_text(current)
        fields = {
            "previous": _dump(_skill_text(previous)),
            "current": _dump(files),
            "comparison": _dump(
                [
                    {"previous": evidence(a), "current": evidence(b)}
                    for a, b in zip(
                        before["trajectories"], after["trajectories"], strict=True
                    )
                ]
            ),
        }
        if use_meta:
            reply = worker_reply("meta", epoch, fields)
            try:
                new_meta = _field(reply, "meta_skill_content")
            except _PatchError:
                invalid("meta", epoch, reply)
            else:
                meta_skill = new_meta
        if use_slow:
            reply = worker_reply("slow", epoch, fields)
            try:
                updated = _apply_guidance(files, reply)
            except _PatchError:
                invalid("slow", epoch, reply)
            else:
                if updated == files:
                    decision = take("decision", epoch)
                    _require(
                        decision
                        == {
                            "epoch": epoch,
                            "kind": "slow",
                            "reason": "no_change",
                            "accepted": False,
                        },
                        f"Epoch {epoch}: unchanged slow guidance has an invalid gate",
                    )
                else:
                    evaluation = take("candidate_dev", epoch)
                    candidate = Snapshot.load(
                        attempt / "snapshots" / f"{evaluation['snapshot_id']}.json"
                    )
                    expected_files = dict(current.files)
                    for name, text in updated.items():
                        expected_files[name] = replace(
                            current.files[name], content=text.encode("utf-8")
                        )
                    current._validate_candidate(candidate)
                    _require(
                        candidate.parent_id == selected
                        and candidate.files == expected_files,
                        f"Epoch {epoch}: slow candidate differs from the Worker guidance",
                    )
                    decision = take("decision", epoch)
                    _require(
                        decision.get("epoch") == epoch
                        and decision.get("kind") == "slow"
                        and decision.get("parent_id") == selected
                        and decision.get("candidate_id") == candidate.id,
                        f"Epoch {epoch}: slow gate does not match its candidate",
                    )
                    score = mean(
                        row["metrics"]["hard"] for row in evaluation["trajectories"]
                    )
                    _equal_number(
                        decision["baseline_score"], best, "Slow gate baseline"
                    )
                    _equal_number(decision["score"], score, "Slow candidate dev score")
                    _require(
                        decision["accepted"] == (score > best),
                        "Invalid slow improvement gate",
                    )
                    if decision["accepted"]:
                        selected, best = candidate.id, score
        epoch_end[epoch] = selected
        verified.append(epoch)
    wanted = list(range(1, expected["epochs"])) if use_meta or use_slow else []
    _require(verified == wanted, "Missing epoch slow/meta evidence")
    return verified


def _verify_completed(experiment, profile, plan, result):
    counts = EXPECTED[profile]["counts"]
    data = _data(experiment.parent, profile)
    for name, record in (("plan", plan), ("result", result)):
        _require(record["profile"] == profile, f"{name} profile mismatch")
        _require(record["harness"] == experiment.name, f"{name} harness mismatch")
        _require(record["split_counts"] == counts, f"{name} split counts mismatch")
    _require(
        plan["fingerprint"] == result["fingerprint"], "Plan/result fingerprint mismatch"
    )
    _require(
        plan["initial_snapshot"] == result["initial_snapshot"],
        "Initial snapshot mismatch",
    )
    _require(
        result["test_used_for_selection"] is False,
        "Result declares test used for selection",
    )
    # Resolve within the supplied run so archived absolute paths survive renames.
    attempt = experiment / "attempts" / Path(result["attempt"]).name
    _require(
        _read(attempt / "result.json") == result,
        "Attempt result differs from published result",
    )

    initial_id, final_id = result["initial_snapshot"], result["final_snapshot"]
    for identifier in {initial_id, final_id}:
        _require(
            bool(re.fullmatch(r"[a-f0-9]{64}", identifier)),
            "Invalid snapshot identifier",
        )
        snapshot = Snapshot.load(attempt / "snapshots" / f"{identifier}.json")
        _require(snapshot.id == identifier, "Snapshot content hash differs from result")

    evaluations, training, decisions, sequence, tests = Counter(), [], [], [], {}
    non_test_sequences = []
    finished_counts = Counter()
    selected_id = initial_id
    candidate_scores = {}
    baseline_score = None
    for path in sorted((attempt / "trajectories").glob("*.json")):
        match = re.fullmatch(r"(\d+)-(.+)\.json", path.name)
        _require(match is not None, "Unrecognized trajectory filename")
        number, label = int(match[1]), match[2]
        sequence.append(number)
        record = _read(path)
        if label not in {"initial-test", "final-test"}:
            non_test_sequences.append(number)
        if "trajectories" in record:
            split = (
                "test"
                if label in {"initial-test", "final-test"}
                else "dev"
                if label in {"baseline", "candidate_dev"}
                else "train"
                if label in {"train", "comparison_before", "comparison_after"}
                else None
            )
            _require(split is not None, f"Unexpected scored evaluation label: {label}")
            ids, summary, hard = _score_rows(record["trajectories"], data[split], label)
            _require(summary["errors"] == 0, f"{label}: unfinished task execution")
            evaluations[label] += 1
            finished_counts["finished"] += summary["finished"]
            finished_counts["errors"] += summary["errors"]
            if split in {"dev", "test"}:
                _require(
                    set(ids) == set(data[split]),
                    f"{label}: holdout IDs are not the fixed {split} set",
                )
            if label == "train":
                _require(
                    record["snapshot_id"] == selected_id,
                    "Training used an unselected snapshot",
                )
                training.append(ids)
            elif label == "baseline":
                _require(
                    record["snapshot_id"] == initial_id, "Initial dev snapshot mismatch"
                )
                baseline_score = summary["hard"]
            elif label == "candidate_dev":
                candidate_scores[record["snapshot_id"]] = summary["hard"]
            elif split == "test":
                _require(label not in tests, f"Duplicate {label} evaluation")
                wanted_id = initial_id if label == "initial-test" else final_id
                _require(
                    record["snapshot_id"] == wanted_id, f"{label}: snapshot mismatch"
                )
                tests[label] = {
                    "sequence": number,
                    "ids": ids,
                    "summary": summary,
                    "hard": hard,
                }
        elif label == "decision":
            decisions.append(record)
            if record.get("reason") == "invalid_patch":
                _verify_invalid_patch(record, plan, attempt, selected_id)
            if "score" in record:
                _equal_number(
                    record["baseline_score"], baseline_score, "Decision baseline score"
                )
                _equal_number(
                    record["score"],
                    candidate_scores[record["candidate_id"]],
                    "Candidate dev score",
                )
                _require(
                    record["accepted"] == (record["score"] > baseline_score),
                    "Decision violates strict dev improvement",
                )
            if record["accepted"]:
                _require(
                    record["parent_id"] == selected_id,
                    "Accepted candidate has wrong parent",
                )
                selected_id, baseline_score = record["candidate_id"], record["score"]

    _require(
        sequence == list(range(1, len(sequence) + 1)),
        "Trajectory sequence has gaps or duplicates",
    )
    _require(
        evaluations["baseline"] == 1, "Exactly one initial dev evaluation is required"
    )
    _require(
        set(tests) == {"initial-test", "final-test"},
        "Completed result lacks both test evaluations",
    )
    before, after = tests["initial-test"], tests["final-test"]
    _require(before["ids"] == after["ids"], "Initial/final test order differs")
    _require(
        max(non_test_sequences) < before["sequence"] < after["sequence"],
        "Test evaluation preceded completed training/selection",
    )
    _require(
        selected_id == final_id, "Final snapshot is not the last accepted snapshot"
    )

    expected = EXPECTED[profile]
    _require(len(training) == expected["batches"], "Wrong number of fast train batches")
    per_epoch = expected["batches"] // expected["epochs"]
    batch_size = counts["train"] // per_epoch
    for epoch in range(expected["epochs"]):
        batches = training[epoch * per_epoch : (epoch + 1) * per_epoch]
        _require(
            all(len(batch) == batch_size for batch in batches),
            f"Epoch {epoch}: wrong train batch size",
        )
        ids = [task_id for batch in batches for task_id in batch]
        _require(
            Counter(ids) == Counter(data["train"].keys()),
            f"Epoch {epoch}: train coverage has omissions or duplicates",
        )
    fast = [record for record in decisions if record["kind"] == "fast"]
    _require(
        [record["step"] for record in fast] == list(range(1, expected["batches"] + 1)),
        "Fast decision step sequence mismatch",
    )
    _require(
        [record["epoch"] for record in fast]
        == [i // per_epoch for i in range(expected["batches"])],
        "Fast decision epoch sequence mismatch",
    )
    _require(
        result["accepted_candidates"] == sum(bool(d["accepted"]) for d in decisions),
        "Accepted candidate count mismatch",
    )
    _require(
        result["candidate_decisions"] == len(decisions),
        "Candidate decision count mismatch",
    )
    for saved_name, evidence in (("baseline_test", before), ("evolved_test", after)):
        for field in ("tasks", "finished", "hard", "f1"):
            _equal_number(
                result[saved_name][field],
                evidence["summary"][field],
                f"{saved_name}.{field}",
            )
    paired = _paired(before["hard"], after["hard"])
    for field in ("delta_percentage_points", "improved_tasks", "regressed_tasks"):
        _equal_number(
            result["paired_comparison"][field], paired[field], f"paired.{field}"
        )
    actual_interval = result["paired_comparison"]["paired_bootstrap_95pct_pp"]
    _require(len(actual_interval) == 2, "Paired interval must have two endpoints")
    for actual, expected_value in zip(
        actual_interval, paired["paired_bootstrap_95pct_pp"], strict=True
    ):
        _equal_number(actual, expected_value, "Paired bootstrap interval")
    slow_epochs = _verify_slow_epochs(attempt, plan, data["train"], profile)
    return {
        "harness": experiment.name,
        "status": "passed",
        "attempt": str(attempt),
        "initial_snapshot": initial_id,
        "final_snapshot": final_id,
        "snapshot_changed": initial_id != final_id,
        "baseline_test": before["summary"],
        "evolved_test": after["summary"],
        "paired_comparison": paired,
        "evaluations": dict(evaluations),
        "evaluated_task_counts": dict(finished_counts),
        "epochs_verified": expected["epochs"],
        "slow_update_epochs_verified": slow_epochs,
        "train_batches_verified": len(training),
        "accepted_candidates": result["accepted_candidates"],
        "invalid_patch_rejections_verified": sum(
            d.get("reason") == "invalid_patch" for d in decisions
        ),
        "checks": [
            "fixed_data_hashes_and_disjoint_splits",
            "official_scores_recomputed_from_outputs_and_fixed_answers",
            "test_ids_and_initial_final_order",
            "test_only_after_training_and_selection",
            "complete_per_epoch_train_coverage",
            "epoch_comparisons_meta_memory_and_slow_gates",
            "strict_dev_selection_and_final_snapshot_hash",
            "published_summary_and_paired_interval",
        ],
    }


def verify_harness(experiment, profile):
    experiment = Path(experiment)
    try:
        result_path = experiment / "result.json"
        if not result_path.exists():
            state_path = experiment / "status.json"
            state = (
                _read(state_path).get("status") if state_path.exists() else "pending"
            )
            return {
                "harness": experiment.name,
                "status": "incomplete",
                "recorded_status": state,
                "reason": "No completed result.json; evidence has not been verified",
            }
        result = _read(result_path)
        if result.get("status") != "finished":
            return {
                "harness": experiment.name,
                "status": "incomplete",
                "reason": "Result is not finished; evidence has not been verified",
            }
        plan = _read(experiment / "plan.json")
        return _verify_completed(experiment, profile, plan, result)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        return {
            "harness": experiment.name,
            "status": "failed",
            "error": str(error) or type(error).__name__,
        }


def verify(run_root, profile):
    _require(profile in EXPECTED, "Unsupported verification profile")
    run_root = Path(run_root).expanduser().resolve()
    results = [
        verify_harness(run_root / profile / name, profile) for name in HARNESS_NAMES
    ]
    states = {result["status"] for result in results}
    status = (
        "failed"
        if "failed" in states
        else "incomplete"
        if "incomplete" in states
        else "passed"
    )
    return {
        "status": status,
        "profile": profile,
        "run_root": str(run_root),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Saved artifact consistency and scoring; not independent reruns or proof of model identity",
        "experiments": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--profile", choices=EXPECTED, required=True)
    parser.add_argument(
        "--output", type=Path, help="Optional separate verification.json artifact"
    )
    args = parser.parse_args()
    report = verify(args.run_root, args.profile)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return {"passed": 0, "failed": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
