"""Account for canonical calls without counting embedded trajectory copies."""

import json
import tempfile
import unittest
from pathlib import Path

from flashrsi._run_summary import _add_usage, _collect_usage, _empty


class RunSummaryTests(unittest.TestCase):
    def test_judge_samples_and_postprocess_are_counted_once(self):
        usage = {
            "model_calls": [
                {
                    "call_id": "answer",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            ],
            "benchmark_judge": {
                "samples": [
                    {"prompt_tokens": 30, "completion_tokens": 5},
                    {"prompt_tokens": 40, "completion_tokens": 6},
                ]
            },
            "benchmark_postprocess": {"prompt_tokens": 10, "completion_tokens": 2},
        }
        trajectory = {
            "status": "finished",
            "usage": usage,
            "messages": [{"usage": usage}],
        }
        with tempfile.TemporaryDirectory(prefix="flashrsi-summary-test-") as directory:
            root = Path(directory)
            cache = root / "cache/target/version"
            cache.mkdir(parents=True)
            (cache / "task.json").write_text(
                json.dumps({"trajectory": trajectory}), encoding="utf-8"
            )
            replay = root / "trajectories"
            replay.mkdir()
            (replay / "copy.json").write_text(
                json.dumps({"trajectories": [trajectory]}), encoding="utf-8"
            )
            summary = _collect_usage(root)
        self.assertEqual(summary["total"]["input_tokens"], 180)
        self.assertEqual(summary["total"]["output_tokens"], 33)
        self.assertEqual(summary["total"]["usage_entries"], 4)
        self.assertEqual(summary["total"]["records"], 1)

    def test_responses_cache_is_a_subset_of_input(self):
        total = _empty()
        _add_usage(
            total,
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 60},
            },
            set(),
            "target",
        )
        self.assertEqual(total["input_tokens"], 100)
        self.assertEqual(total["cache_read_tokens"], 60)

    def test_anthropic_cache_is_added_to_uncached_input(self):
        total = _empty()
        _add_usage(
            total,
            {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 60,
                "cache_creation_input_tokens": 5,
            },
            set(),
            "target",
        )
        self.assertEqual(total["input_tokens"], 75)
        self.assertEqual(total["cache_read_tokens"], 60)
        self.assertEqual(total["cache_write_tokens"], 5)

    def test_flat_judge_and_call_deduplication(self):
        total, seen = _empty(), set()
        call = {
            "model_calls": [
                {
                    "call_id": "same",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            ]
        }
        _add_usage(
            total,
            {**call, "benchmark_judge": {"prompt_tokens": 30, "completion_tokens": 5}},
            seen,
            "target",
        )
        _add_usage(total, call, seen, "target")
        self.assertEqual(total["input_tokens"], 130)
        self.assertEqual(total["duplicate_usage_entries"], 1)

    def test_gemini_judge_includes_reasoning_and_cached_tokens(self):
        total = _empty()
        _add_usage(
            total,
            {
                "prompt_token_count": 100,
                "candidates_token_count": 20,
                "thoughts_token_count": 10,
                "cached_content_token_count": 60,
            },
            set(),
            "target",
        )
        self.assertEqual(total["input_tokens"], 100)
        self.assertEqual(total["output_tokens"], 30)
        self.assertEqual(total["cache_read_tokens"], 60)
        self.assertEqual(total["usage_entries_missing_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
