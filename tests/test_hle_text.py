"""Official HLE source, text projection and exclusion before experiment splits."""

import json

import pytest

from flashrsi.benchmarks import HLE


def test_real_parquet_projection_does_not_decode_image_features(tmp_path, monkeypatch):
    import datasets

    source = {
        "id": ["text"],
        "question": ["Public question"],
        "image": [""],
        "answer": ["PRIVATE_REFERENCE"],
        "category": ["Math"],
        "answer_type": ["exactMatch"],
        "image_preview": [{"bytes": b"INVALID_IMAGE", "path": None}],
        "rationale_image": [{"bytes": b"INVALID_IMAGE", "path": None}],
    }
    features = datasets.Features(
        {
            key: datasets.Image()
            if key in {"image_preview", "rationale_image"}
            else datasets.Value("string")
            for key in source
        }
    )
    path = tmp_path / "official-format.parquet"
    datasets.Dataset.from_dict(source, features=features).to_parquet(path)
    monkeypatch.chdir(str(tmp_path).removeprefix("\\\\?\\"))
    load = datasets.load_dataset

    def official(source, **kwargs):
        assert source == "cais/hle"
        return load(
            "parquet",
            data_files={"test": "official-format.parquet"},
            columns=kwargs["columns"],
            streaming=True,
            cache_dir="cache",
        )

    monkeypatch.setattr(datasets, "load_dataset", official)
    assert HLE({}).load()["test"][0].task_id == "text"


def test_official_hf_projection_excludes_image_features_and_questions(monkeypatch):
    import datasets

    rows = [
        {
            "id": str(i),
            "question": "Public question " + str(i),
            "answer": "PRIVATE_REFERENCE",
            "image": image,
            "category": "Math",
            "answer_type": "exactMatch",
            "image_preview": object(),
            "rationale_image": object(),
            "rationale": "PRIVATE_RATIONALE",
        }
        for i, image in enumerate(
            (
                "",
                None,
                "  \n",
                "https://example.invalid/image.png",
                "data:image/png;base64,AA==",
            )
        )
    ]
    calls = []

    def load(source, **kwargs):
        calls.append((source, kwargs))
        columns = kwargs["columns"]
        assert set(columns) == {
            "id",
            "question",
            "image",
            "answer",
            "category",
            "answer_type",
        }
        return {"test": [{k: row[k] for k in columns} for row in rows]}

    monkeypatch.setattr(datasets, "load_dataset", load)
    benchmark = HLE({"split_counts": {"train": 1, "dev": 1, "test": 1}})
    splits = benchmark.load()
    assert {role: len(tasks) for role, tasks in splits.items()} == {
        "train": 1,
        "dev": 1,
        "test": 1,
    }
    assert {task.task_id for tasks in splits.values() for task in tasks} == {
        "0",
        "1",
        "2",
    }
    assert calls[0][0] == "cais/hle"
    assert calls[0][1]["revision"] == HLE.metadata["revision"]
    assert calls[0][1]["streaming"] is True
    assert all(
        "PRIVATE" not in task.question for tasks in splits.values() for task in tasks
    )
    assert all(
        "rationale" not in row and "image_preview" not in row
        for row in benchmark._rows_by_id.values()
    )


def test_local_text_override_drops_unused_image_and_rationale_fields(tmp_path):
    path = tmp_path / "test.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "text",
                    "question": "Public question",
                    "answer": "PRIVATE_REFERENCE",
                    "rationale": "PRIVATE_RATIONALE",
                    "image_preview": {"bytes": "not needed"},
                }
            ]
        )
    )
    benchmark = HLE({"data_path": str(path)})
    assert benchmark.load()["test"][0].task_id == "text"
    assert set(benchmark._rows_by_id["text"]) == {"id", "question", "answer"}


def test_image_only_input_cannot_fill_text_experiment_roles(tmp_path):
    path = tmp_path / "test.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "image",
                    "question": "Read the figure",
                    "answer": "PRIVATE",
                    "image": "https://example.invalid/image.png",
                }
            ]
        )
    )
    with pytest.raises(ValueError):
        HLE(
            {"data_path": str(path), "split_counts": {"train": 1, "dev": 1, "test": 1}}
        ).load()
