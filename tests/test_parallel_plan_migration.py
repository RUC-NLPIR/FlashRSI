import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from flashrsi._records import _config_record
from flashrsi.config import load_config
from scripts import run_searchqa_experiment as runner
from scripts import run_searchqa_parallel_experiment as parallel
from scripts._parallel_plan_migration import (
    PARALLEL_KEYS,
    adopt_serial_plan,
    atomic_json,
)


@pytest.fixture
def recipe(tmp_path):
    config = load_config(runner.ROOT / "examples/searchqa_deepseek/miniagent.yaml")
    config.run.output_dir = str(tmp_path / "attempts")
    data = {"fixed": "data-hash"}
    initial_id = "initial-snapshot"
    old = {
        "fingerprint": runner._fingerprint(config, data, initial_id),
        "config": _config_record(config),
        "initial_snapshot": initial_id,
        "profile": "full",
        "harness": "miniagent",
    }
    atomic_json(tmp_path / "plan.json", old)
    for key in PARALLEL_KEYS:
        config.algorithm[key] = 4 if key == "worker_concurrency" else "source-sha"
    return tmp_path, config, data, initial_id, old


def test_adoption_preserves_serial_evidence_before_plan_commit_and_replays(recipe):
    root, config, data, initial_id, old = recipe
    adopt = lambda: adopt_serial_plan(  # noqa: E731
        root, config, data, initial_id, runner._fingerprint
    )
    adopted = adopt()
    assert json.loads((root / "plan.json").read_text()) == old
    assert json.loads((root / "serial-plan.json").read_text()) == old
    evidence = (root / "parallel-migration.json").read_bytes()
    assert json.loads(evidence)["parallel_plan"] == adopted
    assert adopt() == adopted
    assert (root / "parallel-migration.json").read_bytes() == evidence
    assert adopted["fingerprint"] != old["fingerprint"]
    assert adopted["config"]["agent"] == old["config"]["agent"]
    assert (
        adopted["config"]["algorithm"]["worker"] == old["config"]["algorithm"]["worker"]
    )


@pytest.mark.parametrize("change", ["model", "data", "initial", "source", "extra"])
def test_rejects_other_recipe_changes_before_writing_evidence(recipe, change):
    root, config, data, initial_id, _ = recipe
    fingerprint = runner._fingerprint
    if change == "model":
        config.agent.llm.model_name = "changed-model"
    elif change == "data":
        data["fixed"] = "changed-data"
    elif change == "initial":
        initial_id = "changed-snapshot"
    elif change == "source":

        def fingerprint(*_):
            return "changed-source"
    else:
        config.algorithm.unapproved_change = True
    with pytest.raises(ValueError, match="changed"):
        adopt_serial_plan(root, config, data, initial_id, fingerprint)
    assert not (root / "serial-plan.json").exists()


@pytest.mark.parametrize("artifact", ["result.json", "serial-plan.json"])
def test_rejects_completed_run_or_conflicting_archive(recipe, artifact):
    root, config, data, initial_id, _ = recipe
    atomic_json(root / artifact, {"status": "finished"})
    with pytest.raises(ValueError, match="completed|archive"):
        adopt_serial_plan(root, config, data, initial_id, runner._fingerprint)


def test_atomic_shared_manifest_writes_do_not_race(tmp_path):
    path = tmp_path / "shared.json"
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: atomic_json(path, {"id": i}), range(30)))
    assert json.loads(path.read_text())["id"] in range(30)
    assert not list(tmp_path.glob("*.tmp"))


def test_wrapper_adopts_under_existing_lock_and_restores_runner(recipe, monkeypatch):
    root, config, data, initial_id, old = recipe
    saved_config = copy.deepcopy(config)
    original = (runner.SkillOpt, runner._fingerprint, runner._write_json)

    def fake_main():
        with runner._exclusive(root / "process.lock"):
            first = runner._fingerprint(config, data, initial_id)
            second = runner._fingerprint(config, data, initial_id)
        assert first == second
        assert json.loads((root / "plan.json").read_text())["fingerprint"] == first
        assert json.loads((root / "serial-plan.json").read_text()) == old
        return 0

    monkeypatch.setattr(runner, "main", fake_main)
    monkeypatch.setattr(parallel.sys, "argv", ["parallel", "--adopt-serial-plan"])
    assert parallel.main() == 0
    assert (runner.SkillOpt, runner._fingerprint, runner._write_json) == original
    assert config == saved_config
