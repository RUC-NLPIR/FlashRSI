"""Codex participates in the local launcher and shared container payload."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from flashrsi._launch import _plan
from flashrsi._startup import _role
from flashrsi.config import load_config
from flashrsi.integrations import _container_payload


def test_codex_target_and_worker_select_python_extra_without_native_prerequisites():
    config = load_config(
        overrides={
            "agent": {"name": "codex", "llm": {"model_name": "target"}},
            "algorithm": {
                "worker": {
                    "type": "agent",
                    "name": "codex",
                    "llm": {"model_name": "worker"},
                }
            },
        }
    )
    plan = _plan(config)
    assert plan["extras"] == ["all"]
    assert not any("Cargo" in item or "Rust" in item for item in plan["prerequisites"])
    assert any("Responses" in item for item in plan["prerequisites"])


def test_codex_worker_cannot_use_target_or_ambient_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    _role({"llm": {"api_key": "target-key"}}, "agent", "codex")
    with pytest.raises(ValueError, match="algorithm.worker.llm.api_key"):
        _role({"llm": {}}, "algorithm.worker", "codex")
    with pytest.raises(ValueError, match="native login"):
        _role({"llm": {"api_key": "key", "auth": "login"}}, "agent", "codex")


@pytest.mark.parametrize("explicit_source", [False, True])
def test_container_payload_keeps_source_provenance_without_mutating_config(
    tmp_path, monkeypatch, explicit_source
):
    class Adapter:
        snapshot = SimpleNamespace(save=lambda path: path.write_text("{}"))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_container_payload.shutil, "copytree", lambda *a, **kw: None)
    monkeypatch.setattr(_container_payload, "_dependencies", lambda agent: [])
    config = {"llm": {"model_name": "target", "api_key": "key"}}
    if explicit_source:
        config["source_dir"] = "source"
    before = copy.deepcopy(config)
    _container_payload._stage(tmp_path, Adapter(), config, "Task")
    request = json.loads((tmp_path / "request.json").read_text())
    staged = yaml.safe_load(request["config_yaml"])
    expected = Path("source") if explicit_source else Path(__file__).parent
    assert staged["source_dir"] == str(expected.resolve())
    assert config == before
