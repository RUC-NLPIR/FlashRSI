import json

import pytest

from flashrsi._run_summary import _collect_usage, _finish_summary, _write_run_summary


def save(root, name, usage, status="finished"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"trajectory": {"status": status, "usage": usage}}))


def test_canonical_cache_failures_replays_and_cost(tmp_path):
    usage = {
        "session_id": "session-1",
        "input_tokens": 9999,
        "output_tokens": 9999,
        "total_cost_usd": 0.4,
        "model_usage": {
            "flash": {
                "inputTokens": 100,
                "outputTokens": 10,
                "cacheReadInputTokens": 50,
                "cacheCreationInputTokens": 20,
                "costUSD": 0.4,
                "costBasis": "unknown",
            }
        },
    }
    save(tmp_path, "cache/target/ab/a.json", usage)
    save(tmp_path, "attempts/replay/trajectories/a.json", usage)
    save(tmp_path, "cache/errors/target/ab/b.json", usage, "error")
    save(
        tmp_path,
        "cache/errors/target/ab/c.json",
        {
            "model_calls": [
                {
                    "call_id": "failed-call",
                    "usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 5,
                        "prompt_tokens_details": {"cached_tokens": 8},
                    },
                }
            ]
        },
        "error",
    )
    save(tmp_path, "cache/worker/ab/d.json", {})
    save(
        tmp_path,
        "cache/protocol_retries/worker/ab/e.json",
        {"prompt_tokens": 12, "completion_tokens": 3},
    )
    result = _write_run_summary(
        tmp_path, result={"status": "finished", "api_key": "secret"}, emit=False
    )
    total = result["usage"]["total"]
    assert total["input_tokens"] == 212
    assert total["output_tokens"] == 18
    assert total["cache_read_tokens"] == 58
    assert total["cache_write_tokens"] == 20
    assert total["sdk_cost_usd"] == pytest.approx(0.4)
    assert total["records"] == 5
    assert total["failed_records"] == 2
    assert total["duplicate_usage_entries"] == 1
    assert total["usage_entries_missing_tokens"] == 1
    assert total["cost_bases"] == ["unknown"]
    assert "secret" not in (tmp_path / "end-summary.json").read_text()
    assert "网关实际费用：未记录" in (tmp_path / "end-summary.md").read_text()


def test_no_cost_is_unknown_and_identical_calls_without_ids_are_not_deduped(tmp_path):
    for index in range(2):
        save(
            tmp_path,
            f"trajectories/{index}.json",
            {"prompt_tokens": 8, "completion_tokens": 2},
        )
    total = _collect_usage(tmp_path)["total"]
    assert total["input_tokens"] == 16
    assert total["sdk_cost_usd"] is None
    assert total["duplicate_usage_entries"] == 0


def test_report_failure_does_not_mask_experiment_failure(tmp_path, caplog):
    (tmp_path / "result.json").write_text("invalid")
    assert _finish_summary(tmp_path) is None
    assert "raw evidence retained" in caplog.text


def test_empty_or_null_usage_is_reported_missing(tmp_path):
    save(tmp_path, "trajectories/empty.json", {"model_calls": []})
    save(
        tmp_path,
        "trajectories/null.json",
        {
            "prompt_tokens": None,
            "completion_tokens": None,
            "prompt_tokens_details": None,
        },
    )
    total = _collect_usage(tmp_path)["total"]
    assert total["usage_entries_missing_tokens"] == 2
    assert total["sdk_cost_usd"] is None
