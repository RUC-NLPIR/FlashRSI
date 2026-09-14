import pytest

from flashrsi.benchmarks.metrics import (
    exact_match,
    normalize_answer,
    qa_metrics,
    token_f1,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  The\tCRIMSON\nTide!  ", "crimson tide"),
        ("Ａｎ ＯＦＦＩＣＥ ﬂoor", "office floor"),
        ("“Straße”—Café…", "strassecafé"),
        ("New-York's $5", "newyorks 5"),
        ("A theatre and an anthem", "theatre and anthem"),
        ("5 ≥ 3", "5 ≥ 3"),
        ("The an a!", ""),
    ],
)
def test_normalize_answer_preserves_searchqa_rules(value, expected):
    assert normalize_answer(value) == expected


@pytest.mark.parametrize(
    ("prediction", "answer", "expected"),
    [
        ("The CRIMSON tide!", "crimson tide", 1.0),
        ("Ｓｔｒａßｅ", "strasse", 1.0),
        ("New-York", "New York", 0.0),
        ("red blue", "blue red", 0.0),
        ("Café", "Cafe", 0.0),
        ("The", "An", 1.0),
    ],
)
def test_exact_match_normalizes_raw_answers(prediction, answer, expected):
    assert exact_match(prediction, answer) == expected


@pytest.mark.parametrize(
    ("prediction", "answer", "expected"),
    [
        ("The CRIMSON tide!", "crimson tide", 1.0),
        ("red blue blue", "red red blue", 2 / 3),
        ("RED!", "the red blue", 2 / 3),
        ("red blue green", "BLUE", 0.5),
        ("red", "blue", 0.0),
        ("The", "An", 1.0),
        ("The", "blue", 0.0),
        ("blue", "The", 0.0),
    ],
)
def test_token_f1_normalizes_and_counts_token_multiplicity(
    prediction, answer, expected
):
    assert token_f1(prediction, answer) == pytest.approx(expected)


def test_qa_metrics_uses_the_best_reference():
    assert qa_metrics("The CRIMSON tide!", ["red red blue", "Crimson Tide"]) == {
        "exact_match": 1.0,
        "f1": 1.0,
    }
    metrics = qa_metrics("red blue blue", ("unrelated", "red red blue"))
    assert metrics["exact_match"] == 0.0
    assert metrics["f1"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("prediction", ["", " \t\n", "\u2003"])
def test_qa_metrics_does_not_reward_blank_predictions(prediction):
    assert qa_metrics(prediction, ["The"]) == {"exact_match": 0.0, "f1": 0.0}


def test_qa_metrics_can_match_nonblank_answers_that_normalize_to_empty():
    assert qa_metrics("The", ["An"]) == {"exact_match": 1.0, "f1": 1.0}


@pytest.mark.parametrize("prediction", ["answer", ""])
def test_qa_metrics_rejects_missing_references(prediction):
    with pytest.raises(ValueError, match="at least one reference answer"):
        qa_metrics(prediction, ())
