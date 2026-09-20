import asyncio
import copy
import hashlib
import json
import random
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flashrsi.core import Task, Trajectory
from scripts import run_searchqa_experiment as runner


def _source(tmp_path, *, duplicate=None):
    source = tmp_path / "source"
    source.mkdir()
    split_rows = {
        name: [
            {
                "id": f"{name}-{index}",
                "question": f"Question {index}?",
                "context": f"The answer is Paris. Evidence {index}.",
                "answers": ["Paris"],
            }
            for index in range(count)
        ]
        for name, count in zip(
            ("train", "dev", "test"), runner.PROFILES["full"]["counts"], strict=True
        )
    }
    if duplicate is not None:
        train_chosen = random.Random(42).sample(range(len(split_rows["train"])), 4)
        dev_chosen = random.Random(42).sample(range(len(split_rows["dev"])), 4)
        if duplicate == "same_split":
            split_rows["train"][train_chosen[1]]["id"] = split_rows["train"][
                train_chosen[0]
            ]["id"]
        elif duplicate == "across_splits":
            split_rows["dev"][dev_chosen[0]]["id"] = split_rows["train"][
                train_chosen[0]
            ]["id"]
        else:
            unseen_train = next(i for i in range(400) if i not in train_chosen)
            unseen_dev = next(i for i in range(200) if i not in dev_chosen)
            split_rows["dev"][unseen_dev]["id"] = split_rows["train"][unseen_train][
                "id"
            ]
    manifest = {"splits": {}}
    for name, rows in split_rows.items():
        path = source / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        manifest["splits"][name] = {
            "count": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source, split_rows


@pytest.mark.parametrize("profile", ["smoke", "pilot", "full"])
def test_prepare_data_preserves_membership_counts_hashes_and_fixed_sampling(
    tmp_path, profile
):
    source, split_rows = _source(tmp_path)
    destination = tmp_path / "prepared"
    result = runner._prepare_data(source, destination, profile)
    assert result == runner._prepare_data(source, destination, profile)
    for name, count in zip(
        ("train", "dev", "test"), runner.PROFILES[profile]["counts"], strict=True
    ):
        indices = sorted(random.Random(42).sample(range(len(split_rows[name])), count))
        expected = [split_rows[name][index] for index in indices]
        path = destination / f"{name}.jsonl"
        assert [json.loads(line) for line in path.read_text().splitlines()] == expected
        assert result["selected"][name] == {
            "count": count,
            "source_sha256": hashlib.sha256(
                (source / f"{name}.parquet").read_bytes()
            ).hexdigest(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "ids": [row["id"] for row in expected],
        }


def test_prepare_data_rejects_source_hash_mismatch(tmp_path):
    source, _ = _source(tmp_path)
    with (source / "train.parquet").open("ab") as stream:
        stream.write(b"modified source")
    with pytest.raises(ValueError, match="checksum mismatch"):
        runner._prepare_data(source, tmp_path / "prepared", "smoke")


def test_prepare_data_rejects_source_count_and_existing_output_mismatch(tmp_path):
    source, _ = _source(tmp_path)
    destination = tmp_path / "prepared"
    runner._prepare_data(source, destination, "smoke")
    (destination / "train.jsonl").write_text("changed prepared data\n")
    with pytest.raises(ValueError, match="Prepared data changed"):
        runner._prepare_data(source, destination, "smoke")
    path = source / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["splits"]["train"]["count"] += 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="count mismatch"):
        runner._prepare_data(source, tmp_path / "another", "smoke")


@pytest.mark.parametrize("duplicate", ["same_split", "across_splits", "unselected"])
def test_prepare_data_rejects_duplicate_ids_before_sampling(tmp_path, duplicate):
    source, _ = _source(tmp_path, duplicate=duplicate)
    with pytest.raises(ValueError, match="overlap|duplicate"):
        runner._prepare_data(source, tmp_path / "prepared", "smoke")


def _scored(task_id, score):
    return Trajectory(task=Task(task_id, "Question?"), metrics={"hard": score})


@pytest.mark.parametrize("after_ids", [["a"], ["b", "a"], ["a", "c"]])
def test_paired_rejects_missing_reordered_or_changed_ids(after_ids):
    before = tuple(_scored(task_id, 0) for task_id in ("a", "b"))
    after = tuple(_scored(task_id, 1) for task_id in after_ids)
    with pytest.raises(ValueError, match="task IDs differ"):
        runner._paired(before, after)


def test_paired_reports_paired_change_and_reproducible_interval():
    before = tuple(_scored(str(i), score) for i, score in enumerate((0, 0, 1, 1)))
    after = tuple(_scored(str(i), score) for i, score in enumerate((1, 1, 0, 1)))
    result = runner._paired(before, after)
    assert result == runner._paired(before, after)
    assert result["delta_percentage_points"] == 25.0
    assert result["improved_tasks"] == 2
    assert result["regressed_tasks"] == 1
    low, high = result["paired_bootstrap_95pct_pp"]
    assert low <= 25 <= high


@pytest.fixture
def credential_file(tmp_path, monkeypatch):
    for name in ("FLASHRSI_BASE_URL", "FLASHRSI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "credentials.env"
    path.write_text(
        "# Offline test credentials, never usable at a provider.\n"
        "FLASHRSI_BASE_URL='http://127.0.0.1:9/v1/'\n"
        'FLASHRSI_API_KEY="offline-test-key"\n'
    )
    path.chmod(0o600)
    return path


def test_credentials_reads_private_file_and_environment_overrides(
    credential_file, monkeypatch
):
    assert runner._credentials(credential_file) == {
        "FLASHRSI_BASE_URL": "http://127.0.0.1:9/v1",
        "FLASHRSI_API_KEY": "offline-test-key",
    }
    monkeypatch.setenv("FLASHRSI_BASE_URL", "http://127.0.0.1:8/v1/")
    monkeypatch.setenv("FLASHRSI_API_KEY", "offline-environment-key")
    assert runner._credentials(credential_file) == {
        "FLASHRSI_BASE_URL": "http://127.0.0.1:8/v1",
        "FLASHRSI_API_KEY": "offline-environment-key",
    }


def test_credentials_rejects_shared_permissions_without_exposing_value(credential_file):
    credential_file.chmod(0o644)
    with pytest.raises(ValueError, match="0600") as caught:
        runner._credentials(credential_file)
    assert "offline-test-key" not in str(caught.value)


def test_credentials_supports_environment_only_and_rejects_missing(
    credential_file, monkeypatch
):
    credential_file.unlink()
    with pytest.raises(ValueError, match="Set FLASHRSI_BASE_URL"):
        runner._credentials(credential_file)
    monkeypatch.setenv("FLASHRSI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("FLASHRSI_API_KEY", "offline-environment-key")
    assert (
        runner._credentials(credential_file)["FLASHRSI_API_KEY"]
        == "offline-environment-key"
    )


@pytest.mark.parametrize("execute", [False, True])
def test_main_with_fake_models_tests_only_after_selection_on_same_holdout(
    tmp_path, monkeypatch, credential_file, execute
):
    source, _ = _source(tmp_path)
    events = []
    roles = []

    class FakeTarget:
        def __init__(self, config):
            self.config = config
            self.snapshot = SimpleNamespace(id=f"initial-{config.name}", files={})
            roles.append((config.name, config.llm.base_url, config.llm.model_name))

        def configure_experiment(self, directory, concurrency):
            assert concurrency == 2
            return self

    class FakeWorker:
        def __init__(self, config):
            roles.append(("evolver", config.llm.base_url, config.llm.model_name))

        def configure_experiment(self, directory):
            return self

    class FakeAlgorithm:
        def __init__(self, config, *, target, worker, benchmark):
            self.config = copy.deepcopy(config)
            self.target = target
            self.benchmark = benchmark
            self.benchmark.load()
            self.evolved = False

        async def evolve(self):
            self.evolved = True
            events.append((self.target.config.name, "evolved", ()))
            return SimpleNamespace(
                id=f"final-{self.target.config.name}",
                files={
                    "skills/main.md": SimpleNamespace(
                        component="skill", content=b"Final skill\n"
                    )
                },
            )

        async def _evaluate(self, snapshot, tasks, *, label):
            assert self.evolved
            assert tuple(tasks) == self.benchmark.test
            assert snapshot.id.startswith(
                "initial-" if label == "initial-test" else "final-"
            )
            events.append(
                (self.target.config.name, label, tuple(t.task_id for t in tasks))
            )
            return self.benchmark.grade(
                tuple(
                    Trajectory(
                        task=task,
                        output="wrong" if label == "initial-test" else "Paris",
                    )
                    for task in tasks
                )
            )

    monkeypatch.setattr(runner, "CachedMiniAgent", FakeTarget)
    monkeypatch.setattr(runner, "CachedClaudeCode", FakeTarget)
    monkeypatch.setattr(runner, "CachedLLM", FakeWorker)
    monkeypatch.setattr(runner, "SkillOpt", FakeAlgorithm)
    args = SimpleNamespace(
        env_file=credential_file,
        data_source=source,
        run_root=tmp_path / "runs",
        profile="smoke",
        harness=["miniagent", "claude_code"],
        concurrency=2,
        execute=execute,
    )
    asyncio.run(runner._main(args))
    results = json.loads((args.run_root / "smoke/summary.json").read_text())
    assert len(results) == 2
    if execute:
        assert [event[1] for event in events] == [
            "evolved",
            "initial-test",
            "final-test",
        ] * 2
        assert events[1][2] == events[2][2] == events[4][2] == events[5][2]
        assert len(events[1][2]) == 8
        for result in results:
            assert result["status"] == "finished"
            assert result["test_used_for_selection"] is False
            assert result["baseline_test"]["hard"] == 0
            assert result["evolved_test"]["hard"] == 1
            assert result["paired_comparison"]["delta_percentage_points"] == 100
        for harness in args.harness:
            summary = json.loads(
                (args.run_root / "smoke" / harness / "end-summary.json").read_text()
            )
            assert summary["result"]["status"] == "finished"
            assert summary["result"]["evolved_test"]["hard"] == 1
            assert summary["models"]["target"] == "deepseek-v4-flash"
        # A completed run is returned without running evolution or holdout again.
        asyncio.run(runner._main(args))
        assert len(events) == 6
    else:
        assert events == []
        assert all(result["status"] == "prepared" for result in results)
    assert ("miniagent", "http://127.0.0.1:9/v1", "deepseek-v4-flash") in roles
    assert ("claude_code", "http://127.0.0.1:9", "deepseek-v4-flash") in roles
    assert ("evolver", "http://127.0.0.1:9/v1", "deepseek-v4-pro") in roles
    for path in args.run_root.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".yaml"}:
            assert "offline-test-key" not in path.read_text()
