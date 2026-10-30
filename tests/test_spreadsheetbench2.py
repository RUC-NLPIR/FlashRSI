"""Native workbook isolation, deterministic materialization and launcher wiring."""

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from flashrsi import _launch
from flashrsi._startup import _HARBOR
from flashrsi.benchmarks import SpreadsheetBench2
from flashrsi.benchmarks.spreadsheetbench2 import _data, _recalculate
from flashrsi.config import load_config
from flashrsi.core import Trajectory
from flashrsi.runner import _BENCHMARKS


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    upstream = tmp_path / "upstream"
    (upstream / "evaluation").mkdir(parents=True)
    for name in ("evaluation.py", "open_spreadsheet.py"):
        (upstream / "evaluation" / name).write_bytes(b"# native fixture, unmodified\n")
    (upstream / "SWE-agent").mkdir()
    (upstream / "SWE-agent/spreadsheet.Dockerfile").write_text("FROM python:3.11\n")
    root = tmp_path / "dataset"
    for category in _data._CATEGORIES:
        folder = root / category
        folder.mkdir(parents=True)
        (folder / "Embedded Color_input.xlsx").write_bytes(b"PUBLIC_WORKBOOK")
        (folder / "gold.xlsx").write_bytes(b"SECRET_GOLDEN")
        (folder / "dataset.json").write_text(
            json.dumps(
                [
                    {
                        "id": "01_01",
                        "instruction": "Fix the workbook.",
                        "spreadsheet_path": "Embedded Color_input.xlsx",
                        "golden_response_path": "gold.xlsx",
                        "answer_position": "Sheet!A1:B2",
                    }
                ]
            )
        )
    monkeypatch.setattr(_data, "_download_git", lambda *args: upstream)
    monkeypatch.setattr(_data.constants, "HF_HOME", str(tmp_path / "cache"))
    return root, upstream


def test_native_materialization_isolated_and_reproducible(dataset):
    from harbor.models.task.task import Task as HarborTask

    root, upstream = dataset
    config = {
        "data_path": root,
        "split_counts": {"train": 1, "dev": 1, "test": 1},
        "seed": 42,
    }
    bench = SpreadsheetBench2(config)
    splits = bench.load()
    assert splits == SpreadsheetBench2(config).load()
    tasks = [t for group in splits.values() for t in group]
    assert len({t.task_id for t in tasks}) == 3
    assert bench.metadata["source"] == "local"
    for task in tasks:
        directory = Path(task.env)
        native = HarborTask(directory)
        assert native.config.verifier.environment_mode == "separate"
        assert "SECRET_GOLDEN" not in task.question
        assert "answer_position" not in task.question
        assert all(
            b"SECRET_GOLDEN" not in p.read_bytes()
            for p in (directory / "environment").iterdir()
        )
        assert (directory / "tests/evaluation.py").read_bytes() == (
            upstream / "evaluation/evaluation.py"
        ).read_bytes()
        row = json.loads((directory / "tests/record.json").read_text())["row"]
        assert "Embedded Color" in row["spreadsheet_path"]
        assert (
            directory / "tests" / row["golden_response_path"]
        ).read_bytes() == b"SECRET_GOLDEN"
        assert "/logs/artifacts/01_01_output.xlsx" in task.question
        assert "SpreadsheetBench2 task environment:" in task.question
        assert "/usr/local/bin/python" in task.question


def test_prepared_resources_use_mirrored_workbooks_and_evaluator(
    dataset, monkeypatch, tmp_path
):
    root, upstream = dataset
    archive = tmp_path / "native.zip"
    with ZipFile(archive, "w") as output:
        for path in root.rglob("*"):
            if path.is_file():
                output.write(
                    path, "spreadsheetbench-v2/" + path.relative_to(root).as_posix()
                )

    def forbidden(*args, **kwargs):
        pytest.fail("Prepared inputs must not fetch upstream resources")

    monkeypatch.setattr(_data, "_download_git", forbidden)
    monkeypatch.setattr(_data, "hf_hub_download", forbidden)
    prepared = {
        "archive": str(archive),
        "code": {
            name: str(upstream / name)
            for name in (
                "evaluation/evaluation.py",
                "evaluation/open_spreadsheet.py",
                "SWE-agent/spreadsheet.Dockerfile",
            )
        },
    }
    bench = SpreadsheetBench2(
        {
            "_prepared_spreadsheet": prepared,
            "split_counts": {"train": 1, "dev": 1, "test": 1},
        }
    )
    assert all(len(tasks) == 1 for tasks in bench.load().values())
    assert (Path(bench.test[0].env) / "tests/evaluation.py").read_bytes() == (
        upstream / "evaluation/evaluation.py"
    ).read_bytes()


def test_category_filter_and_cache_tamper(dataset):
    root, _ = dataset
    config = {
        "data_path": root,
        "category": "Template",
        "split": {"train": 1, "dev": 0, "test": 0},
    }
    bench = SpreadsheetBench2(config)
    bench.load()
    assert len(bench.train) == 1
    assert bench.train[0].metadata["category"] == "Template"
    (Path(bench.train[0].env) / "tests/golden.xlsx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="cache changed"):
        SpreadsheetBench2(config).load()


def test_separate_verifier_has_native_build_context(dataset):
    from harbor.environments.definition import require_agent_environment_definition
    from harbor.models.task.task import Task as HarborTask
    from harbor.models.task.verifier_mode import resolve_effective_verifier_env_config
    from harbor.trial.trial import Trial

    root, upstream = dataset
    bench = SpreadsheetBench2(
        {
            "data_path": root,
            "category": "Template",
            "split": {"train": 1, "dev": 0, "test": 0},
        }
    )
    bench.load()
    task = HarborTask(Path(bench.train[0].env))
    # Exercise Harbor's actual separate-verifier context selection, which differs
    # from the agent's environment/ even when both inherit the same config.
    context = Trial._verifier_env_build_context(SimpleNamespace(task=task), None)
    config = resolve_effective_verifier_env_config(task.config, None)
    require_agent_environment_definition(context, docker_image=config.docker_image)
    recipe = (context / "Dockerfile").read_text()
    assert recipe.startswith(
        (upstream / "SWE-agent/spreadsheet.Dockerfile").read_text()
    )
    assert "RUN pip install tqdm" in recipe
    assert "COPY input.xlsx" not in recipe
    # Harbor's separate verifier skips test upload. Only its private image
    # receives /tests; the agent context still contains no golden workbook.
    assert [line for line in recipe.splitlines() if line.startswith("COPY ")] == [
        "COPY . /tests/"
    ]
    assert not (Path(bench.train[0].env) / "environment/golden.xlsx").exists()


@pytest.mark.parametrize("value", ["Visualization", "debugging", None, 2])
def test_unsupported_categories_fail(value):
    with pytest.raises(ValueError, match="Visualization is not supported"):
        SpreadsheetBench2({"category": value})


def test_no_implicit_train_and_unsafe_data_path(dataset):
    root, _ = dataset
    with pytest.raises(ValueError, match="No experiment role"):
        SpreadsheetBench2({"data_path": root}).load()
    path = root / "Template/dataset.json"
    rows = json.loads(path.read_text())
    rows[0]["spreadsheet_path"] = "../outside.xlsx"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="relative path"):
        SpreadsheetBench2({"data_path": root, "category": "Template"}).load()


def test_host_reward_and_task_identity(dataset):
    root, _ = dataset
    bench = SpreadsheetBench2(
        {
            "data_path": root,
            "category": "Template",
            "split": {"train": 0, "dev": 0, "test": 1},
        }
    )
    bench.load()
    task = bench.test[0]
    trajectory = Trajectory(
        task=task,
        messages=(
            {
                "type": "HarborVerifier",
                "task_id": task.task_id,
                "task_checksum": task.metadata["task_checksum"],
                "rewards": {"reward": 1.0},
            },
        ),
    )
    assert bench.grade((trajectory,))[0].metrics == {"reward": 1.0}
    with pytest.raises(ValueError, match="loaded benchmark Task"):
        bench.grade((replace(trajectory, task=replace(task, question="other")),))
    with pytest.raises(ValueError, match="final HarborVerifier"):
        bench.grade((replace(trajectory, messages=()),))


@pytest.mark.parametrize("success", [True, False])
def test_native_recalculation_cannot_silently_fail(tmp_path, monkeypatch, success):
    file = tmp_path / "input.xlsx"
    file.write_bytes(b"original")
    stopped = []

    def batch(files):
        if success:
            Path(files[0]).write_bytes(b"recalculated")

    monkeypatch.setitem(
        sys.modules,
        "open_spreadsheet",
        SimpleNamespace(
            start_libreoffice_service=lambda: True,
            batch_open_files=batch,
            stop_libreoffice_service=lambda: stopped.append(True),
        ),
    )
    if success:
        _recalculate.recalculate([file])
        assert file.read_bytes() == b"recalculated"
    else:
        with pytest.raises(RuntimeError, match="recalculation failed"):
            _recalculate.recalculate([file])
    assert stopped == [True]


def test_launcher_registration_and_cruxeval_removal():
    assert "cruxeval_output" not in _BENCHMARKS
    assert "cruxeval_output" not in _launch._BENCHMARK_EXTRAS
    assert _BENCHMARKS["spreadsheetbench2"] is SpreadsheetBench2
    assert "spreadsheetbench2" in _HARBOR
    config = load_config(
        overrides={
            "benchmark": {"name": "spreadsheetbench2"},
            "agent": {"llm": {"model_name": "test"}},
            "algorithm": {"worker": {"llm": {"model_name": "test"}}},
        }
    )
    plan = _launch._plan(config)
    assert "harbor" in plan["extras"]
    assert "Docker Compose" in plan["prerequisites"]


@pytest.mark.parametrize("has_output", [True, False])
def test_verifier_invokes_native_grader_and_maps_rewards(
    tmp_path, monkeypatch, has_output
):
    row = {
        "id": "01",
        "spreadsheet_path": "Color_input.xlsx",
        "golden_response_path": "gold.xlsx",
        "answer_position": "Sheet!A1:B2",
    }
    (tmp_path / "record.json").write_text(
        json.dumps({"row": row, "category": "Debugging"})
    )
    for name in ("Color_input.xlsx", "gold.xlsx"):
        (tmp_path / name).write_bytes(b"original")
    output = tmp_path / "logs/artifacts/01_output.xlsx"
    output.parent.mkdir(parents=True)
    if has_output:
        output.write_bytes(b"answer")
    recalculated = []
    monkeypatch.setitem(
        sys.modules,
        "_recalculate",
        SimpleNamespace(recalculate=lambda files: recalculated.extend(files)),
    )

    def grade(data, dataset, outputs, turns, category):
        assert data == row and dataset == str(tmp_path)
        assert outputs == str(output.parent) and turns == {} and category == "Debugging"
        return {
            "accuracy": int(has_output),
            "regression_accuracy": 0.75,
            "modification_accuracy": 0.5,
        }, not has_output

    monkeypatch.setitem(
        sys.modules, "evaluation", SimpleNamespace(process_single_item=grade)
    )
    spec = importlib.util.spec_from_file_location(
        "verifier_fixture", Path(_data.__file__).with_name("_verify.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "_verify.py"))
    monkeypatch.setattr(
        module,
        "Path",
        lambda p: tmp_path / p.lstrip("/") if str(p).startswith("/logs/") else Path(p),
    )
    module.main()
    assert recalculated == [
        tmp_path / "Color_input.xlsx",
        tmp_path / "gold.xlsx",
        *([output] if has_output else []),
    ]
    reward = json.loads((tmp_path / "logs/verifier/reward.json").read_text())
    assert reward == {
        "reward": int(has_output),
        "regression_accuracy": 0.75,
        "modification_accuracy": 0.5,
    }
