"""Offline checks for reporting experimental claims and provider token counts."""

import json

import pytest

from scripts.summarize_searchqa_experiment import _usage, collect, render


def test_canonical_usage_does_not_double_count_openai_cache():
    assert _usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 8,
            "prompt_tokens_details": {"cached_tokens": 70},
        }
    ) == {
        "input_tokens": 100,
        "output_tokens": 8,
    }


def test_miniagent_usage_sums_only_canonical_calls():
    assert _usage(
        {
            "model_calls": [
                {"usage": {"prompt_tokens": 100, "completion_tokens": 10}},
                {"usage": {"prompt_tokens": 120, "completion_tokens": 20}},
            ],
            "turns": 2,
        }
    ) == {"input_tokens": 220, "output_tokens": 30}


def test_claude_usage_uses_aggregate_models_not_last_message():
    assert _usage(
        {
            "input_tokens": 999,
            "output_tokens": 999,
            "model_usage": {
                "flash": {
                    "inputTokens": 100,
                    "cacheReadInputTokens": 70,
                    "cacheCreationInputTokens": 10,
                    "outputTokens": 8,
                },
                "other": {"inputTokens": 50, "outputTokens": 2},
            },
        }
    ) == {"input_tokens": 230, "output_tokens": 10}


def test_missing_experiment_is_pending(tmp_path):
    assert collect(tmp_path / "claude_code") == {
        "harness": "claude_code",
        "status": "pending",
    }


def _completed_experiment(tmp_path):
    experiment = tmp_path / "miniagent"
    experiment.mkdir()
    plan = {
        "profile": "smoke",
        "split_counts": {"train": 4, "dev": 4, "test": 8},
        "config": {
            "agent": {"llm": {"model_name": "deepseek-v4-flash"}},
            "algorithm": {"worker": {"llm": {"model_name": "deepseek-v4-pro"}}},
        },
    }
    score = {"tasks": 8, "finished": 8, "hard": 0.75, "f1": 0.8}
    result = {
        "status": "finished",
        "baseline_test": score,
        "evolved_test": score,
        "initial_snapshot": "same",
        "final_snapshot": "same",
        "test_used_for_selection": False,
        "paired_comparison": {
            "delta_percentage_points": 0,
            "improved_tasks": 1,
            "regressed_tasks": 1,
            "paired_bootstrap_95pct_pp": [-25, 25],
        },
    }
    (experiment / "plan.json").write_text(json.dumps(plan))
    (experiment / "result.json").write_text(json.dumps(result))
    return experiment, result


def test_same_snapshot_report_cannot_claim_skill_changed(tmp_path):
    experiment, _ = _completed_experiment(tmp_path)
    record = collect(experiment)
    assert record["status"] == "finished"
    assert record["skill_changed"] is False
    assert record["test_used_for_selection"] is False
    text = render({"profile": "smoke", "inspected_at": "now", "experiments": [record]})
    assert "不能归因于演化" in text
    assert "75.00%" in text
    assert "模型不同" in text


@pytest.mark.parametrize("field", ["tasks", "finished"])
def test_short_test_evidence_rejected(tmp_path, field):
    experiment, result = _completed_experiment(tmp_path)
    result["evolved_test"][field] = 7
    (experiment / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Incomplete test evidence"):
        collect(experiment)
