import json

import pytest

from flashrsi.benchmarks.twowiki_multihopqa import TwoWikiMultiHopQA
from flashrsi.core import Trajectory


def row(i=0):
    return {
        "_id": str(i),
        "question": "Which city?",
        "answer": "London",
        "context": [["Person", ["A person lived abroad.", "Another sentence."]]],
        "supporting_facts": [["SECRET_SUPPORT", 0]],
        "evidences": [["SECRET_EVIDENCE", "relation", "London"]],
        "entity_ids": "SECRET_ENTITY",
    }


def test_native_and_mirror_schema_and_no_label_leak():
    original = row()
    mirror = {**original, "id": original["_id"]}
    del mirror["_id"]
    mirror["context"] = {
        "title": ["Person"],
        "sentences": [["A person lived abroad.", "Another sentence."]],
    }
    native = TwoWikiMultiHopQA._task_from_row(original, "train")
    assert native == TwoWikiMultiHopQA._task_from_row(mirror, "train")
    assert "SECRET" not in native.question
    assert "London" not in native.question
    assert "abroad. Another" in native.question


@pytest.mark.parametrize(
    "field,value",
    [
        ("answer", ""),
        ("context", []),
        ("context", {"title": ["x"], "sentences": []}),
        ("context", [["x", [None]]]),
        ("_id", None),
    ],
)
def test_invalid_native_rows(field, value):
    with pytest.raises(ValueError):
        TwoWikiMultiHopQA._task_from_row({**row(), field: value}, "train")


def test_local_splits_grading_and_failed_runs(tmp_path):
    path = tmp_path / "train.json"
    path.write_text(json.dumps([row(i) for i in range(6)]))
    config = {
        "data_path": str(path),
        "split_counts": {"train": 2, "dev": 2, "test": 2},
        "seed": 42,
    }
    bench = TwoWikiMultiHopQA(config)
    splits = bench.load()
    assert {k: len(v) for k, v in splits.items()} == {"train": 2, "dev": 2, "test": 2}
    assert splits == TwoWikiMultiHopQA(config).load()
    assert len({t.task_id for group in splits.values() for t in group}) == 6
    task = splits["test"][0]
    good, partial, failed = bench.grade(
        tuple(
            Trajectory(
                task=task,
                output=output,
                status=status,
                error_message="test failure" if status == "error" else None,
            )
            for output, status in [
                ("The London!", "finished"),
                ("London city", "finished"),
                ("London", "error"),
            ]
        )
    )
    assert good.metrics == {"exact_match": 1, "f1": 1}
    assert partial.metrics["f1"] == pytest.approx(2 / 3)
    assert failed.metrics == {"exact_match": 0, "f1": 0}


def test_no_implicit_official_test_and_unsupported_modes(tmp_path):
    path = tmp_path / "train.json"
    path.write_text(json.dumps([row()]))
    bench = TwoWikiMultiHopQA({"data_path": str(path)})
    assert bench.load()["test"] == ()
    assert bench.metadata["scoring"] == "answer_text"
    assert TwoWikiMultiHopQA.metadata["splits"] == ("train", "validation")
    for config in ({"mode": "fullwiki"}, {"scoring": "official"}):
        with pytest.raises(ValueError):
            TwoWikiMultiHopQA(config)


def test_yes_no_mismatch_is_zero():
    task = TwoWikiMultiHopQA._task_from_row({**row(), "answer": "yes"}, "dev")
    assert TwoWikiMultiHopQA({})._score("yes indeed", task)["f1"] == 0
