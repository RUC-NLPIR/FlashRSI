"""CLI names that select the main experiment roles."""

from flashrsi import cli


def test_explicit_role_names_map_to_configuration_paths():
    args = cli._parser().parse_args(
        [
            "run",
            "--algorithm",
            "skillopt",
            "--benchmark",
            "searchqa",
            "--agent-harness",
            "miniagent",
            "--model",
            "target-model",
            "--worker-model",
            "worker-model",
        ]
    )

    overrides = cli._overrides(args)
    assert overrides["algorithm"]["name"] == "skillopt"
    assert overrides["benchmark"]["name"] == "searchqa"
    assert overrides["agent"]["name"] == "miniagent"
    assert overrides["agent"]["llm"]["model_name"] == "target-model"
    assert overrides["algorithm"]["worker"]["llm"]["model_name"] == "worker-model"


def test_short_algorithm_and_legacy_agent_aliases_remain_supported():
    args = cli._parser().parse_args(
        ["run", "--algo", "opro", "--agent", "codex"]
    )

    overrides = cli._overrides(args)
    assert overrides["algorithm"]["name"] == "opro"
    assert overrides["agent"]["name"] == "codex"
