"""Memory survives fresh Python processes without changing versioned resources."""

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from types import SimpleNamespace

import pytest
from test_codex_core_parity import _events, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_python_memory import _call

from flashrsi.agents import Codex
from flashrsi.agents.codex._python import _memory_overlay, _save_memory


def _memory_agent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    files = tmp_path / "export"
    files.mkdir()
    store = tmp_path / "runtime-memory"
    store.mkdir()
    return SimpleNamespace(
        config={"source_dir": source, "memory_dir": store},
        files_dir=files,
        snapshot=SimpleNamespace(id="a" * 64),
    )


def test_snapshot_memory_directory_rejects_symlinks_on_load_and_save(tmp_path):
    agent = _memory_agent(tmp_path)
    source = agent.config["source_dir"]
    baseline = source / "baseline.md"
    baseline.write_text("immutable Snapshot resource")
    scoped = agent.config["memory_dir"] / agent.snapshot.id
    scoped.symlink_to(source, target_is_directory=True)
    home = tmp_path / "home"

    with pytest.raises(ValueError, match="memory directory.*symlink"):
        _memory_overlay(agent, home)
    assert not home.exists()

    scoped.unlink()
    overlay = _memory_overlay(agent, home)
    notes = overlay[1]
    notes.mkdir(parents=True)
    filename = "2026-10-28T12-34-56-new.md"
    (notes / filename).write_text("new runtime note")
    # A directory replaced after loading must also be rejected at persistence.
    scoped.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="memory directory.*symlink"):
        _save_memory(overlay)
    assert baseline.read_text() == "immutable Snapshot resource"
    assert not (source / filename).exists()


def test_parallel_identical_notes_publish_complete_bytes_without_conflicts(
    tmp_path, monkeypatch
):
    agent = _memory_agent(tmp_path)
    overlays = [_memory_overlay(agent, tmp_path / name) for name in ("first", "second")]
    filename = "2026-10-28T12-34-56-shared.md"
    data = b"Both rollouts produced the same complete memory note.\n" * 200
    for _, notes in overlays:
        notes.mkdir(parents=True)
        (notes / filename).write_bytes(data)

    started, resume = Event(), Event()
    state = local()
    original_open = io.open

    class PausedWriter:
        def __init__(self, file):
            self.file = file

        def __getattr__(self, name):
            return getattr(self.file, name)

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def write(self, content):
            middle = len(content) // 2
            self.file.write(content[:middle])
            self.file.flush()
            started.set()
            if not resume.wait(10):
                raise TimeoutError("parallel memory writer did not resume")
            self.file.write(content[middle:])
            return len(content)

    def paused_open(file, mode="r", *args, **kwargs):
        result = original_open(file, mode, *args, **kwargs)
        if getattr(state, "pause", False) and "b" in mode and set(mode) & {"w", "x"}:
            return PausedWriter(result)
        return result

    def first_save():
        state.pause = True
        _save_memory(overlays[0])

    monkeypatch.setattr(io, "open", paused_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_save)
        try:
            assert started.wait(10), "first writer never reached its partial write"
            # A fresh rollout must not import the first writer's staged prefix.
            before = _memory_overlay(agent, tmp_path / "before-publication")[1]
            before_data = (
                (before / filename).read_bytes()
                if (before / filename).exists()
                else None
            )
            second = pool.submit(_save_memory, overlays[1])
            second_error = second.exception(timeout=10)
            after = _memory_overlay(agent, tmp_path / "after-publication")[1]
            after_data = (
                (after / filename).read_bytes() if (after / filename).exists() else None
            )
        finally:
            resume.set()
        first.result(timeout=10)

    assert before_data is None
    assert second_error is None
    assert after_data == data
    scoped = agent.config["memory_dir"] / agent.snapshot.id
    assert sorted(path.name for path in scoped.iterdir()) == [filename]
    assert (scoped / filename).read_bytes() == data
    assert sorted(path.name for path in scoped.parent.iterdir()) == [agent.snapshot.id]


def test_notes_persist_outside_snapshot_and_candidates_are_isolated(
    parity_source, tmp_path
):
    config = parity_source / "config.toml"
    config.write_text(
        config.read_text() + "memories=true\n[memories]\ndedicated_tools=true\n"
    )
    store = tmp_path / "runtime-memory"
    filename = "2026-10-28T12-34-56-persist.md"
    note_path = "extensions/ad_hoc/notes/" + filename
    with _responses_server() as replay:
        agent = Codex(
            {
                "source_dir": parity_source,
                "memory_dir": str(store),
                "sandbox": "danger-full-access",
                "timeout": 30,
                "llm": {
                    "model_name": "gpt-5.4",
                    "api_key": "local-key",
                    "base_url": replay.base_url,
                },
            }
        )
        agent.set_scope({"prompt": "rw"})
        baseline = agent.snapshot
        replay.reset(
            [
                (
                    200,
                    _call(
                        "add_ad_hoc_note",
                        {"filename": filename, "note": "PERSIST_ACROSS_FRESH_PROCESS"},
                        0,
                    ),
                ),
                (200, _events("SAVED")),
            ]
        )
        first = asyncio.run(agent.run("Remember the supplied fact."))
        assert first.status == "finished", first.error_message
        assert (
            store / baseline.id / filename
        ).read_text() == "PERSIST_ACROSS_FRESH_PROCESS"
        assert not (parity_source / "memories/extensions").exists()
        assert agent.snapshot.id == baseline.id

        def read_note():
            replay.reset(
                [(200, _call("read", {"path": note_path}, 1)), (200, _events("READ"))]
            )
            result = asyncio.run(agent.run("Read the saved note."))
            assert result.status == "finished", result.error_message
            assert not replay.errors and not replay.steps
            feedback = replay.requests[1]["body"]["input"][-1]["output"]
            return feedback

        assert "PERSIST_ACROSS_FRESH_PROCESS" in read_note()
        with baseline.check_out() as directory:
            (directory / "AGENTS.md").write_text("CANDIDATE_MEMORY_SCOPE\n")
            candidate = baseline.commit(directory)
        agent.update(candidate)
        assert "PERSIST_ACROSS_FRESH_PROCESS" not in read_note()
        agent.update(baseline)
        assert "PERSIST_ACROSS_FRESH_PROCESS" in read_note()
        assert agent.snapshot.files == baseline.files
