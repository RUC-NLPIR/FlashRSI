import json

import pytest

from flashrsi._records import _config_record
from flashrsi.config import load_config
from scripts import run_searchqa_experiment as runner
from scripts._parallel_plan_migration import atomic_json
from scripts.run_searchqa_recoverable_experiment import ADDED_KEYS, adopt_patch_recovery


@pytest.fixture
def migration(tmp_path):
    config = load_config(runner.ROOT / "examples/searchqa_deepseek/miniagent.yaml")
    config.run.output_dir = str(tmp_path / "attempts")
    config.algorithm.worker_concurrency = 4
    config.algorithm.parallel_skillopt_sha256 = "former-source"
    data = {"data": "frozen"}
    initial = "frozen-initial"
    old = {
        "fingerprint": runner._fingerprint(config, data, initial),
        "config": _config_record(config),
        "initial_snapshot": initial,
    }
    atomic_json(tmp_path / "plan.json", old)
    for key in ADDED_KEYS:
        config.algorithm[key] = "new-policy-or-source"
    return tmp_path, config, data, initial, old


def test_upgrade_preserves_former_plan_and_same_role_configs(migration):
    root, config, data, initial, old = migration
    value = adopt_patch_recovery(root, config, data, initial, runner._fingerprint)
    upgraded = json.loads((root / "plan.json").read_text())
    assert value == upgraded["fingerprint"] != old["fingerprint"]
    assert json.loads((root / "pre-patch-recovery-plan.json").read_text()) == old
    audit = (root / "patch-recovery-migration.json").read_bytes()
    assert upgraded["config"]["agent"] == old["config"]["agent"]
    assert (
        upgraded["config"]["algorithm"]["worker"]
        == old["config"]["algorithm"]["worker"]
    )
    # Replay after an interruption between audit publication and plan publication.
    atomic_json(root / "plan.json", old)
    assert (
        adopt_patch_recovery(root, config, data, initial, runner._fingerprint) == value
    )
    assert (root / "patch-recovery-migration.json").read_bytes() == audit


@pytest.mark.parametrize("change", ["model", "data", "source", "completed"])
def test_upgrade_rejects_any_other_change(migration, change):
    root, config, data, initial, _ = migration
    if change == "model":
        config.agent.llm.model_name = "different"
    elif change == "data":
        data["data"] = "different"
    elif change == "source":
        config.algorithm.parallel_skillopt_sha256 = "different"
    else:
        atomic_json(root / "result.json", {"status": "finished"})
    with pytest.raises(ValueError):
        adopt_patch_recovery(root, config, data, initial, runner._fingerprint)
    assert not (root / "pre-patch-recovery-plan.json").exists()
