import asyncio
import hashlib
import io
import json
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.benchmarks import TerminalBench
from flashrsi.benchmarks import _archive as data_module
from flashrsi.benchmarks import terminal_bench as module
from flashrsi.core import Task, Trajectory


@pytest.fixture
def harbor():
    return pytest.importorskip("harbor.models.task.task")


def _task_dir(root, name="one", *, extra_config=""):
    directory = root / name
    (directory / "environment").mkdir(parents=True)
    (directory / "tests").mkdir()
    (directory / "solution").mkdir()
    (directory / "task.toml").write_text(
        'version = "1.0"\n'
        '[metadata]\ncategory = "software-engineering"\ndifficulty = "easy"\n'
        + extra_config
    )
    (directory / "instruction.md").write_text(
        "<!-- benchmark canary: do not train on this -->\n\n"
        f"Create /work/{name}.txt with the requested contents.\n"
    )
    (directory / "environment/Dockerfile").write_text("FROM scratch\nWORKDIR /work\n")
    (directory / "tests/test.sh").write_text(
        "#!/bin/sh\necho 0 > /logs/verifier/reward.txt\n"
    )
    (directory / "solution/solve.sh").write_text("ORACLE-SOLUTION-PRIVATE\n")
    return directory


def _single_config(path):
    return {"data_path": path, "split": {"train": 1, "dev": 0, "test": 0}}


def test_local_task_uses_native_instruction_checksum_and_no_oracle(tmp_path, harbor):
    directory = _task_dir(tmp_path)
    benchmark = TerminalBench(_single_config(directory))

    (task,) = benchmark.load()["train"]

    assert benchmark.load() is benchmark.load()
    assert benchmark.dev == benchmark.test == ()
    assert task.task_id == "one"
    assert task.env == str(directory.resolve())
    assert task.question == "Create /work/one.txt with the requested contents.\n"
    assert task.ground_truth is None
    assert "ORACLE-SOLUTION-PRIVATE" not in repr(task)
    assert task.metadata["source_split"] == "unassigned"
    assert task.metadata["category"] == "software-engineering"
    assert benchmark.metadata == {"source": "local", "data_path": str(directory)}
    with pytest.warns(DeprecationWarning):
        assert task.metadata["task_checksum"] == harbor.Task(directory).checksum

    (directory / "tests/test.sh").write_text("changed native test\n")
    changed = TerminalBench(_single_config(directory)).load()["train"][0]
    assert changed.metadata["task_checksum"] != task.metadata["task_checksum"]


def test_flat_directory_uses_reproducible_disjoint_splits_and_limit(tmp_path, harbor):
    for index in range(9):
        _task_dir(tmp_path, f"task-{index}")
    full = TerminalBench({"data_path": tmp_path, "seed": 11}).load()
    limited = TerminalBench({"data_path": tmp_path, "seed": 11, "limit": 3}).load()
    repeated = TerminalBench({"data_path": tmp_path, "seed": 11}).load()

    assert full == repeated
    assert [len(full[name]) for name in ("train", "dev", "test")] == [5, 2, 2]
    assert len({task.task_id for tasks in full.values() for task in tasks}) == 9
    for name in full:
        assert len(limited[name]) == 1
        assert limited[name][0] in full[name]


def test_single_task_auto_requires_explicit_partition(tmp_path, harbor):
    directory = _task_dir(tmp_path)
    with pytest.raises(ValueError, match="enough training/unassigned tasks"):
        TerminalBench({"data_path": directory}).load()


def test_duplicate_native_task_ids_are_rejected(tmp_path, harbor):
    for name in ("one", "two", "three"):
        _task_dir(tmp_path, name, extra_config='[task]\nname = "example/shared"\n')
    with pytest.raises(ValueError, match="duplicate task id"):
        TerminalBench({"data_path": tmp_path}).load()


@pytest.mark.parametrize("kind", ["windows", "steps"])
def test_non_linux_or_multistep_tasks_are_rejected(tmp_path, harbor, kind):
    extra = (
        '[environment]\nos = "windows"\n'
        if kind == "windows"
        else '[[steps]]\nname = "first"\n'
    )
    directory = _task_dir(tmp_path, extra_config=extra)
    if kind == "windows":
        (directory / "tests/test.bat").write_text("@echo test\n")
    else:
        (directory / "steps/first").mkdir(parents=True)
        (directory / "steps/first/instruction.md").write_text("Do the first step.\n")
    with pytest.raises(ValueError, match="single-step Linux"):
        TerminalBench(_single_config(directory)).load()


def test_native_task_validation_rejects_missing_verifier(tmp_path, harbor):
    directory = _task_dir(tmp_path)
    (directory / "tests/test.sh").unlink()
    with pytest.raises(FileNotFoundError, match="test.sh"):
        TerminalBench(_single_config(directory)).load()


@pytest.mark.parametrize("data_path", [False, "", [], "missing"])
def test_bad_local_source_rejected_without_downloading(
    monkeypatch, tmp_path, data_path
):
    monkeypatch.setattr(
        module, "_download_tasks", lambda: pytest.fail("unexpected fetch")
    )
    if data_path == "missing":
        data_path = tmp_path / "missing"
    with pytest.raises(ValueError, match="data_path"):
        TerminalBench({"data_path": data_path}).load()


def test_empty_local_directory_and_missing_optional_dependency(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="no native tasks"):
        TerminalBench({"data_path": tmp_path}).load()
    directory = _task_dir(tmp_path)
    monkeypatch.setitem(sys.modules, "harbor.models.task.task", None)
    with pytest.raises(ValueError, match=r"flashrsi-lite\[harbor\]"):
        TerminalBench(_single_config(directory)).load()


@pytest.fixture
def hf_dataset(monkeypatch, tmp_path, harbor):
    directories = [_task_dir(tmp_path / "native", f"task-{i}") for i in range(3)]
    for directory in directories:
        (directory / "tests/test.sh").chmod(0o755)
    archive_path = tmp_path / "tasks.tar.gz"
    with tarfile.open(archive_path, "w:gz") as stream:
        for directory in directories:
            stream.add(directory, arcname=directory.name)
    manifest = {
        "schema": "flashrsi.terminal_bench.v1",
        "source": dict(TerminalBench.metadata["upstream"]),
        "archive": {
            "file": "terminal_bench/tasks.tar.gz",
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "bytes": archive_path.stat().st_size,
        },
        "index": {
            "file": "terminal_bench/tasks.parquet",
            "sha256": "0" * 64,
            "count": len(directories),
        },
        "tasks": [],
    }
    for directory in directories:
        with pytest.warns(DeprecationWarning):
            checksum = harbor.Task(directory).checksum
        manifest["tasks"].append(
            {"id": directory.name, "path": directory.name, "task_checksum": checksum}
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    cache = tmp_path / "hf_home"
    monkeypatch.setattr(data_module.constants, "HF_HOME", str(cache))
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return str(
            {
                "terminal_bench/manifest.json": manifest_path,
                "terminal_bench/tasks.tar.gz": archive_path,
            }[kwargs["filename"]]
        )

    monkeypatch.setattr(data_module, "hf_hub_download", download)
    return SimpleNamespace(
        manifest=manifest,
        manifest_path=manifest_path,
        archive=archive_path,
        cache=cache / "flashrsi/terminal_bench",
        calls=calls,
    )


def test_hf_download_pins_revision_preserves_native_files_and_uses_default_auth(
    hf_dataset,
):
    benchmark = TerminalBench({})

    async def inside_existing_loop():
        return benchmark.load()

    splits = asyncio.run(inside_existing_loop())
    assert hf_dataset.calls == [
        {
            "repo_id": "jinjiajie/flashrsi",
            "repo_type": "dataset",
            "revision": module._REVISION,
            "filename": filename,
        }
        for filename in ("terminal_bench/manifest.json", "terminal_bench/tasks.tar.gz")
    ]
    assert benchmark.load() is splits
    for tasks in splits.values():
        for task in tasks:
            assert task.metadata["source"] == {
                **benchmark.metadata,
                "path": task.task_id,
            }
            assert task.metadata["source_split"] == "unassigned"
            assert Path(task.env).is_relative_to(hf_dataset.cache)
            assert (Path(task.env) / "tests/test.sh").stat().st_mode & 0o777 == 0o755
            assert (Path(task.env) / "solution/solve.sh").read_text() == (
                "ORACLE-SOLUTION-PRIVATE\n"
            )
    assert benchmark.metadata["revision"] == module._REVISION
    assert benchmark.metadata["upstream"]["revision"] == module._UPSTREAM_REVISION
    assert benchmark.metadata["config"] == "terminal_bench"


def test_hf_cache_is_reused_across_benchmark_instances(hf_dataset, monkeypatch):
    splits = TerminalBench({}).load()
    monkeypatch.setattr(
        data_module,
        "_extract",
        lambda *args: pytest.fail("unexpected extraction"),
    )
    assert TerminalBench({}).load() == splits
    assert [call["filename"] for call in hf_dataset.calls] == [
        "terminal_bench/manifest.json",
        "terminal_bench/tasks.tar.gz",
        "terminal_bench/manifest.json",
    ]


def test_concurrent_loads_share_one_complete_extraction(hf_dataset):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: TerminalBench({}).load(), range(2)))
    assert results[0] == results[1]
    assert (
        sum(
            call["filename"] == "terminal_bench/tasks.tar.gz"
            for call in hf_dataset.calls
        )
        == 1
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (("schema",), "unknown"),
        (("source", "revision"), "a" * 40),
        (("source", "git_url"), "https://example.com/repo"),
        (("archive", "file"), "../tasks.tar.gz"),
        (("archive", "sha256"), "wrong"),
        (("archive", "bytes"), 0),
        (("index", "count"), 99),
        (("tasks",), []),
        (("tasks", 0, "path"), "../task-0"),
        (("tasks", 0, "id"), "../task-0"),
        (("tasks", 0, "task_checksum"), "wrong"),
    ],
)
def test_bad_manifest_is_rejected_before_archive_download(hf_dataset, field, value):
    container = hf_dataset.manifest
    for key in field[:-1]:
        container = container[key]
    container[field[-1]] = value
    hf_dataset.manifest_path.write_text(json.dumps(hf_dataset.manifest))

    with pytest.raises(ValueError, match="manifest"):
        TerminalBench({}).load()
    assert len(hf_dataset.calls) == 1


def test_duplicate_manifest_tasks_are_rejected(hf_dataset):
    hf_dataset.manifest["tasks"][1] = hf_dataset.manifest["tasks"][0]
    hf_dataset.manifest_path.write_text(json.dumps(hf_dataset.manifest))
    with pytest.raises(ValueError, match="duplicate"):
        TerminalBench({}).load()
    assert len(hf_dataset.calls) == 1


def test_download_checksum_is_verified_before_extraction(hf_dataset):
    with hf_dataset.archive.open("ab") as stream:
        stream.write(b"corrupted download")
    with pytest.raises(ValueError, match="checksum or size mismatch"):
        TerminalBench({}).load()
    assert not any(path.is_dir() for path in hf_dataset.cache.iterdir())


@pytest.mark.parametrize(
    "kind",
    ["traversal", "absolute", "symlink", "hardlink", "fifo", "extra", "duplicate"],
)
def test_unsafe_archive_is_rejected_and_partial_extraction_removed(hf_dataset, kind):
    with tarfile.open(hf_dataset.archive, "w:gz") as stream:
        first = tarfile.TarInfo("task-0/first.txt")
        first.size = 2
        stream.addfile(first, io.BytesIO(b"ok"))
        name = {
            "traversal": "task-0/../../escaped",
            "absolute": str(hf_dataset.cache.parent / "escaped"),
            "extra": "unlisted-task/file",
            "duplicate": first.name,
        }.get(kind, "task-0/unsafe")
        member = tarfile.TarInfo(name)
        member.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "fifo": tarfile.FIFOTYPE,
        }.get(kind, tarfile.REGTYPE)
        member.linkname = "../../escaped"
        stream.addfile(member)
    hf_dataset.manifest["archive"].update(
        sha256=hashlib.sha256(hf_dataset.archive.read_bytes()).hexdigest(),
        bytes=hf_dataset.archive.stat().st_size,
    )
    hf_dataset.manifest_path.write_text(json.dumps(hf_dataset.manifest))

    with pytest.raises(ValueError, match="Unsafe.*archive member"):
        TerminalBench({}).load()
    assert not (hf_dataset.cache.parent / "escaped").exists()
    assert not any(path.is_dir() for path in hf_dataset.cache.iterdir())


@pytest.mark.parametrize("kind", ["contents", "missing-task", "symlink", "extra-task"])
def test_damaged_cache_is_rejected_without_redownloading(hf_dataset, kind):
    splits = TerminalBench({}).load()
    task_directory = Path(splits["train"][0].env)
    if kind == "contents":
        (task_directory / "instruction.md").write_text("Changed task instruction")
    elif kind == "missing-task":
        task_directory.rename(task_directory.with_name("renamed"))
    elif kind == "symlink":
        (task_directory / "unexpected-link").symlink_to(hf_dataset.manifest_path)
    else:
        (task_directory.parent / "extra-task").mkdir()
    hf_dataset.calls.clear()

    with pytest.raises(ValueError, match="cached task|task cache"):
        TerminalBench({}).load()
    assert [call["filename"] for call in hf_dataset.calls] == [
        "terminal_bench/manifest.json"
    ]


def test_native_checksum_must_match_manifest(hf_dataset):
    hf_dataset.manifest["tasks"][0]["task_checksum"] = "f" * 64
    hf_dataset.manifest_path.write_text(json.dumps(hf_dataset.manifest))
    with pytest.raises(ValueError, match="cached task does not match its manifest"):
        TerminalBench({}).load()


@pytest.fixture
def loaded(monkeypatch):
    task = Task(
        "one", "Do the task", env="/native/one", metadata={"task_checksum": "abc"}
    )
    benchmark = TerminalBench({"split": {"train": 1, "dev": 0, "test": 0}})
    monkeypatch.setattr(benchmark, "_iter_tasks", lambda: iter((task,)))
    benchmark.load()
    return benchmark, task


def _event(task, reward=1.0):
    return {
        "type": "HarborVerifier",
        "task_id": task.task_id,
        "task_checksum": task.metadata["task_checksum"],
        "rewards": {"reward": reward},
    }


def test_grade_uses_host_verifier_and_preserves_records(loaded):
    benchmark, task = loaded
    original = Trajectory(
        task=task,
        output=json.dumps({"reward": 1.0, "success": True}),
        messages=(
            _event(task, 1),
            {"role": "assistant", "content": "pass"},
            _event(task, 0),
        ),
        metrics={"reward": 1.0, "latency": 3.5},
        usage={"input_tokens": 10},
    )
    failed = replace(original, status="error", error_message="Verifier timed out")
    successful = replace(original, messages=(_event(task, 1),))

    graded = benchmark.grade((original, failed, successful))

    assert [item.metrics["reward"] for item in graded] == [0.0, 0.0, 1.0]
    assert original.metrics["reward"] == 1.0
    assert graded[0] is not original
    assert graded[0].metrics["latency"] == 3.5
    assert graded[0].task is task
    assert graded[0].messages == original.messages
    assert graded[0].output == original.output
    assert graded[0].usage == original.usage
    assert graded[1].error_message == failed.error_message


@pytest.mark.parametrize(
    "value", [None, True, "1", [], float("nan"), float("inf"), -1, 2]
)
def test_finished_trajectory_requires_valid_numeric_reward(loaded, value):
    benchmark, task = loaded
    with pytest.raises(ValueError, match="finite number between 0 and 1"):
        benchmark.grade((Trajectory(task=task, messages=(_event(task, value),)),))


@pytest.mark.parametrize("kind", ["missing", "not-last", "task", "checksum", "rewards"])
def test_finished_trajectory_requires_bound_final_verifier_event(loaded, kind):
    benchmark, task = loaded
    event = _event(task)
    messages = (event,)
    if kind == "missing":
        messages = ()
    elif kind == "not-last":
        messages = (event, {"role": "assistant", "content": "reward: 1"})
    elif kind == "task":
        event["task_id"] = "other"
    elif kind == "checksum":
        event["task_checksum"] = "another-native-task"
    else:
        event["rewards"] = "reward: 1"
    with pytest.raises(ValueError):
        benchmark.grade(
            (Trajectory(task=task, messages=messages, metrics={"reward": 1}),)
        )


def test_error_trajectory_does_not_require_verifier_output(loaded):
    benchmark, task = loaded
    error = Trajectory(task=task, status="error", error_message="Container failed")
    assert benchmark.grade((error,))[0].metrics["reward"] == 0.0


def test_grading_requires_loaded_task_identity(loaded):
    benchmark, task = loaded
    for wrong in (
        None,
        replace(task, task_id="other"),
        replace(task, question="different"),
    ):
        with pytest.raises(ValueError, match="loaded benchmark Task"):
            benchmark.grade((Trajectory(task=wrong, messages=(_event(task),)),))
    with pytest.raises(RuntimeError, match=r"call load\(\) first"):
        TerminalBench({}).grade(())
