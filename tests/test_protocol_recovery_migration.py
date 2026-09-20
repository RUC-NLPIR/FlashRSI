import json

import pytest

from flashrsi._records import _config_record
from flashrsi.config import load_config
from scripts import run_searchqa_experiment as runner
from scripts._parallel_plan_migration import atomic_json
from scripts.run_searchqa_protocol_experiment import ADDED_KEYS, adopt_protocol_recovery


@pytest.fixture
def migration(tmp_path):
    config = load_config(runner.ROOT / "examples/searchqa_deepseek/miniagent.yaml")
    config.run.output_dir = str(tmp_path / "attempts")
    config.algorithm.patch_recovery_sha256 = "unchanged"
    data, initial = {"frozen": True}, "seed"
    old = {
        "fingerprint": runner._fingerprint(config, data, initial),
        "config": _config_record(config),
        "initial_snapshot": initial,
    }
    atomic_json(tmp_path / "plan.json", old)
    for key in ADDED_KEYS:
        config.algorithm[key] = "added"
    return tmp_path, config, data, initial, old


def test_migration_preserves_previous_config_and_supports_interrupted_publication(
    migration,
):
    root, config, data, initial, old = migration
    value = adopt_protocol_recovery(root, config, data, initial, runner._fingerprint)
    new = json.loads((root / "plan.json").read_text())
    assert new["fingerprint"] == value != old["fingerprint"]
    assert new["config"]["agent"] == old["config"]["agent"]
    assert new["config"]["algorithm"]["worker"] == old["config"]["algorithm"]["worker"]
    assert json.loads((root / "pre-protocol-recovery-plan.json").read_text()) == old
    audit = (root / "protocol-recovery-migration.json").read_bytes()
    atomic_json(root / "plan.json", old)
    assert (
        adopt_protocol_recovery(root, config, data, initial, runner._fingerprint)
        == value
    )
    assert (root / "protocol-recovery-migration.json").read_bytes() == audit


@pytest.mark.parametrize("change", ["model", "data", "source", "initial", "completed"])
def test_rejects_other_changes(migration, change):
    root, config, data, initial, _ = migration
    if change == "model":
        config.agent.llm.model_name = "changed"
    elif change == "data":
        data["frozen"] = False
    elif change == "source":
        config.algorithm.patch_recovery_sha256 = "changed"
    elif change == "initial":
        initial = "changed"
    else:
        atomic_json(root / "result.json", {"status": "finished"})
    with pytest.raises(ValueError):
        adopt_protocol_recovery(root, config, data, initial, runner._fingerprint)
    assert not (root / "pre-protocol-recovery-plan.json").exists()
