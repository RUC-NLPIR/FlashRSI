"""Native SearchQA JSON includes integer IDs and missing search snippets."""

import unittest

from flashrsi.benchmarks._data import _split_tasks
from flashrsi.benchmarks.searchqa import SearchQA


class SearchQANativeTests(unittest.TestCase):
    def row(self, results):
        return {
            "id": 0,
            "question": "Who?",
            "answer": "Copernicus",
            "search_results": results,
        }

    def test_native_null_snippets_and_integer_zero_id(self):
        row = self.row(
            [{"snippet": "Galileo."}, {"snippet": None}, {"snippet": "Copernicus."}]
        )
        task = SearchQA._task_from_row(row, "train")
        self.assertEqual(task.task_id, "train:0")
        self.assertIn("Context:\nGalileo.\nCopernicus.\n\nQuestion:", task.question)
        self.assertEqual(task.ground_truth, "Copernicus")
        self.assertNotEqual(task.task_id, SearchQA._task_from_row(row, "test").task_id)

    def test_columnar_snippets_and_existing_string_id(self):
        row = self.row({"snippets": ["Evidence", None]})
        row["id"] = "existing-id"
        task = SearchQA._task_from_row(row, "train")
        self.assertEqual(task.task_id, "existing-id")
        self.assertIn("Context:\nEvidence\n\nQuestion:", task.question)

    def test_malformed_non_null_snippets_still_fail(self):
        for results in ([{"snippet": 42}], {"snippets": [False]}, ["not an object"]):
            with (
                self.subTest(results=results),
                self.assertRaisesRegex(ValueError, "malformed snippets"),
            ):
                SearchQA._task_from_row(self.row(results), "train")

    def test_limited_native_sampling_keeps_membership_and_proportions(self):
        tasks = []
        for split, size in (("train", 40), ("validation", 10), ("test", 10)):
            for i in range(size):
                row = self.row([{"snippet": "Evidence"}])
                row["id"] = i
                tasks.append(SearchQA._task_from_row(row, split))
        full = _split_tasks(iter(tasks), {"split": "auto", "seed": 42})
        for order in (tasks, list(reversed(tasks))):
            sampled = _split_tasks(
                iter(order), {"split": "auto", "seed": 42, "limit": 6}
            )
            self.assertEqual(
                {k: len(v) for k, v in sampled.items()},
                {"train": 4, "dev": 1, "test": 1},
            )
            for role, size in (("train", 4), ("dev", 1), ("test", 1)):
                self.assertEqual(sampled[role], full[role][:size])


if __name__ == "__main__":
    unittest.main()
