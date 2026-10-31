"""Terminal 2.1 uses its tasks subdirectory; historical 2.0 stays pinned."""

import pytest

from flashrsi.benchmarks.terminal_bench import TerminalBench, _data


@pytest.mark.parametrize("value", [2.1, "2.2", None])
def test_invalid_version(value):
    with pytest.raises(ValueError, match="version"):
        TerminalBench({"version": value})


@pytest.mark.parametrize("version,subdir", [("2.0", "."), ("2.1", "tasks")])
def test_version_download_path(tmp_path, monkeypatch, version, subdir):
    pytest.importorskip("harbor")
    task = tmp_path / subdir / "example"
    (task / "environment").mkdir(parents=True)
    (task / "task.toml").write_text('version = "1.0"\n')
    (task / "instruction.md").write_text("Task")
    (task / "environment/Dockerfile").write_text("FROM ubuntu:24.04\n")
    (task / "tests").mkdir()
    (task / "tests/test.sh").write_text("#!/bin/bash\ntrue\n")
    calls = []

    def download(*args):
        calls.append(args)
        return tmp_path

    monkeypatch.setattr(_data, "_download_git", download)
    bench = TerminalBench(
        {"version": version, "split_counts": {"train": 0, "dev": 0, "test": 1}}
    )
    bench.load()
    assert bench.test[0].task_id == "example"
    assert calls == [(bench.metadata["source"], bench.metadata["revision"], [subdir])]
    assert bench.metadata["version"] == version
    assert TerminalBench({}).metadata["version"] == "2.0"
