"""Independent pinned year pools preserve downstream partition and scoring."""

import json

import pytest

from flashrsi.benchmarks.aime import _SOURCES, AIME
from flashrsi.core import Trajectory


@pytest.fixture
def pools(tmp_path, monkeypatch):
    rows = {
        year: [
            {"id": i, "problem": f"Year {year} problem {i}", "answer": i + 10}
            for i in range(6)
        ]
        for year in (2025, 2026)
    }
    paths = {}
    for year, data in rows.items():
        paths[year] = tmp_path / f"{year}.jsonl"
        paths[year].write_text(
            "".join(json.dumps(r) + "\n" for r in data), encoding="utf-8"
        )
    calls = []

    def download(**options):
        year = next(
            y
            for y, source in _SOURCES.items()
            if source["source"] == options["repo_id"]
        )
        assert options["revision"] == _SOURCES[year]["revision"]
        assert options["filename"] == _SOURCES[year]["filename"]
        calls.append(year)
        return str(paths[year])

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    return rows, paths, calls


def test_external_year_preserves_heldout_and_native_grading(pools):
    _, _, calls = pools
    cfg = {"year": 2026, "split_counts": {"train": 1, "dev": 1, "test": 1}, "seed": 42}
    baseline = AIME(cfg).load()
    benchmark = AIME({**cfg, "evolution_year": 2025, "evolution_limit": 1})
    splits = benchmark.load()
    assert splits["dev"] == baseline["dev"]
    assert splits["test"] == baseline["test"]
    assert len(splits["train"]) == 1
    assert all(t.task_id.startswith("aime2025:") for t in splits["train"])
    assert benchmark.load() is splits
    source = benchmark.metadata["evolution_source"]
    assert source["source"] == "math-ai/aime25"
    assert source["year"] == 2025
    assert source["revision"] == _SOURCES[2025]["revision"]
    assert source["native_split"] == "test"
    assert len(source["pool_checksum"]) == 64
    assert calls == [2026, 2026, 2025]
    for task in (*benchmark.train, *benchmark.dev, *benchmark.test):
        trajectory = Trajectory(task=task, output=r"\boxed{" + task.ground_truth + "}")
        assert benchmark.grade((trajectory,))[0].metrics == {"accuracy": 1.0}


@pytest.mark.parametrize("year", [2026, 2024, "2025", True])
def test_evolution_year_must_be_truly_different(pools, year):
    benchmark = AIME({"year": 2026, "evolution_year": year})
    with pytest.raises(ValueError, match="supported different year"):
        benchmark.load()
    assert benchmark._splits is None
    assert "evolution_source" not in benchmark.metadata


def test_entire_source_pools_are_checked_before_sampling(pools):
    rows, paths, _ = pools
    cfg = {"year": 2026, "split_counts": {"train": 1, "dev": 1, "test": 1}, "seed": 42}
    selected = AIME(cfg).load()
    selected_ids = {t.task_id for group in selected.values() for t in group}
    unseen = next(r for r in rows[2026] if f"aime2026:{r['id']}" not in selected_ids)
    # A renamed ID/year or whitespace difference cannot hide a held-out-source question.
    rows[2025][-1]["problem"] = "  " + unseen["problem"].replace(" ", "\n") + "  "
    paths[2025].write_text(
        "".join(json.dumps(r) + "\n" for r in rows[2025]), encoding="utf-8"
    )
    benchmark = AIME({**cfg, "evolution_year": 2025, "evolution_limit": 1})
    with pytest.raises(ValueError, match="overlaps downstream"):
        benchmark.load()
    assert benchmark._splits is None
    assert "evolution_source" not in benchmark.metadata


def test_limit_without_independent_source_is_rejected():
    with pytest.raises(ValueError, match="requires evolution_year"):
        AIME({"evolution_limit": 1}).load()
