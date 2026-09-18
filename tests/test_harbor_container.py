"""Exercise the container boundary without a model or container daemon."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.core import Trajectory
from flashrsi.integrations import _container


@pytest.mark.parametrize("adapter", [ClaudeCode, MiniAgent])
def test_resolves_importable_agent_classes(adapter):
    import_path = f"{adapter.__module__}:{adapter.__qualname__}"
    assert _container._agent_class(import_path) is adapter


@pytest.mark.parametrize(
    "import_path",
    [
        None,
        "",
        "flashrsi.agents",
        "flashrsi.agents:ClaudeCode:extra",
        "../flashrsi.agents:ClaudeCode",
        "flashrsi.agents:Outer.<locals>.Inner",
        "__main__:ClaudeCode",
        "flashrsi.missing_agent:Agent",
        "flashrsi.agents:MissingAgent",
        "flashrsi.core:Agent",
        "flashrsi.core:Trajectory",
        "flashrsi.integrations._container:_run",
    ],
)
def test_rejects_invalid_or_non_agent_entrypoints(import_path):
    with pytest.raises(ValueError, match="agent_class"):
        _container._agent_class(import_path)


@pytest.fixture(params=[ClaudeCode, MiniAgent], ids=["claude_code", "miniagent"])
def container_request(request, tmp_path):
    adapter = request.param
    agent = adapter({"llm": {"model_name": "local-model"}})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        skill = directory / "skills/container-check/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: container-check\n---\nCANDIDATE_CONTENT\n")
        candidate = baseline.commit(directory)
    snapshot_path = tmp_path / "snapshot.json"
    candidate.save(snapshot_path)
    payload = {
        "agent_class": f"{adapter.__module__}:{adapter.__qualname__}",
        "config_yaml": yaml.safe_dump(
            {
                "name": adapter.name,
                "source_dir": "/host-only/source",
                "llm": {"model_name": "local-model", "api_key": "config-private-key"},
                "timeout": 27,
                "max_turns": 3,
                "permission_mode": "acceptEdits",
                "allowed_tools": ["Read", "Write"],
                "tools": ["Read", "Write", "Skill"],
                "custom": {"retained": True},
            }
        ),
        "snapshot_path": str(snapshot_path),
        "prompt": "Apply the container-check skill",
    }
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "output.json"

    def write():
        request_path.write_text(json.dumps(payload))

    write()
    return payload, write, request_path, output_path, candidate, adapter


def test_restores_candidate_and_preserves_execution_config_and_events(
    container_request, monkeypatch, tmp_path
):
    payload, _, request_path, output_path, candidate, adapter = container_request
    # The bridge must leave the environment untouched.
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")
    monkeypatch.chdir(tmp_path)
    seen = {}

    async def run(self, prompt, working_dir=None):
        assert not request_path.exists()
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "host-token"
        seen["config"] = dict(self.config)
        seen["snapshot"] = self.snapshot
        seen["files_dir"] = self.files_dir
        assert self.snapshot.id == candidate.id
        assert self.snapshot.root_id == candidate.root_id
        assert self.snapshot.parent_id == candidate.parent_id
        assert working_dir == Path.cwd()
        skill = self.files_dir / "skills/container-check/SKILL.md"
        assert "CANDIDATE_CONTENT" in skill.read_text()
        return Trajectory(
            output="answer config-private-key",
            messages=(
                {"type": "RunInput", "snapshot_id": self.snapshot.id, "prompt": prompt},
                {
                    "type": "AssistantMessage",
                    "parent_tool_use_id": "child-1",
                    "content": [{"type": "TextBlock", "text": "child result"}],
                },
                {"type": "ResultMessage", "result": "host-token"},
            ),
            usage={
                "model_usage": {"local-model": {"inputTokens": 14}},
                "num_turns": 2,
            },
        )

    monkeypatch.setattr(adapter, "_run", run)
    if adapter is MiniAgent:

        def unexpected_claude(*args, **kwargs):
            raise AssertionError("MiniAgent must not instantiate Claude Code")

        monkeypatch.setattr(ClaudeCode, "__init__", unexpected_claude)
    assert asyncio.run(_container._run(request_path, output_path)) == 0
    result = json.loads(output_path.read_text())
    assert result["task"] is None
    assert result["status"] == "finished"
    assert result["output"] == "answer [REDACTED]"
    assert result["messages"][0]["type"] == "RunConfig"
    assert result["messages"][0]["snapshot_id"] == candidate.id
    assert result["messages"][0]["config"]["llm"]["api_key"] is None
    assert result["messages"][1]["snapshot_id"] == candidate.id
    assert result["messages"][2]["parent_tool_use_id"] == "child-1"
    assert result["messages"][3]["result"] == "[REDACTED]"
    assert result["usage"] == {
        "model_usage": {"local-model": {"inputTokens": 14}},
        "num_turns": 2,
    }
    expected = {
        key: value
        for key, value in yaml.safe_load(payload["config_yaml"]).items()
        if key != "source_dir"
    }
    assert seen["config"] == expected
    assert not seen["files_dir"].exists()


@pytest.mark.parametrize("field", ["name", "agent_class", "snapshot"])
def test_rejects_unknown_adapter_or_mismatched_config_and_snapshot(
    container_request, monkeypatch, field
):
    payload, write, request_path, output_path, _, adapter = container_request
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")
    config = yaml.safe_load(payload["config_yaml"])
    other_adapter = MiniAgent if adapter is ClaudeCode else ClaudeCode
    if field == "name":
        config["name"] = other_adapter.name
    elif field == "agent_class":
        payload["agent_class"] = "flashrsi.agents:MissingAgent"
    else:
        snapshot_path = request_path.with_name("other.json")
        other_adapter({"llm": {"model_name": "unused"}}).snapshot.save(snapshot_path)
        payload["snapshot_path"] = str(snapshot_path)
    payload["config_yaml"] = yaml.safe_dump(config)
    write()

    def unexpected_init(*args, **kwargs):
        raise AssertionError("unsupported request must not start the adapter")

    monkeypatch.setattr(adapter, "__init__", unexpected_init)
    assert asyncio.run(_container._run(request_path, output_path)) == 1
    result = json.loads(output_path.read_text())
    assert result["status"] == "error"
    assert "not start the adapter" not in result["error_message"]
    assert field.replace("snapshot", "Snapshot") in result["error_message"]
    assert not request_path.exists()
    assert "config-private-key" not in output_path.read_text()


def test_adapter_owns_container_validation_and_cli_config(
    container_request, monkeypatch
):
    payload, write, request_path, output_path, _, adapter = container_request
    config = yaml.safe_load(payload["config_yaml"])
    config.pop("name")  # The importable class identifies the adapter on its own.
    config["cli_path"] = "/agent-specific/cli"
    payload["config_yaml"] = yaml.safe_dump(config)
    write()
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")
    checks = []

    def check(self):
        assert "source_dir" not in self.config
        assert self.config["cli_path"] == "/agent-specific/cli"
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "host-token"
        checks.append(self)

    async def run(self, prompt, working_dir=None):
        assert checks == [self]
        return Trajectory(output="validated")

    monkeypatch.setattr(adapter, "_check_container", check)
    monkeypatch.setattr(adapter, "_run", run)
    assert asyncio.run(_container._run(request_path, output_path)) == 0
    result = json.loads(output_path.read_text())
    assert result["output"] == "validated"
    assert result["messages"][0]["config"]["cli_path"] == "/agent-specific/cli"


def test_backend_exception_is_recorded_and_redacted(container_request, monkeypatch):
    _, _, request_path, output_path, candidate, adapter = container_request
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")

    async def run(self, prompt, working_dir=None):
        raise RuntimeError("failure config-private-key host-token")

    monkeypatch.setattr(adapter, "_run", run)
    assert asyncio.run(_container._run(request_path, output_path)) == 1
    result = json.loads(output_path.read_text())
    assert result["error_message"] == "failure [REDACTED] [REDACTED]"
    assert result["messages"][0]["snapshot_id"] == candidate.id
    assert not request_path.exists()


def test_cancellation_is_not_reported_as_an_ordinary_error(
    container_request, monkeypatch
):
    _, _, request_path, output_path, _, adapter = container_request
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")

    async def run(self, prompt, working_dir=None):
        raise asyncio.CancelledError()

    monkeypatch.setattr(adapter, "_run", run)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_container._run(request_path, output_path))
    assert not request_path.exists()
    assert not output_path.exists()


def test_yaml_config_values_keep_their_types(container_request, monkeypatch):
    payload, write, request_path, output_path, _, adapter = container_request
    config = yaml.safe_load(payload["config_yaml"])
    config["custom"] = {"date": date(2026, 9, 17), "choices": {"one", "two"}}
    payload["config_yaml"] = yaml.safe_dump(config)
    write()
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")

    async def run(self, prompt, working_dir=None):
        assert self.config["custom"]["date"] == date(2026, 9, 17)
        assert self.config["custom"]["choices"] == {"one", "two"}
        return Trajectory(output="preserved")

    monkeypatch.setattr(adapter, "_run", run)
    assert asyncio.run(_container._run(request_path, output_path)) == 0
    result = json.loads(output_path.read_text())
    assert result["output"] == "preserved"
    assert result["messages"][0]["config"]["custom"]["date"]["type"] == "yaml"


def test_malformed_yaml_does_not_echo_credential_text(container_request):
    payload, write, request_path, output_path, _, _ = container_request
    payload["config_yaml"] = "llm: [api_key: private-malformed-secret"
    write()
    assert asyncio.run(_container._run(request_path, output_path)) == 1
    assert "private-malformed-secret" not in output_path.read_text()
    assert "Invalid container config YAML" in output_path.read_text()


def test_module_entrypoint_removes_malformed_request_and_writes_error(tmp_path):
    request_path, output_path = tmp_path / "request.json", tmp_path / "output.json"
    request_path.write_text('{"config_yaml":')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flashrsi.integrations._container",
            str(request_path),
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert not result.stderr
    assert not request_path.exists()
    assert json.loads(output_path.read_text())["status"] == "error"
