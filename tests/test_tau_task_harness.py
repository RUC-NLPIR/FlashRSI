"""The bounded tau process restores its caller's importable harness version."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from flashrsi.agents import ClaudeCode, Codex, MiniAgent
from flashrsi.core import Snapshot
from flashrsi.integrations import _container


@pytest.mark.parametrize("agent_type", [MiniAgent, ClaudeCode, Codex])
def test_bounded_tau_restores_selected_harness_without_a_name_whitelist(
    agent_type, tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "components.yaml").write_text("prompt: [instructions.md]\n")
    (source / "instructions.md").write_text("seed")
    config = {
        "name": agent_type.name,
        "source_dir": str(source),
        "llm": {"model_name": "destination-model", "api_key": "test-key"},
    }
    seed = agent_type(config).snapshot
    with seed.check_out() as files:
        (files / "instructions.md").write_text("evolved harness")
        selected = seed.commit(files)
    snapshot_path = tmp_path / "selected.json"
    selected.save(snapshot_path)
    captured = []

    def simulate(agent, task, domain, simulator, role_config, evidence, judge):
        captured.append(agent)
        assert type(agent) is agent_type
        assert agent.snapshot.id == selected.id
        assert agent.snapshot.files == selected.files
        assert agent.config.llm.model_name == "destination-model"
        assert task.metadata == {"domain": "retail"}
        assert domain == tmp_path
        assert simulator == {"model_name": "independent-user"}
        return "native simulation fixture"

    # Import only the private subprocess entry: tau's installed orchestrator and
    # remote models are intentionally absent from this dispatch contract test.
    simulation = ModuleType("flashrsi.integrations.tau2")
    simulation._simulate = simulate
    simulation._simulation_result = lambda run, evidence: {"reward": 1}
    monkeypatch.setitem(sys.modules, simulation.__name__, simulation)
    entry_path = Path(_container.__file__).with_name("_tau2_task.py")
    spec = importlib.util.spec_from_file_location(
        "tau_task_dispatch_fixture", entry_path
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "agent_class": f"{agent_type.__module__}:{agent_type.__qualname__}",
                "config": config,
                "snapshot": str(snapshot_path),
                "domain": str(tmp_path),
                "task_id": "retail-task",
                "metadata": {"domain": "retail"},
                "simulator": {"model_name": "independent-user"},
            }
        )
    )
    response = tmp_path / "response.json"
    entry.main(request, response)
    assert len(captured) == 1
    assert json.loads(response.read_text()) == {"reward": 1}
    assert Snapshot.load(snapshot_path).id == selected.id
    assert (source / "instructions.md").read_text() == "seed"
