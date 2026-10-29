"""Native external TriviaQA references use the unchanged SearchQA scorer."""

import pytest

from flashrsi.benchmarks import SearchQA, TriviaQA
from flashrsi.core import Trajectory


@pytest.fixture
def pools(monkeypatch):
    downstream = [
        {
            "id": f"search-{i}",
            "question": f"Search question {i}?",
            "context": "Original search snippets.",
            "answers": ["Canonical", "Native Alias"],
        }
        for i in range(6)
    ]
    external = [
        {
            "question_id": f"trivia-{i}",
            "question": f"Trivia question {i}?",
            "answer": {
                "value": "Canonical",
                "aliases": ["Native Alias"],
                "normalized_aliases": ["canonical", "native alias"],
                "human_answers": [],
            },
            "entity_pages": {
                "title": ["Original title"],
                "wiki_context": ["Original page"],
            },
        }
        for i in range(4)
    ]
    monkeypatch.setattr(
        SearchQA,
        "_load_source_rows",
        lambda self: (("validation", r) for r in downstream),
    )
    calls = []

    def load_dataset(source, *, split, name, revision, streaming):
        calls.append({"source": source, "split": split, "config": name})
        assert revision == TriviaQA.metadata["revision"] and streaming is True
        return external

    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    return downstream, external, calls


def config(**extra):
    return {"split_counts": {"train": 1, "dev": 1, "test": 1}, "seed": 42, **extra}


def evolution():
    return {"evolution_triviaqa": {"split": "train"}, "evolution_limit": 1}


@pytest.mark.parametrize("scoring", ["text_em_f1", "legacy"])
def test_native_external_aliases_scorer_and_heldout(pools, scoring):
    baseline = SearchQA(config(scoring=scoring)).load()
    bench = SearchQA(config(scoring=scoring, **evolution()))
    splits = bench.load()
    assert bench.load() is splits
    assert bench.dev == baseline["dev"] and bench.test == baseline["test"]
    train = bench.train[0]
    assert train.task_id.startswith("trivia-")
    assert "Original title: Original page" in train.question
    assert (
        train.ground_truth == "Canonical"
        and "Native Alias" in train.metadata["answers"]
    )
    source = bench.metadata["evolution_source"]
    assert source["source"] == TriviaQA.metadata["source"]
    assert source["native_split"] == "train" and source["pool_size"] == 4
    assert len(source["pool_checksum"]) == 64
    assert "scorer_revision" not in source  # SearchQA still owns grading.
    assert bench.scoring == scoring
    for task in (*bench.train, *bench.dev, *bench.test):
        good, bad = bench.grade(
            (
                Trajectory(task=task, output="Native Alias"),
                Trajectory(task=task, output="wrong"),
            )
        )
        assert good.metrics == {"exact_match": 1.0, "f1": 1.0}
        assert bad.metrics == {"exact_match": 0.0, "f1": 0.0}


@pytest.mark.parametrize("field", ["question_id", "question"])
def test_entire_sources_guard_before_limit(pools, field):
    downstream, external, _ = pools
    external[-1][field] = (
        downstream[-1]["id"] if field == "question_id" else " SEARCH\nquestion\t5? "
    )
    external[-1]["entity_pages"]["wiki_context"] = ["Changed evidence"]
    bench = SearchQA(config(**evolution()))
    with pytest.raises(ValueError, match="overlaps downstream"):
        bench.load()
    assert bench._splits is None and "evolution_source" not in bench.metadata


def test_public_complete_native_cache_source_override(pools):
    _, _, calls = pools
    bench = SearchQA(
        config(
            evolution_triviaqa={
                "split": "train",
                "dataset": {"source": "/native/cache", "config": "default"},
            },
            evolution_limit=1,
        )
    )
    bench.load()
    assert calls == [{"source": "/native/cache", "split": "train", "config": "default"}]
    assert bench.metadata["evolution_source"]["source"] == "/native/cache"


@pytest.mark.parametrize(
    "extra",
    [
        {"evolution_triviaqa": "train"},
        {"evolution_triviaqa": {}},
        {"evolution_triviaqa": {"split": "test"}},
        {"evolution_triviaqa": {"split": "train", "dataset": "path"}},
        {"evolution_triviaqa": {"split": "train"}, "evolution_split": "train"},
    ],
)
def test_invalid_or_ambiguous_public_source(pools, extra):
    with pytest.raises(ValueError, match="SearchQA evolution"):
        SearchQA(config(**extra)).load()


def test_original_duplicate_external_question_is_retained(pools):
    _, external, _ = pools
    external[-1]["question"] = external[0]["question"]
    bench = SearchQA(config(**{**evolution(), "evolution_limit": 4}))
    bench.load()
    assert (
        len(bench.train) == 4 and bench.metadata["evolution_source"]["pool_size"] == 4
    )


def test_malformed_native_aliases_are_not_filled(pools):
    del pools[1][-1]["answer"]["normalized_aliases"]
    with pytest.raises(ValueError, match="normalized_aliases"):
        SearchQA(config(**evolution())).load()
