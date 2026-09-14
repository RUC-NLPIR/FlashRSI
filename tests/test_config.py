from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
import yaml

import flashrsi.config as config_module
from flashrsi.config import Config, load_config, prepare_run_dir


@pytest.fixture
def settings():
    return {
        "agent": {"model_name": "target-model"},
        "algorithm": {"worker": {"model_name": "worker-model"}},
    }


def test_defaults_and_nested_overrides_do_not_mutate_inputs(tmp_path, settings):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings))
    overrides = {
        "benchmark": {"split": {"train": 0.5, "dev": 0.25, "test": 0.25}},
        "algorithm": {"worker": {"base_url": "https://example.test/v1"}},
    }
    before = deepcopy(overrides)

    config = load_config(path, overrides=overrides)

    assert set(config) == {"run", "benchmark", "agent", "algorithm"}
    assert config["agent"]["name"] == "miniagent"
    assert config["algorithm"]["worker"]["model_name"] == "worker-model"
    assert config["algorithm"]["worker"]["type"] == "llm"
    assert "name" not in config["algorithm"]["worker"]
    assert config["benchmark"]["split"] == {"train": 0.5, "dev": 0.25, "test": 0.25}
    assert overrides == before
    assert yaml.safe_load(path.read_text()) == settings
    config["benchmark"]["split"]["train"] = 0.9
    assert overrides == before
    assert load_config(path)["benchmark"]["split"]["train"] == 0.6


def test_paths_use_the_directory_of_their_source(tmp_path, monkeypatch, settings):
    yaml_dir = tmp_path / "yaml"
    shell_dir = tmp_path / "shell"
    yaml_dir.mkdir()
    shell_dir.mkdir()
    path = yaml_dir / "config.yaml"
    path.write_text(yaml.safe_dump({**settings, "run": {"output_dir": "./yaml-runs"}}))
    monkeypatch.chdir(shell_dir)

    inherited = load_config(path, overrides={"agent": {"model_name": "new-model"}})
    overridden = load_config(path, overrides={"run": {"output_dir": "./cli-runs"}})

    assert inherited["run"]["output_dir"] == str(yaml_dir / "yaml-runs")
    assert overridden["run"]["output_dir"] == str(shell_dir / "cli-runs")
    assert not (shell_dir / "cli-runs").exists()
    assert not (yaml_dir / "yaml-runs").exists()


def test_config_without_yaml_accepts_custom_backend_and_model_names(
    tmp_path, monkeypatch, settings
):
    monkeypatch.chdir(tmp_path)
    settings["agent"].update(name="custom-agent", model_name="provider/model")
    settings["run"] = {"output_dir": Path("output")}

    config = load_config(overrides=settings)

    assert config["agent"]["name"] == "custom-agent"
    assert config["agent"]["model_name"] == "provider/model"
    assert config["run"]["output_dir"] == str(tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"worker": {}}, "Unknown keys in configuration: worker"),
        ({"run": {"output_dir": None}}, "run.output_dir"),
        ({"agent": {"model_name": " "}}, "agent.model_name"),
        ({"agent": {"api_key": 123}}, "agent.api_key"),
        ({"agent": {"name": "../escape"}}, "agent.name"),
        ({"algorithm": {"name": "bad/name"}}, "algorithm.name"),
        ({"benchmark": {"name": "bad\nname"}}, "benchmark.name"),
        (
            {"algorithm": {"worker": {"model_name": None}}},
            "algorithm.worker.model_name",
        ),
        ({"algorithm": {"worker": {"base_url": []}}}, "algorithm.worker.base_url"),
        ({"algorithm": {"worker": {"type": "other"}}}, "algorithm.worker.type"),
        ({"algorithm": {"worker": {"type": []}}}, "algorithm.worker.type"),
        ({"algorithm": {"worker": {"name": "miniagent"}}}, "requires type: agent"),
        ({"algorithm": {"worker": []}}, "algorithm.worker must be a mapping"),
        ({"benchmark": []}, "benchmark must be a mapping"),
        ({"benchmark": {"split": []}}, "benchmark.split must be a mapping"),
        (
            {"benchmark": {"split": {"val": 0.2}}},
            "Unknown keys in benchmark.split: val",
        ),
        ({"benchmark": {"split": {"train": 0.8}}}, "ratios must sum to 1"),
    ],
)
def test_invalid_config_has_actionable_errors(tmp_path, settings, override, message):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError, match=message):
        load_config(path, overrides=override)


@pytest.mark.parametrize("ratio", [True, -0.1, 1.1, float("nan"), float("inf"), "0.6"])
def test_invalid_split_ratios_are_rejected(settings, ratio):
    settings["benchmark"] = {"split": {"train": ratio}}
    with pytest.raises(ValueError, match="benchmark.split.train"):
        load_config(overrides=settings)


@pytest.mark.parametrize("ratios", [(0.1, 0.2, 0.7), (1, 0, 0)])
def test_split_allows_float_rounding_and_zero(settings, ratios):
    split = dict(zip(("train", "dev", "test"), ratios))
    settings["benchmark"] = {"split": split}
    assert load_config(overrides=settings)["benchmark"]["split"] == split


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "agent:\n  model_name: one\n  model_name: two\n",
            "Duplicate configuration key: model_name",
        ),
        ("- item\n", "Configuration must be a mapping"),
        ("agent: [\n", "Invalid YAML"),
        ("1: value\n", "Configuration keys must be strings"),
    ],
)
def test_invalid_yaml_is_rejected(tmp_path, content, message):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_models_must_be_explicit():
    with pytest.raises(ValueError, match="agent.model_name"):
        load_config()
    with pytest.raises(ValueError, match="algorithm.worker.model_name"):
        load_config(overrides={"agent": {"model_name": "target-model"}})


def test_agent_worker_requires_a_name_and_can_be_switched_to_llm(tmp_path, settings):
    settings["algorithm"]["worker"]["type"] = "agent"
    with pytest.raises(ValueError, match="algorithm.worker.name"):
        load_config(overrides=settings)

    settings["algorithm"]["worker"]["name"] = "claude_code"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings))
    config = load_config(path)
    assert config["algorithm"]["worker"]["name"] == "claude_code"

    config = load_config(
        path, overrides={"algorithm": {"worker": {"type": "llm", "name": None}}}
    )
    assert config["algorithm"]["worker"]["type"] == "llm"


def test_run_names_and_timestamp_collisions_preserve_existing_results(
    tmp_path, monkeypatch, settings
):
    class FixedClock:
        @staticmethod
        def now():
            return datetime(2026, 9, 14, 16, 30, 0, 123456)

    monkeypatch.setattr(config_module, "datetime", FixedClock)
    monkeypatch.chdir(tmp_path)
    settings["algorithm"]["name"] = "custom_algo"
    settings["agent"]["name"] = "claude_code"
    settings["benchmark"] = {"name": "terminal-bench"}
    config = load_config(overrides=settings)
    before = deepcopy(config)

    first = prepare_run_dir(config)
    result = first / "trajectories" / "existing.json"
    result.write_text('{"score": 1}')
    second = prepare_run_dir(config)

    prefix = "custom_algo-claude_code-terminal-bench-20260914-163000-"
    assert first.name == prefix + "123456"
    assert second.name == prefix + "123457"
    assert first.parent == second.parent == tmp_path / "runs"
    assert result.read_text() == '{"score": 1}'
    assert {p.name for p in second.iterdir()} == {
        "config.yaml",
        "snapshots",
        "trajectories",
        "working",
    }
    assert load_config(first / "config.yaml") == config
    assert load_config(second / "config.yaml") == config
    assert config == before


def test_saved_config_omits_keys_but_runtime_config_keeps_them(tmp_path, settings):
    settings["run"] = {"output_dir": str(tmp_path)}
    settings["agent"].update(
        api_key="test-target-secret", base_url="https://example.test/v1"
    )
    settings["algorithm"]["worker"]["api_key"] = "test-worker-secret"
    config = load_config(overrides=settings)
    before = deepcopy(config)

    run_dir = prepare_run_dir(config)
    content = (run_dir / "config.yaml").read_text()
    saved = load_config(run_dir / "config.yaml")

    assert "test-target-secret" not in content
    assert "test-worker-secret" not in content
    expected = deepcopy(config)
    expected["agent"]["api_key"] = None
    expected["algorithm"]["worker"]["api_key"] = None
    assert saved == expected
    assert config == before
    assert settings["agent"]["api_key"] == "test-target-secret"


def test_failed_write_cleans_only_the_new_run(tmp_path, monkeypatch, settings):
    monkeypatch.chdir(tmp_path)
    config = load_config(overrides=settings)
    previous = prepare_run_dir(config)

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(OSError, match="disk full"):
        prepare_run_dir(config)
    assert list((tmp_path / "runs").iterdir()) == [previous]
    assert (previous / "config.yaml").is_file()


def test_repository_example_loads_without_extra_fields():
    path = Path(__file__).parents[1] / "example.yaml"
    expected = yaml.safe_load(path.read_text())
    expected["run"]["output_dir"] = str(path.parent / "runs")
    assert load_config(path) == expected


def test_extra_parameters_support_dot_access_overrides_and_save_reload(
    tmp_path, settings
):
    settings["run"] = {"output_dir": str(tmp_path / "runs"), "seed": 42}
    settings["benchmark"] = {"limit": 10, "filters": {"language": "en"}}
    settings["agent"]["tools"] = [{"name": "search", "timeout": 30}]
    settings["algorithm"]["rounds"] = 3
    settings["algorithm"]["worker"]["sampling"] = {"temperature": 0.7, "top_p": 0.9}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings))

    config = load_config(
        path,
        overrides={"algorithm": {"worker": {"sampling": {"temperature": 0.2}}}},
    )

    assert isinstance(config, Config)
    assert config.benchmark.name == "searchqa"
    assert config.run.seed == 42
    assert config.benchmark.limit == 10
    assert config.benchmark.filters.language == "en"
    assert config.agent.tools[0].name == "search"
    assert config.algorithm.rounds == 3
    assert config.algorithm.worker.sampling.temperature == 0.2
    assert config.algorithm.worker.sampling.top_p == 0.9
    assert config["benchmark"]["limit"] == config.benchmark.limit
    run_dir = prepare_run_dir(config)
    reloaded = load_config(run_dir / "config.yaml")
    assert reloaded == config
    assert reloaded.agent.tools[0].timeout == 30
    assert reloaded.algorithm.worker.sampling.temperature == 0.2
    assert yaml.safe_load(path.read_text()) == settings


def test_config_assignment_mapping_methods_and_missing_attributes():
    source = {"nested": {"value": 1}}
    config = Config(source)
    config.nested.value = 2
    config.extra = {"steps": [{"enabled": True}]}
    config.update({"more": {"count": 3}})
    config["items"] = {"value": 4}

    assert source == {"nested": {"value": 1}}
    assert config["nested"]["value"] == 2
    assert config.extra.steps[0].enabled is True
    assert config.more.count == 3
    assert config["items"].value == 4
    assert dict(config.items())["nested"] is config.nested
    assert config.get("missing", 5) == 5
    assert not hasattr(config, "missing")
    with pytest.raises(AttributeError, match="missing"):
        _ = config.missing
    with pytest.raises(KeyError, match="missing"):
        _ = config["missing"]

    cloned = deepcopy(config)
    cloned.extra.steps[0].enabled = False
    assert config.extra.steps[0].enabled is True
    del config.more
    assert "more" not in config
