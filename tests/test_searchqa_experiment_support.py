import json
from pathlib import Path

import pytest
import yaml

import flashrsi.agents
from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.core import Trajectory
from scripts._searchqa_experiment_support import (
    INITIAL_SKILL,
    ExperimentSearchQA,
    create_seed,
    official_metrics,
)


@pytest.mark.parametrize(
    ("prediction", "answers", "hard", "f1"),
    [
        (
            "Analysis.\n<answer>Wrong</answer>\n<ANSWER> The Nile! </ANSWER>",
            ["Nile"],
            1,
            1,
        ),
        ("The evidence points here.\n\nNew York\n\n", ["NYC", "New York"], 1, 1),
        ("<answer>red red blue</answer>", ["red blue blue"], 0, 2 / 3),
        ("The blue whale", ["blue whale", "orca"], 1, 1),
        ("<answer>‘Paris’</answer>", ["Paris"], 0, 0),
        ("<answer>ＮＩＬＥ</answer>", ["Nile"], 0, 0),
        (" ", ["Nile"], 0, 0),
        (" ", ["the"], 1, 1),
    ],
)
def test_official_extraction_and_normalization(prediction, answers, hard, f1):
    assert official_metrics(prediction, answers) == pytest.approx(
        {"hard": hard, "f1": f1}
    )


def _benchmark(tmp_path):
    for name in ("train", "dev", "test"):
        (tmp_path / f"{name}.json").write_text(
            json.dumps(
                [
                    {
                        "id": name,
                        "question": "Name the city.",
                        "context": "The city is Paris.",
                        "answers": ["Paris"],
                    }
                ]
            ),
            encoding="utf-8",
        )
    benchmark = ExperimentSearchQA({"data_path": str(tmp_path), "split": "auto"})
    benchmark.load()
    return benchmark


def test_grade_uses_official_hard_and_keeps_lite_diagnostics(tmp_path):
    benchmark = _benchmark(tmp_path)
    task = benchmark.test[0]
    trajectory = Trajectory(
        task=task,
        output="Reasoning text.\n<answer>Paris</answer>",
        metrics={"external_metric": 0.25},
    )
    result = benchmark.grade((trajectory,))[0]
    assert benchmark.primary_metric == "hard"
    assert result.metrics["hard"] == result.metrics["f1"] == 1.0
    assert result.metrics["exact_match"] == result.metrics["lite_f1"] == 0.0
    assert result.metrics["external_metric"] == 0.25
    assert result.task == trajectory.task
    assert result.output == trajectory.output
    original = SearchQA({"data_path": str(tmp_path), "split": "auto"})
    original.load()
    assert task.question == original.test[0].question


def test_failed_trajectory_scores_zero_despite_correct_answer(tmp_path):
    benchmark = _benchmark(tmp_path)
    result = benchmark.grade(
        (
            Trajectory(
                task=benchmark.test[0],
                status="error",
                output="<answer>Paris</answer>",
                error_message="request interrupted",
            ),
        )
    )[0]
    assert dict(result.metrics) == {
        "hard": 0.0,
        "f1": 0.0,
        "exact_match": 0.0,
        "lite_f1": 0.0,
    }


@pytest.mark.parametrize(
    "harness,agent_type", [("miniagent", MiniAgent), ("claude_code", ClaudeCode)]
)
def test_seed_is_loadable_equal_and_preserves_bundled_prompt(
    tmp_path, harness, agent_type
):
    bundled = Path(flashrsi.agents.__file__).parent / harness
    destination = create_seed(harness, tmp_path / harness)
    agent = agent_type(
        {"source_dir": str(destination), "llm": {"model_name": "offline"}}
    )
    agent.set_scope({"skill": "rw"})

    if harness == "miniagent":
        assert (destination / "skills/main.md").read_text() == INITIAL_SKILL
        assert (destination / "prompts/system.md").read_bytes() == (
            bundled / "prompts/system.md"
        ).read_bytes()
        config = yaml.safe_load((destination / "agent.yaml").read_text())
        assert config["skills"] == ["main"]
        assert agent.snapshot.files["skills/main.md"].content.decode() == INITIAL_SKILL
    else:
        skill_text = (destination / "skills/searchqa/SKILL.md").read_text()
        _, frontmatter, body = skill_text.split("---", 2)
        assert yaml.safe_load(frontmatter)["name"] == "searchqa"
        assert body.lstrip("\n") == INITIAL_SKILL
        assert '"flashrsi:searchqa"' in (destination / "CLAUDE.md").read_text()
        assert (
            agent.snapshot.files["skills/searchqa/SKILL.md"].content.decode()
            == skill_text
        )
        assert (destination / "settings.json").read_bytes() == (
            bundled / "settings.json"
        ).read_bytes()
    assert not list(destination.rglob("*.pyc"))
    with pytest.raises(FileExistsError):
        create_seed(harness, destination)
