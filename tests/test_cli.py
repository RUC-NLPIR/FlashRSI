import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from flashrsi.cli import main
from flashrsi.config import load_config


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "experiment.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "run": {"output_dir": "runs"},
                "benchmark": {"limit": 10},
                "agent": {"model_name": "yaml-target", "api_key": "test-target-secret"},
                "algorithm": {
                    "worker": {
                        "model_name": "yaml-worker",
                        "api_key": "test-worker-secret",
                    }
                },
            }
        )
    )
    return path


def test_prepare_from_yaml_creates_named_directory_and_redacted_config(
    config_path, capsys
):
    assert main(["run", "--config", str(config_path), "--prepare-only"]) == 0
    runs = list((config_path.parent / "runs").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    assert run_dir.name.startswith("skillopt-miniagent-searchqa-")
    assert (run_dir / "snapshots").is_dir()
    config = load_config(run_dir / "config.yaml")
    assert config.agent.model_name == "yaml-target"
    assert config.benchmark.limit == 10
    assert config.benchmark.split == "auto"
    assert config.agent.api_key is None
    assert config.algorithm.worker.api_key is None
    output = capsys.readouterr()
    assert str(run_dir) in output.out
    assert "Preparation only" in output.out
    assert "test-target-secret" not in output.out + output.err
    assert "test-worker-secret" not in output.out + output.err


def test_cli_auto_overrides_explicit_yaml_split_and_is_saved(config_path):
    values = yaml.safe_load(config_path.read_text())
    values["benchmark"]["split"] = {"train": 0.6, "dev": 0.2, "test": 0.2}
    config_path.write_text(yaml.safe_dump(values))
    assert (
        main(
            [
                "run",
                "--config",
                str(config_path),
                "--prepare-only",
                "--benchmark.split",
                "auto",
            ]
        )
        == 0
    )
    (run_dir,) = (config_path.parent / "runs").iterdir()
    assert load_config(run_dir / "config.yaml").benchmark.split == "auto"


def test_flags_and_typed_settings_override_yaml_and_resolve_paths_from_cwd(
    config_path, tmp_path, monkeypatch
):
    shell_dir = tmp_path / "shell"
    shell_dir.mkdir()
    monkeypatch.chdir(shell_dir)
    assert (
        main(
            [
                "run",
                "--config",
                str(config_path),
                "--prepare-only",
                "--set",
                "agent.model_name=set-model",
                "--model",
                "flag-model",
                "--worker-model",
                "flag-worker",
                "--agent",
                "claude_code",
                "--algorithm",
                "custom_algo",
                "--benchmark",
                "custom_bench",
                "--output-dir",
                "flag-runs",
                "--set",
                "run.output_dir=final-runs",
                "--set",
                "algorithm.rounds=2",
                "--set",
                "algorithm.rounds=3",
                "--set",
                "agent.enabled=true",
                "--set",
                "agent.base_url=null",
                "--set",
                "agent.tools=[{name: search, timeout: 30}]",
                "--set",
                "benchmark.filters={language: en}",
                "--set",
                "agent.endpoint=https://example.test/?a=b=c",
            ]
        )
        == 0
    )

    (run_dir,) = (shell_dir / "final-runs").iterdir()
    assert run_dir.name.startswith("custom_algo-claude_code-custom_bench-")
    config = load_config(run_dir / "config.yaml")
    assert config.agent.model_name == "set-model"
    assert config.algorithm.worker.model_name == "flag-worker"
    assert config.algorithm.rounds == 3
    assert config.agent.enabled is True
    assert config.agent.base_url is None
    assert config.agent.tools[0].timeout == 30
    assert config.benchmark.filters.language == "en"
    assert config.benchmark.limit == 10
    assert config.agent.endpoint == "https://example.test/?a=b=c"
    assert not (shell_dir / "flag-runs").exists()
    assert not (tmp_path / "runs").exists()


def test_run_without_execution_support_fails_without_creating_directories(
    config_path, capsys
):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(config_path)])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "not implemented yet" in output.err
    assert "--prepare-only" in output.err
    assert "test-target-secret" not in output.err
    assert not (config_path.parent / "runs").exists()


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (["algorithm.rounds"], "PATH=VALUE"),
        (["=value"], "non-empty dot-separated keys"),
        (["agent..model_name=value"], "non-empty dot-separated keys"),
        (["agent.extra=1", "agent.extra.nested=2"], "agent.extra is not a mapping"),
        (["agent.api_key=[test-secret"], "Invalid YAML value for --set agent.api_key"),
        (["agent.extra={key: 1, key: 2}"], "Invalid YAML value for --set agent.extra"),
        (["benchmark.split.train=0.9"], "ratios must sum to 1"),
    ],
)
def test_bad_settings_fail_without_writes_or_value_leaks(
    config_path, settings, message, capsys
):
    args = ["run", "--config", str(config_path), "--prepare-only"]
    for setting in settings:
        args.extend(["--set", setting])
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert message in output.err
    assert "Traceback" not in output.err
    assert "test-secret" not in output.err
    assert not (config_path.parent / "runs").exists()


def test_invalid_yaml_file_does_not_echo_its_contents(tmp_path, capsys):
    path = tmp_path / "invalid.yaml"
    path.write_text("agent:\n  api_key: [test-file-secret\n")
    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(path), "--prepare-only"])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "Invalid YAML" in output.err
    assert "test-file-secret" not in output.err


def test_module_entry_point_supports_pure_cli_configuration(tmp_path):
    output_dir = tmp_path / "module-runs"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flashrsi",
            "run",
            "--prepare-only",
            "--model",
            "cli-target",
            "--worker-model",
            "cli-worker",
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (run_dir,) = output_dir.iterdir()
    config = load_config(run_dir / "config.yaml")
    assert config.agent.model_name == "cli-target"
    assert config.algorithm.worker.model_name == "cli-worker"


def test_help_and_missing_config_are_actionable(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--help"])
    assert exc.value.code == 0
    assert "--prepare-only" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(tmp_path / "missing.yaml"), "--prepare-only"])
    assert exc.value.code == 2
    assert "missing.yaml" in capsys.readouterr().err


def test_dotted_flags_set_arbitrary_config_depth_and_preserve_yaml_types(tmp_path):
    output_dir = tmp_path / "dotted-runs"
    assert (
        main(
            [
                "run",
                "--prepare-only",
                "--run.output_dir",
                str(output_dir),
                "--agent.name",
                "miniagent",
                "--agent.model_name",
                "dotted-target",
                "--algorithm.worker.model_name=dotted-worker",
                "--benchmark.split.train",
                "0.5",
                "--benchmark.split.dev=0.25",
                "--benchmark.split.test",
                "0.25",
                "--algorithm.search.policy.max_depth",
                "4",
                "--algorithm.worker.sampling.temperature",
                "-0.7",
                "--algorithm.worker.sampling.delta",
                "-1.0e-3",
                "--agent.enabled",
                "true",
                "--agent.base_url=null",
                "--agent.tools=[{name: search, timeout: 30}]",
                "--agent.prompt=-text",
                "--agent.endpoint=https://example.test/?a=b=c",
            ]
        )
        == 0
    )
    (run_dir,) = output_dir.iterdir()
    config = load_config(run_dir / "config.yaml")
    assert config.agent.model_name == "dotted-target"
    assert config.algorithm.worker.model_name == "dotted-worker"
    assert config.benchmark.split.train == 0.5
    assert config.benchmark.split.dev == config.benchmark.split.test == 0.25
    assert config.algorithm.search.policy.max_depth == 4
    assert config.algorithm.worker.sampling.temperature == -0.7
    assert config.algorithm.worker.sampling.delta == -0.001
    assert config.agent.enabled is True
    assert config.agent.base_url is None
    assert config.agent.tools[0].timeout == 30
    assert config.agent.prompt == "-text"
    assert config.agent.endpoint == "https://example.test/?a=b=c"


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (
            ["--set=agent.model_name=set-value", "--agent.model_name", "dotted-value"],
            "dotted-value",
        ),
        (
            ["--agent.model_name=dotted-value", "--set", "agent.model_name=set-value"],
            "set-value",
        ),
    ],
)
def test_dotted_and_set_flags_follow_order_and_override_named_flags(
    config_path, settings, expected
):
    assert (
        main(
            [
                "run",
                f"--config={config_path}",
                "--prepare-only",
                *settings,
                "--model",
                "named-value",
            ]
        )
        == 0
    )
    (run_dir,) = (config_path.parent / "runs").iterdir()
    assert load_config(run_dir / "config.yaml").agent.model_name == expected


@pytest.mark.parametrize("following", [[], ["--prepare-only"], ["-c"], ["--"]])
def test_dotted_flags_require_values_without_consuming_other_options(
    config_path, following, capsys
):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--config", str(config_path), "--algorithm.rounds", *following])
    assert exc.value.code == 2
    assert "--algorithm.rounds requires a value" in capsys.readouterr().err
    assert not (config_path.parent / "runs").exists()


def test_option_terminator_stops_dotted_parsing_and_errors_omit_values(
    config_path, capsys
):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "run",
                "--config",
                str(config_path),
                "--prepare-only",
                "--",
                "--agent.api_key=test-hidden-secret",
            ]
        )
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "Unrecognized arguments" in output.err
    assert "test-hidden-secret" not in output.err
    assert not (config_path.parent / "runs").exists()
