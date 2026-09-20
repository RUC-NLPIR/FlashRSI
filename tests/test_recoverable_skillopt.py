"""Reject completed invalid edits without changing the experiment's valid path."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_parallel_skillopt import FakeWorker, _algorithm, _reply
from test_parallel_skillopt import source as source

from flashrsi.agents import LLM
from flashrsi.algorithms.skillopt._patch import _Patch, _PatchError
from flashrsi.core import Trajectory
from scripts._experiment_runtime import CachedLLM
from scripts._parallel_skillopt import ParallelSkillOpt
from scripts._recoverable_skillopt import RecoverableSkillOpt


class Responses(FakeWorker):
    def __init__(self, replies):
        super().__init__()
        self.replies = iter(replies)

    async def _run(self, prompt, working_dir=None):
        self.requests.append(prompt)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return Trajectory(output=reply if isinstance(reply, str) else json.dumps(reply))


def _patch(*edits):
    return {"reasoning": "Offline proposed edits", "edits": list(edits)}


def _append():
    return {"path": "skills/main.md", "op": "append", "content": "SOLVED"}


def _missing():
    return {
        "path": "skills/main.md",
        "op": "replace",
        "target": "absent target",
        "content": "SOLVED",
    }


def _records(monkeypatch, algo):
    records = []
    monkeypatch.setattr(
        algo,
        "_record",
        lambda label, payload: records.append(
            (label, json.loads(json.dumps(payload, default=dict)))
        ),
    )
    return records


def _invalid(records, kind):
    matches = [
        payload
        for label, payload in records
        if label == "decision"
        and payload.get("reason") == "invalid_patch"
        and payload["kind"] == kind
    ]
    assert len(matches) == 1
    result = matches[0]
    assert result["accepted"] is False
    assert not {"score", "baseline_score", "candidate_id"} & result.keys()
    return result


@pytest.mark.parametrize("target", ["anchor", "absent target"])
def test_duplicate_or_missing_target_is_rejected_atomically(
    monkeypatch, source, target
):
    original_text = "anchor\nanchor\n"
    (source / "skills/main.md").write_text(original_text)
    proposed = _patch(
        {"path": "skills/new.md", "op": "append", "content": "must not be committed"},
        {
            "path": "skills/main.md",
            "op": "replace",
            "target": target,
            "content": "SOLVED",
        },
    )
    algo = _algorithm(RecoverableSkillOpt, source, Responses([proposed]))
    current = algo.target.snapshot
    records = _records(monkeypatch, algo)
    algo._rejected = [{"prior": index} for index in range(5)]
    result, best = asyncio.run(
        algo._fast_update(current, 0.625, algo.benchmark.train[:1], 2, 10)
    )
    assert result is current and best == 0.625
    assert algo.target.snapshot.id == current.id
    assert "skills/new.md" not in current.files
    assert (source / "skills/main.md").read_text() == original_text
    assert not (source / "skills/new.md").exists()
    assert [label for label, _ in records] == ["train", "success", "decision"]
    assert len(algo.target.calls) == 1
    invalid = _invalid(records, "fast")
    assert invalid["epoch"] == 2 and invalid["step"] == 10
    assert invalid["parent_id"] == current.id
    assert invalid["error"] == "edit target must occur exactly once in the skill"
    assert (
        invalid["patch"] == _Patch.parse(json.dumps(proposed), "success").as_mapping()
    )
    assert algo._rejected == [{"prior": index} for index in range(1, 5)] + [invalid]


def test_next_batch_continues_with_error_feedback_and_replays_worker_cache(
    monkeypatch, source, tmp_path
):
    native_calls = []

    async def run(self, prompt, working_dir=None):
        ordinal = self._experiment_worker_ordinal - 1
        native_calls.append((ordinal, prompt))
        reply = _patch(_missing()) if ordinal == 0 else _reply(prompt, ordinal)
        return Trajectory(output=json.dumps(reply))

    monkeypatch.setattr(LLM, "_run", run)

    def make():
        worker = CachedLLM({"llm": {"model_name": "offline"}}).configure_experiment(
            tmp_path / "cache"
        )
        return _algorithm(
            RecoverableSkillOpt,
            source,
            worker,
            num_epochs=1,
            batch_size=1,
            max_steps=2,
        )

    original = make()
    records = _records(monkeypatch, original)
    final = asyncio.run(original.evolve())
    invalid = _invalid(records, "fast")
    assert invalid["step"] == 1
    assert [ordinal for ordinal, _ in native_calls] == [0, 1]
    assert invalid["error"] in native_calls[1][1]
    assert '"reason": "invalid_patch"' in native_calls[1][1]
    assert [label for label, _ in records].count("candidate_dev") == 1
    assert len(original.target.calls) == 4  # baseline, two train, one valid candidate
    assert b"SOLVED" in final.files["skills/main.md"].content

    replay = make()
    replay_records = _records(monkeypatch, replay)
    assert asyncio.run(replay.evolve()) == final
    assert replay.target.calls == original.target.calls
    assert replay_records == records
    assert replay.worker._experiment_worker_ordinal == 2
    assert replay.worker._experiment_worker_hits == 2
    assert len(native_calls) == 2


@pytest.mark.parametrize("stage", ["reflection", "merge", "rank"])
def test_parallel_parser_errors_remain_terminal(monkeypatch, source, stage):
    replies = {
        "reflection": ["not JSON"],
        "merge": [_patch(_append()), _patch(_append()), "not JSON"],
        "rank": [
            _patch(_append()),
            _patch(_append()),
            _patch(_append(), _append()),
            {"selected_indices": [99]},
        ],
    }[stage]
    algo = _algorithm(RecoverableSkillOpt, source, Responses(replies), edit_budget=1)
    current = algo.target.snapshot
    records = _records(monkeypatch, algo)
    rejected = copy.deepcopy(algo._rejected)
    batch = algo.benchmark.train[: 1 if stage == "reflection" else 2]
    with pytest.raises(_PatchError):
        asyncio.run(algo._fast_update(current, 0, batch, 0, 1))
    assert algo.target.snapshot.id == current.id
    assert algo._rejected == rejected
    assert not any(label in {"decision", "candidate_dev"} for label, _ in records)


@pytest.mark.parametrize(
    "error", [RuntimeError("gateway failed"), OSError("disk failed")]
)
def test_non_patch_application_errors_propagate(monkeypatch, source, error):
    algo = _algorithm(RecoverableSkillOpt, source, Responses([_patch(_append())]))
    records = _records(monkeypatch, algo)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(_Patch, "apply", fail)
    with pytest.raises(type(error), match=str(error)):
        asyncio.run(
            algo._fast_update(algo.target.snapshot, 0, algo.benchmark.train[:1], 0, 1)
        )
    assert not any(label == "decision" for label, _ in records)


@pytest.mark.parametrize("stage", ["worker", "evaluation", "candidate", "selection"])
def test_execution_and_candidate_errors_are_not_converted_to_rejections(
    monkeypatch, source, stage
):
    replies = (
        [RuntimeError("gateway failed")] if stage == "worker" else [_patch(_append())]
    )
    algo = _algorithm(RecoverableSkillOpt, source, Responses(replies))
    records = _records(monkeypatch, algo)

    async def fail_async(*args, **kwargs):
        raise _PatchError("outside patch application")

    def fail(*args, **kwargs):
        raise _PatchError("outside patch application")

    if stage == "evaluation":
        monkeypatch.setattr(algo, "_evaluate", fail_async)
    elif stage == "candidate":
        monkeypatch.setattr(algo, "_candidate", fail)
    elif stage == "selection":
        monkeypatch.setattr(algo, "_select", fail_async)
    with pytest.raises(RuntimeError if stage == "worker" else _PatchError):
        asyncio.run(
            algo._fast_update(algo.target.snapshot, 0, algo.benchmark.train[:1], 0, 1)
        )
    assert not any(label == "decision" for label, _ in records)


def test_valid_complete_epochs_match_parallel_prompts_ordinals_rollouts_and_decisions(
    monkeypatch, source
):
    config = {
        "num_epochs": 2,
        "batch_size": 6,
        "reflection_minibatch_size": 2,
        "slow_update_samples": 4,
        "edit_budget": 2,
    }
    parallel = _algorithm(ParallelSkillOpt, source, **config)
    recoverable = _algorithm(RecoverableSkillOpt, source, **config)
    expected_records = _records(monkeypatch, parallel)
    actual_records = _records(monkeypatch, recoverable)
    assert asyncio.run(recoverable.evolve()) == asyncio.run(parallel.evolve())
    assert recoverable.worker.requests == parallel.worker.requests
    assert recoverable.target.calls == parallel.target.calls
    assert recoverable._rejected == parallel._rejected
    assert recoverable._meta_skill == parallel._meta_skill
    # Worker response completion ordering is intentionally independent of invocation.
    for records in (expected_records, actual_records):
        records.sort(key=lambda item: json.dumps(item, sort_keys=True))
    assert actual_records == expected_records


def test_invalid_meta_retains_old_value_and_valid_slow_is_selected_normally(
    monkeypatch, source
):
    malformed = {"meta_skill_content": 42}
    guidance = {"guidance": [{"path": "skills/main.md", "content": "SOLVED"}]}
    algo = _algorithm(
        RecoverableSkillOpt,
        source,
        Responses([malformed, guidance]),
        slow_update_samples=2,
    )
    records = _records(monkeypatch, algo)
    current, old_meta = algo.target.snapshot, algo._meta_skill
    result, best = asyncio.run(algo._slow_update(current, current, 0, 1))
    assert result.id != current.id and best == 1
    assert algo._meta_skill == old_meta
    invalid = _invalid(records, "meta")
    assert invalid["parent_id"] == current.id
    assert json.loads(invalid["response"]) == malformed
    assert "response" not in algo._rejected[-1]
    assert [prompt.splitlines()[0] for prompt in algo.worker.requests] == [
        "[SkillOpt: meta]",
        "[SkillOpt: slow]",
    ]
    decisions = [v for label, v in records if label == "decision"]
    assert decisions[-1]["kind"] == "slow" and decisions[-1]["accepted"] is True
    assert len(algo.target.calls) == 5  # two comparison pairs, one candidate dev


def test_invalid_slow_is_atomic_and_keeps_new_valid_meta(monkeypatch, source):
    malformed = {
        "guidance": [
            {"path": "skills/main.md", "content": "SOLVED"},
            {"path": "skills/missing.md", "content": "bad destination"},
        ]
    }
    algo = _algorithm(
        RecoverableSkillOpt,
        source,
        Responses([{"meta_skill_content": "Updated meta"}, malformed]),
        slow_update_samples=2,
    )
    records = _records(monkeypatch, algo)
    current = algo.target.snapshot
    result, best = asyncio.run(algo._slow_update(current, current, 0.5, 1))
    assert result is current and best == 0.5
    assert algo.target.snapshot.id == current.id
    assert algo._meta_skill == "Updated meta"
    assert b"SOLVED" not in current.files["skills/main.md"].content
    assert len(algo.target.calls) == 4
    assert not any(label == "candidate_dev" for label, _ in records)
    assert json.loads(_invalid(records, "slow")["response"]) == malformed


@pytest.mark.parametrize("meta_only", [False, True])
def test_disabled_stage_is_not_called_after_invalid_sequential_reply(
    monkeypatch, source, meta_only
):
    algo = _algorithm(
        RecoverableSkillOpt,
        source,
        Responses(["not JSON"]),
        use_meta_skill=meta_only,
        use_slow_update=not meta_only,
        slow_update_samples=2,
    )
    records = _records(monkeypatch, algo)
    current, old_meta = algo.target.snapshot, algo._meta_skill
    assert asyncio.run(algo._slow_update(current, current, 0.5, 1)) == (current, 0.5)
    assert algo._meta_skill == old_meta
    assert len(algo.worker.requests) == 1
    assert len(algo.target.calls) == 4
    _invalid(records, "meta" if meta_only else "slow")


@pytest.mark.parametrize("stage", ["meta", "slow"])
def test_sequential_worker_errors_propagate(monkeypatch, source, stage):
    algo = _algorithm(
        RecoverableSkillOpt,
        source,
        Responses([RuntimeError("gateway failed")]),
        use_meta_skill=stage == "meta",
        use_slow_update=stage == "slow",
        slow_update_samples=2,
    )
    records = _records(monkeypatch, algo)
    current = algo.target.snapshot
    with pytest.raises(RuntimeError, match="gateway failed"):
        asyncio.run(algo._slow_update(current, current, 0.5, 1))
    assert not any(label == "decision" for label, _ in records)


def test_valid_empty_meta_and_noop_slow_preserve_original_behavior(monkeypatch, source):
    algo = _algorithm(
        RecoverableSkillOpt,
        source,
        Responses([{"meta_skill_content": ""}, {"guidance": []}]),
        slow_update_samples=2,
    )
    records = _records(monkeypatch, algo)
    current = algo.target.snapshot
    assert asyncio.run(algo._slow_update(current, current, 0.5, 1)) == (current, 0.5)
    assert algo._meta_skill == ""
    assert [v for label, v in records if label == "decision"] == [
        {"epoch": 1, "kind": "slow", "reason": "no_change", "accepted": False}
    ]
    assert len(algo.target.calls) == 4


def test_metadata_contains_actual_recovery_source_and_preserves_parallel_fields(source):
    parallel = _algorithm(ParallelSkillOpt, source)
    algo = _algorithm(RecoverableSkillOpt, source, patch_recovery_sha256="not trusted")
    keys = {"invalid_patch_policy", "patch_recovery_sha256"}
    assert set(algo.config) - set(parallel.config) == keys
    assert {k: v for k, v in algo.config.items() if k not in keys} == dict(
        parallel.config
    )
    assert algo.config.invalid_patch_policy == "reject_without_score"
    assert (
        algo.config.patch_recovery_sha256
        == hashlib.sha256(
            (
                Path(__file__).parents[1] / "scripts/_recoverable_skillopt.py"
            ).read_bytes()
        ).hexdigest()
    )
    with pytest.raises(ValueError, match="invalid_patch_policy"):
        _algorithm(RecoverableSkillOpt, source, invalid_patch_policy="invent_score")
