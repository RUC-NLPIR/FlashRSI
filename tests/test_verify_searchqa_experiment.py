"""Verify that incomplete or altered experimental evidence cannot pass."""

import hashlib
import json
import random
from dataclasses import replace

import pytest

from flashrsi.algorithms.skillopt import _dump
from flashrsi.algorithms.skillopt import _prompts as prompts
from flashrsi.algorithms.skillopt._patch import _apply_guidance, _field, _PatchError
from flashrsi.core import Snapshot
from flashrsi.core.snapshot import _create_snapshot
from scripts._searchqa_experiment_support import ExperimentSearchQA
from scripts.verify_searchqa_experiment import EXPECTED, verify_harness


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _fixture(
    tmp_path,
    profile="smoke",
    *,
    advance=False,
    meta_replies=None,
    slow_replies=None,
    benchmark_seed=42,
):
    profile_dir = tmp_path / profile
    experiment = profile_dir / "miniagent"
    attempt = experiment / "attempts/run"
    settings = EXPECTED[profile]
    counts = settings["counts"]
    data, selected = {}, {}
    for split, count in counts.items():
        rows = [
            {
                "id": f"{split}-{i}",
                "question": "Question?",
                "context": "Context",
                "answers": ["correct"],
            }
            for i in range(count)
        ]
        data[split] = rows
        payload = "".join(json.dumps(row) + "\n" for row in rows)
        path = profile_dir / "data" / f"{split}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        selected[split] = {
            "ids": [row["id"] for row in rows],
            "count": count,
            "sha256": hashlib.sha256(payload.encode()).hexdigest(),
        }
    _write(profile_dir / "data-manifest.json", {"selected": selected})
    seed = tmp_path / "seed"
    (seed / "skills").mkdir(parents=True)
    (seed / "skills/main.md").write_text("Initial skill\n")
    snapshot = Snapshot._capture(
        seed, agent_type="miniagent", component_rules={"skill": ("skills/*.md",)}
    )
    (attempt / "snapshots").mkdir(parents=True)
    snapshot.save(attempt / "snapshots" / f"{snapshot.id}.json")
    plan = {
        "profile": profile,
        "harness": "miniagent",
        "split_counts": counts,
        "fingerprint": "fixture",
        "initial_snapshot": snapshot.id,
        "config": {
            "benchmark": {"seed": benchmark_seed, "split": "auto"},
            "algorithm": {
                "seed": 42,
                "use_meta_skill": True,
                "use_slow_update": True,
                "slow_update_samples": 20,
                "edit_budget": 4,
                "invalid_patch_policy": "reject_without_score",
            },
        },
    }
    _write(experiment / "plan.json", plan)
    sequence = 0

    def record(label, value):
        nonlocal sequence
        sequence += 1
        _write(attempt / "trajectories" / f"{sequence:05d}-{label}.json", value)

    current, previous_epoch, meta_skill = snapshot, None, ""
    ordered_training = sorted(
        data["train"],
        key=lambda row: (
            hashlib.sha256(f"{benchmark_seed}:{row['id']}".encode()).digest(),
            row["id"],
        ),
    )
    accepted, decisions = 0, 0
    best = 0.0 if advance else 1.0

    def evaluate(label, rows, version=None, score=1.0):
        value = {
            "snapshot_id": (version or current).id,
            "trajectories": [
                {
                    "task": {"task_id": row["id"]},
                    "status": "finished",
                    "output": "correct" if index < int(len(rows) * score) else "wrong",
                    "messages": [],
                    "metrics": {
                        "hard": float(index < int(len(rows) * score)),
                        "f1": float(index < int(len(rows) * score)),
                    },
                }
                for index, row in enumerate(rows)
            ],
        }
        record(label, value)
        return value

    def child(files):
        version = _create_snapshot(
            {
                name: replace(entry, content=files[name].encode())
                for name, entry in current.files.items()
            },
            agent_type=current.agent_type,
            component_rules=current.component_rules,
            parent=current,
        )
        path = attempt / "snapshots" / f"{version.id}.json"
        if not path.exists():
            version.save(path)
        return version

    def worker(label, reply, fields):
        response = reply if isinstance(reply, str) else json.dumps(reply)
        record(
            label,
            {
                "prompt": (
                    prompts.META_SKILL if label == "meta" else prompts.SLOW_UPDATE
                ).format(**fields),
                "trajectory": {"status": "finished", "output": response},
            },
        )
        return response

    def reject(kind, epoch, reply, error):
        record(
            "decision",
            {
                "kind": kind,
                "epoch": epoch,
                "parent_id": current.id,
                "reason": "invalid_patch",
                "accepted": False,
                "response": reply,
                "error": str(error),
            },
        )

    evaluate("baseline", data["dev"], score=best)
    per_epoch = settings["batches"] // settings["epochs"]
    batch_size = counts["train"] // per_epoch
    for step in range(settings["batches"]):
        epoch = step // per_epoch
        offset = step % per_epoch * batch_size
        evaluate("train", data["train"][offset : offset + batch_size])
        record(
            "success",
            {
                "prompt": "[SkillOpt: success]\nOPTIMIZER MEMORY:\n"
                + meta_skill
                + "\n",
                "trajectory": {"status": "finished", "output": '{"edits": []}'},
            },
        )
        if advance and step == per_epoch:
            candidate = child(
                {
                    name: entry.content.decode() + "Fast improvement\n"
                    for name, entry in current.files.items()
                }
            )
            evaluate("candidate_dev", data["dev"], candidate, 0.5)
            record(
                "decision",
                {
                    "kind": "fast",
                    "epoch": epoch,
                    "step": step + 1,
                    "parent_id": current.id,
                    "candidate_id": candidate.id,
                    "score": 0.5,
                    "baseline_score": best,
                    "accepted": True,
                },
            )
            current, best, accepted = candidate, 0.5, accepted + 1
        else:
            record(
                "decision",
                {
                    "kind": "fast",
                    "epoch": epoch,
                    "step": step + 1,
                    "accepted": False,
                    "reason": "empty_patch",
                },
            )
        decisions += 1
        if (step + 1) % per_epoch:
            continue
        if epoch > 0:
            sample = random.Random(42 + epoch * 2000).sample(ordered_training, 20)
            before = evaluate("comparison_before", sample, previous_epoch)
            after = evaluate("comparison_after", sample)
            files = {
                name: entry.content.decode() for name, entry in current.files.items()
            }
            fields = {
                "previous": _dump(
                    {
                        name: entry.content.decode()
                        for name, entry in previous_epoch.files.items()
                    }
                ),
                "current": _dump(files),
                "comparison": _dump(
                    [
                        {"previous": a, "current": b}
                        for a, b in zip(
                            before["trajectories"], after["trajectories"], strict=True
                        )
                    ]
                ),
            }
            reply = worker(
                "meta",
                (meta_replies or {}).get(
                    epoch, {"meta_skill_content": f"Memory {epoch}"}
                ),
                fields,
            )
            try:
                meta_skill = _field(reply, "meta_skill_content")
            except _PatchError as error:
                reject("meta", epoch, reply, error)
                decisions += 1
            reply = worker(
                "slow", (slow_replies or {}).get(epoch, {"guidance": []}), fields
            )
            try:
                updated = _apply_guidance(files, reply)
            except _PatchError as error:
                reject("slow", epoch, reply, error)
            else:
                if updated == files:
                    record(
                        "decision",
                        {
                            "kind": "slow",
                            "epoch": epoch,
                            "reason": "no_change",
                            "accepted": False,
                        },
                    )
                else:
                    candidate = child(updated)
                    score = 0.75 if advance else 1.0
                    evaluate("candidate_dev", data["dev"], candidate, score)
                    improved = score > best
                    record(
                        "decision",
                        {
                            "kind": "slow",
                            "epoch": epoch,
                            "parent_id": current.id,
                            "candidate_id": candidate.id,
                            "score": score,
                            "baseline_score": best,
                            "accepted": improved,
                        },
                    )
                    if improved:
                        current, best, accepted = candidate, score, accepted + 1
            decisions += 1
        previous_epoch = current
    evaluate("initial-test", data["test"], snapshot)
    evaluate("final-test", data["test"], current)
    score = {
        "tasks": counts["test"],
        "finished": counts["test"],
        "hard": 1.0,
        "f1": 1.0,
    }
    result = {
        **plan,
        "status": "finished",
        "attempt": str(attempt),
        "final_snapshot": current.id,
        "test_used_for_selection": False,
        "accepted_candidates": accepted,
        "candidate_decisions": decisions,
        "baseline_test": score,
        "evolved_test": score,
        "paired_comparison": {
            "delta_percentage_points": 0,
            "improved_tasks": 0,
            "regressed_tasks": 0,
            "paired_bootstrap_95pct_pp": [0, 0],
        },
    }
    _write(experiment / "result.json", result)
    _write(attempt / "result.json", result)
    return experiment, attempt, result


@pytest.mark.parametrize("profile", ["smoke", "pilot", "full"])
def test_complete_evidence_recomputes(tmp_path, profile):
    experiment, _, _ = _fixture(tmp_path, profile)
    result = verify_harness(experiment, profile)
    assert result["status"] == "passed", result
    assert result["train_batches_verified"] == EXPECTED[profile]["batches"]
    assert result["evolved_test"]["tasks"] == EXPECTED[profile]["counts"]["test"]
    assert result["slow_update_epochs_verified"] == (
        [1, 2, 3] if profile == "full" else []
    )


def test_unfinished_run_is_incomplete(tmp_path):
    _write(tmp_path / "status.json", {"status": "running"})
    assert verify_harness(tmp_path, "full")["status"] == "incomplete"


@pytest.mark.parametrize("mutation", ["score", "split", "order", "error"])
def test_altered_test_evidence_fails(tmp_path, mutation):
    experiment, attempt, _ = _fixture(tmp_path)
    path = next((attempt / "trajectories").glob("*-final-test.json"))
    record = json.loads(path.read_text())
    rows = record["trajectories"]
    if mutation == "score":
        rows[0]["metrics"]["hard"] = 0
    elif mutation == "split":
        rows[0]["task"]["task_id"] = "train-0"
    elif mutation == "order":
        rows.reverse()
    else:
        rows[0]["status"] = "error"
        rows[0]["metrics"] = {"hard": 0, "f1": 0}
    _write(path, record)
    assert verify_harness(experiment, "smoke")["status"] == "failed"


def test_full_epoch_duplicate_or_omission_fails(tmp_path):
    experiment, attempt, _ = _fixture(tmp_path, "full")
    paths = sorted((attempt / "trajectories").glob("*-train.json"))
    first = json.loads(paths[0].read_text())
    second = json.loads(paths[1].read_text())
    second["trajectories"] = first["trajectories"]
    _write(paths[1], second)
    result = verify_harness(experiment, "full")
    assert result["status"] == "failed"
    assert "coverage" in result["error"]


def test_consistently_forged_summary_still_fails_recomputation(tmp_path):
    experiment, attempt, result = _fixture(tmp_path)
    result["evolved_test"]["hard"] = 0.5
    _write(experiment / "result.json", result)
    _write(attempt / "result.json", result)
    assert verify_harness(experiment, "smoke")["status"] == "failed"


def test_changed_snapshot_bytes_fail_hash_validation(tmp_path):
    experiment, attempt, result = _fixture(tmp_path)
    path = attempt / "snapshots" / f"{result['final_snapshot']}.json"
    path.write_text("{}")
    assert verify_harness(experiment, "smoke")["status"] == "failed"


@pytest.mark.parametrize("mutation", [None, "valid_patch", "score", "parent"])
def test_invalid_patch_rejection_must_reproduce_without_fake_score(tmp_path, mutation):
    experiment, attempt, result = _fixture(tmp_path)
    plan_path = experiment / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["config"] = {
        "algorithm": {"invalid_patch_policy": "reject_without_score", "edit_budget": 4}
    }
    _write(plan_path, plan)
    path = next((attempt / "trajectories").glob("*-decision.json"))
    record = json.loads(path.read_text())
    record.update(
        reason="invalid_patch",
        parent_id=result["initial_snapshot"],
        error="edit target must occur exactly once in the skill",
        patch={
            "edits": [
                {
                    "op": "replace",
                    "path": "skills/main.md",
                    "target": "missing text",
                    "content": "replacement",
                }
            ]
        },
    )
    if mutation == "valid_patch":
        record["patch"]["edits"][0]["target"] = "Initial skill"
    elif mutation == "score":
        record["score"] = 0.0
    elif mutation == "parent":
        record["parent_id"] = "wrong-parent"
    _write(path, record)
    verified = verify_harness(experiment, "smoke")
    assert verified["status"] == ("passed" if mutation is None else "failed"), verified


def _events(attempt):
    return [
        (path.name.split("-", 1)[1].removesuffix(".json"), json.loads(path.read_text()))
        for path in sorted((attempt / "trajectories").glob("*.json"))
    ]


def _rewrite(experiment, attempt, result, events):
    """Keep numbering and aggregate counts coherent so stage checks catch omissions."""
    for path in (attempt / "trajectories").glob("*.json"):
        path.unlink()
    for index, (label, record) in enumerate(events, 1):
        _write(attempt / "trajectories" / f"{index:05d}-{label}.json", record)
    decisions = [record for label, record in events if label == "decision"]
    result["candidate_decisions"] = len(decisions)
    result["accepted_candidates"] = sum(record["accepted"] for record in decisions)
    _write(experiment / "result.json", result)
    _write(attempt / "result.json", result)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_before",
        "missing_after",
        "missing_meta",
        "missing_slow",
        "missing_decision",
        "missing_epoch_block",
        "missing_all_blocks",
        "wrong_before_snapshot",
        "wrong_after_snapshot",
        "wrong_task",
        "wrong_sample_order",
        "short_sample",
        "wrong_meta_prompt",
        "wrong_slow_prompt",
        "wrong_decision_epoch",
        "stale_meta_memory",
    ],
)
def test_full_slow_epoch_omissions_and_mismatches_fail(tmp_path, mutation):
    experiment, attempt, result = _fixture(tmp_path, "full", advance=True)
    events = _events(attempt)
    before_index = next(
        i for i, (label, _) in enumerate(events) if label == "comparison_before"
    )
    after_index, meta_index, slow_index, decision_index = range(
        before_index + 1, before_index + 5
    )
    before, after = events[before_index][1], events[after_index][1]
    assert before["snapshot_id"] != after["snapshot_id"]
    if mutation.startswith("missing_"):
        indices = {
            "missing_before": [before_index],
            "missing_after": [after_index],
            "missing_meta": [meta_index],
            "missing_slow": [slow_index],
            "missing_decision": [decision_index],
            "missing_epoch_block": list(range(before_index, decision_index + 1)),
            "missing_all_blocks": [
                i
                for i, (label, record) in enumerate(events)
                if label in {"comparison_before", "comparison_after", "meta", "slow"}
                or (label == "decision" and record["kind"] != "fast")
            ],
        }[mutation]
        events = [event for i, event in enumerate(events) if i not in indices]
    elif mutation == "wrong_before_snapshot":
        before["snapshot_id"] = after["snapshot_id"]
    elif mutation == "wrong_after_snapshot":
        after["snapshot_id"] = before["snapshot_id"]
    elif mutation == "wrong_task":
        ids = {row["task"]["task_id"] for row in after["trajectories"]}
        substitute = next(f"train-{i}" for i in range(400) if f"train-{i}" not in ids)
        after["trajectories"][0]["task"]["task_id"] = substitute
    elif mutation == "wrong_sample_order":
        before["trajectories"].reverse()
        after["trajectories"].reverse()
    elif mutation == "short_sample":
        before["trajectories"].pop()
        after["trajectories"].pop()
    elif mutation in {"wrong_meta_prompt", "wrong_slow_prompt"}:
        events[meta_index if mutation == "wrong_meta_prompt" else slow_index][1][
            "prompt"
        ] += "forged evidence"
    elif mutation == "wrong_decision_epoch":
        events[decision_index][1]["epoch"] = 0
    else:
        reflection = next(
            record
            for label, record in events[decision_index + 1 :]
            if label == "success"
        )
        reflection["prompt"] = "[SkillOpt: success]\nOPTIMIZER MEMORY:\n\n"
    _rewrite(experiment, attempt, result, events)
    verified = verify_harness(experiment, "full")
    assert verified["status"] == "failed", verified


@pytest.mark.parametrize(
    "advance,meta_replies,slow_replies",
    [
        (
            False,
            {},
            {1: {"guidance": [{"path": "skills/main.md", "content": "slow guidance"}]}},
        ),
        (
            True,
            {1: "not JSON"},
            {1: {"guidance": [{"path": "skills/main.md", "content": "slow guidance"}]}},
        ),
        (True, {}, {1: "not JSON"}),
        (True, {2: {"meta_skill_content": 12}}, {2: "not JSON"}),
        (True, {1: {"meta_skill_content": ""}}, {}),
    ],
)
def test_full_sequential_recovery_and_valid_slow_gates_pass(
    tmp_path, advance, meta_replies, slow_replies
):
    experiment, _, _ = _fixture(
        tmp_path,
        "full",
        advance=advance,
        meta_replies=meta_replies,
        slow_replies=slow_replies,
    )
    verified = verify_harness(experiment, "full")
    assert verified["status"] == "passed", verified
    assert verified["slow_update_epochs_verified"] == [1, 2, 3]


@pytest.mark.parametrize("kind", ["meta", "slow"])
@pytest.mark.parametrize(
    "mutation", ["missing_rejection", "different_response", "candidate_evaluation"]
)
def test_invalid_sequential_reply_requires_its_exact_unscored_rejection(
    tmp_path, kind, mutation
):
    malformed = {"meta_skill_content": 42} if kind == "meta" else {"guidance": 42}
    options = {f"{kind}_replies": {1: malformed}}
    experiment, attempt, result = _fixture(tmp_path, "full", advance=True, **options)
    events = _events(attempt)
    index = next(
        i
        for i, (label, record) in enumerate(events)
        if label == "decision"
        and record["kind"] == kind
        and record.get("reason") == "invalid_patch"
    )
    if mutation == "missing_rejection":
        events.pop(index)
    elif mutation == "different_response":
        # The same parse error still reproduces, but this was not the Worker reply.
        events[index][1]["response"] = json.dumps(
            {"meta_skill_content": 99} if kind == "meta" else {"guidance": 99}
        )
    else:
        evaluation = next(event for event in events if event[0] == "candidate_dev")
        events.insert(index, evaluation)
    _rewrite(experiment, attempt, result, events)
    assert verify_harness(experiment, "full")["status"] == "failed"


@pytest.mark.parametrize(
    "mutation", ["wrong_candidate", "changed_guidance", "fake_noop", "wrong_gate"]
)
def test_valid_slow_guidance_requires_matching_candidate_and_gate(tmp_path, mutation):
    replies = {
        1: {"guidance": [{"path": "skills/main.md", "content": "slow guidance"}]}
    }
    experiment, attempt, result = _fixture(tmp_path, "full", slow_replies=replies)
    events = _events(attempt)
    slow_index = next(i for i, (label, _) in enumerate(events) if label == "slow")
    evaluation, decision = events[slow_index + 1][1], events[slow_index + 2][1]
    if mutation == "wrong_candidate":
        evaluation["snapshot_id"] = result["initial_snapshot"]
        decision["candidate_id"] = result["initial_snapshot"]
    elif mutation == "changed_guidance":
        events[slow_index][1]["trajectory"]["output"] = json.dumps(
            {"guidance": [{"path": "skills/main.md", "content": "different guidance"}]}
        )
    elif mutation == "fake_noop":
        events.pop(slow_index + 1)
        events[slow_index + 1] = (
            "decision",
            {"epoch": 1, "kind": "slow", "reason": "no_change", "accepted": False},
        )
    else:
        decision["accepted"] = True  # A tie must be rejected.
    _rewrite(experiment, attempt, result, events)
    verified = verify_harness(experiment, "full")
    assert verified["status"] == "failed", verified


def test_comparison_sampling_matches_real_benchmark_order_with_distinct_seed(tmp_path):
    experiment, attempt, _ = _fixture(tmp_path, "full", benchmark_seed=7)
    benchmark = ExperimentSearchQA(
        {"data_path": str(experiment.parent / "data"), "seed": 7, "split": "auto"}
    )
    benchmark.load()
    ids = [
        task.task_id for task in random.Random(2042).sample(list(benchmark.train), 20)
    ]
    before = next(
        record for label, record in _events(attempt) if label == "comparison_before"
    )
    assert [row["task"]["task_id"] for row in before["trajectories"]] == ids
    verified = verify_harness(experiment, "full")
    assert verified["status"] == "passed", verified


def test_consistent_source_order_sample_fails_benchmark_order_verification(tmp_path):
    experiment, attempt, result = _fixture(tmp_path, "full")
    events = _events(attempt)
    start = next(
        i for i, (label, _) in enumerate(events) if label == "comparison_before"
    )
    wrong_ids = random.Random(2042).sample([f"train-{i}" for i in range(400)], 20)
    before, after = events[start][1], events[start + 1][1]
    for record in (before, after):
        for row, task_id in zip(record["trajectories"], wrong_ids, strict=True):
            row["task"]["task_id"] = task_id
    comparison = _dump(
        [
            {"previous": a, "current": b}
            for a, b in zip(before["trajectories"], after["trajectories"], strict=True)
        ]
    )
    for _, record in events[start + 2 : start + 4]:
        record["prompt"] = (
            record["prompt"].split("COMPARISON: ", 1)[0]
            + "COMPARISON: "
            + comparison
            + "\n"
        )
    _rewrite(experiment, attempt, result, events)
    verified = verify_harness(experiment, "full")
    assert verified["status"] == "failed", verified
    assert "fixed 20-task sample" in verified["error"]


def test_verification_survives_run_directory_rename(tmp_path):
    experiment, _, _ = _fixture(tmp_path / "original")
    moved = tmp_path / "renamed"
    (tmp_path / "original").rename(moved)
    report = verify_harness(moved / "smoke/miniagent", "smoke")
    assert report["status"] == "passed"
