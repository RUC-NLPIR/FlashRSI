"""Check source-bound build publication without invoking a real compiler.

Fake Cargo artifacts identify the staged source they read. Companion acquisition
is mocked to return that fake compiler's host. These tests cover cache correctness
and cancellation, independently of the unmocked native Codex parity tests.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from flashrsi.agents.codex import _build

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixtures")


@pytest.fixture
def compiler(tmp_path, monkeypatch):
    from flashrsi.agents.codex import _companion

    executables = tmp_path / "bin"
    executables.mkdir()
    record = tmp_path / "cargo.jsonl"
    cache = tmp_path / "cache"
    runtime = tmp_path / "runtime"
    (runtime / "src").mkdir(parents=True)
    (runtime / "Cargo.toml").write_text('[workspace]\nmembers = ["bridge"]\n')
    (runtime / "src/behavior.txt").write_text("BASELINE")
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "Cargo.toml").write_text('[package]\nname = "fake-bridge"\n')
    (executables / "rustc").write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "print('rustc ' + os.environ.get('FLASHRSI_BUILD_TEST_RUST_VERSION', '1.95.0'))\n"
        "print('host: fake-test-target')\n"
    )
    (executables / "cargo").write_text(
        f"#!{sys.executable}\nRECORD = {str(record)!r}\n"
        + textwrap.dedent(
            """\
            import json, os, pathlib, signal, subprocess, sys, time

            record = pathlib.Path(RECORD)
            selected = pathlib.Path('src/behavior.txt').read_text()
            child = None
            if selected == 'CANCEL':
                child = subprocess.Popen([
                    sys.executable, '-c', 'import time; time.sleep(30)'
                ])

                def stop(signum, frame):
                    child.wait(timeout=2)
                    record.with_suffix('.cancelled').write_text('stopped')
                    raise SystemExit(0)

                signal.signal(signal.SIGINT, stop)
                signal.signal(signal.SIGTERM, stop)

            entry = {
                'selected': selected,
                'pid': os.getpid(),
                'child_pid': None if child is None else child.pid,
                'files': sorted(str(path) for path in pathlib.Path('.').rglob('*') if path.is_file()),
                'rustflags': os.environ.get('RUSTFLAGS'),
            }
            with record.open('a') as stream:
                stream.write(json.dumps(entry) + '\\n')

            if selected == 'INVALID':
                print('candidate does not compile', file=sys.stderr)
                raise SystemExit(42)
            if selected == 'CANCEL':
                while True:
                    signal.pause()

            target = pathlib.Path(sys.argv[sys.argv.index('--target-dir') + 1])
            profile = 'release' if '--release' in sys.argv else sys.argv[sys.argv.index('--profile') + 1]
            assert profile == 'release', 'Codex must use native release semantics'
            output = target / profile / 'flashrsi-codex-core'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({
                'selected': pathlib.Path('src/behavior.txt').read_text(),
                'rustflags': os.environ.get('RUSTFLAGS'),
            }))
            output.chmod(0o755)
            host = output.with_name('codex-code-mode-host')
            host.write_text('host:' + pathlib.Path('src/behavior.txt').read_text())
            host.chmod(0o755)
            # Without the publication lock B can overwrite the shared artifact
            # before A's Python caller copies it into A's immutable cache.
            if selected == 'CONCURRENT_A':
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    if 'CONCURRENT_B' in record.read_text():
                        break
                    time.sleep(0.01)
            """
        )
    )
    for executable in executables.iterdir():
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(executables) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("RUSTC", str(executables / "rustc"))
    monkeypatch.setenv("FLASHRSI_CODEX_BUILD_CACHE", str(cache))
    monkeypatch.delenv("RUSTFLAGS", raising=False)
    monkeypatch.delenv("CARGO_BUILD_TARGET", raising=False)
    monkeypatch.setattr(_build, "_BRIDGE", bridge)

    async def fake_companion(runtime_dir, workspace, target, cache_root, env):
        return target / "release" / "codex-code-mode-host"

    monkeypatch.setattr(_companion, "prepare_companion", fake_companion)
    return SimpleNamespace(runtime=runtime, bridge=bridge, cache=cache, record=record)


def _records(compiler):
    if not compiler.record.exists():
        return []
    return [json.loads(line) for line in compiler.record.read_text().splitlines()]


def _artifact(path):
    return json.loads(path.read_text())


def test_source_changes_rebuild_and_cache_hits_preserve_the_selected_version(compiler):
    (compiler.runtime / "src/removed.rs").write_text("baseline only\n")
    baseline = asyncio.run(_build.build_core(compiler.runtime))
    repeated = asyncio.run(_build.build_core(compiler.runtime))
    assert repeated == baseline
    assert _artifact(baseline)["selected"] == "BASELINE"
    assert len(_records(compiler)) == 1

    (compiler.runtime / "src/removed.rs").unlink()
    (compiler.runtime / "src/behavior.txt").write_text("CANDIDATE")
    candidate = asyncio.run(_build.build_core(compiler.runtime))
    assert candidate != baseline
    assert _artifact(candidate)["selected"] == "CANDIDATE"
    assert _artifact(baseline)["selected"] == "BASELINE"
    first, second = _records(compiler)
    assert "src/removed.rs" in first["files"]
    assert "src/removed.rs" not in second["files"]
    metadata = json.loads((candidate.parent / "build.json").read_text())
    assert metadata["source_sha256"] == candidate.parent.name
    assert metadata["profile"] == "release"


def test_bridge_changes_invalidate_the_core_build_cache(compiler):
    baseline = asyncio.run(_build.build_core(compiler.runtime))
    (compiler.bridge / "boundary.rs").write_text("changed fixed host boundary\n")
    changed = asyncio.run(_build.build_core(compiler.runtime))
    assert changed != baseline
    assert len(_records(compiler)) == 2
    assert "bridge/boundary.rs" in _records(compiler)[-1]["files"]


def test_invalid_source_fails_instead_of_reusing_a_previous_executable(compiler):
    baseline = asyncio.run(_build.build_core(compiler.runtime))
    (compiler.runtime / "src/behavior.txt").write_text("INVALID")
    with pytest.raises(RuntimeError, match="candidate does not compile"):
        asyncio.run(_build.build_core(compiler.runtime))
    assert _artifact(baseline)["selected"] == "BASELINE"
    assert [record["selected"] for record in _records(compiler)] == [
        "BASELINE",
        "INVALID",
    ]
    assert len(list(compiler.cache.glob("*/build.json"))) == 1


@pytest.mark.parametrize("name", ["flashrsi-codex-core", "codex-code-mode-host"])
def test_corrupted_cached_binary_is_rejected(compiler, name):
    binary = asyncio.run(_build.build_core(compiler.runtime))
    binary.with_name(name).write_text("unexpected executable")
    with pytest.raises(RuntimeError, match="SHA-256"):
        asyncio.run(_build.build_core(compiler.runtime))
    assert len(_records(compiler)) == 1


def test_concurrent_candidates_cannot_publish_each_others_binary(compiler, tmp_path):
    second = tmp_path / "other-runtime"
    (second / "src").mkdir(parents=True)
    (second / "Cargo.toml").write_bytes((compiler.runtime / "Cargo.toml").read_bytes())
    (compiler.runtime / "src/behavior.txt").write_text("CONCURRENT_A")
    (second / "src/behavior.txt").write_text("CONCURRENT_B")

    async def compile_both():
        return await asyncio.gather(
            _build.build_core(compiler.runtime), _build.build_core(second)
        )

    first_binary, second_binary = asyncio.run(compile_both())
    assert first_binary != second_binary
    assert _artifact(first_binary)["selected"] == "CONCURRENT_A"
    assert _artifact(second_binary)["selected"] == "CONCURRENT_B"
    assert (
        first_binary.with_name("codex-code-mode-host").read_text()
        == "host:CONCURRENT_A"
    )
    assert (
        second_binary.with_name("codex-code-mode-host").read_text()
        == "host:CONCURRENT_B"
    )
    assert len(_records(compiler)) == 2


def test_cancelled_compile_stops_processes_and_releases_the_publication_lock(compiler):
    (compiler.runtime / "src/behavior.txt").write_text("CANCEL")

    async def cancel_started_build():
        building = asyncio.create_task(_build.build_core(compiler.runtime))

        async def wait_until_started():
            while not _records(compiler):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_until_started(), timeout=5)
        building.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(building, timeout=5)

    asyncio.run(cancel_started_build())
    (started,) = _records(compiler)
    assert compiler.record.with_suffix(".cancelled").read_text() == "stopped"
    for pid in (started["pid"], started["child_pid"]):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert not list(compiler.cache.glob("*/build.json"))

    (compiler.runtime / "src/behavior.txt").write_text("RECOVERED")
    recovered = asyncio.run(_build.build_core(compiler.runtime))
    assert _artifact(recovered)["selected"] == "RECOVERED"


def test_compiler_identity_changes_invalidate_the_build_cache(compiler, monkeypatch):
    first = asyncio.run(_build.build_core(compiler.runtime))
    monkeypatch.setenv("FLASHRSI_BUILD_TEST_RUST_VERSION", "1.95.1")
    second = asyncio.run(_build.build_core(compiler.runtime))
    assert first != second
    assert len(_records(compiler)) == 2


def test_rustflags_changes_cannot_reuse_another_build(compiler, monkeypatch):
    first = asyncio.run(_build.build_core(compiler.runtime))
    monkeypatch.setenv("RUSTFLAGS", "--cfg flashrsi_build_probe")
    second = asyncio.run(_build.build_core(compiler.runtime))
    assert first != second
    assert _artifact(first)["rustflags"] is None
    assert _artifact(second)["rustflags"] == "--cfg flashrsi_build_probe"
    assert len(_records(compiler)) == 2


@pytest.mark.parametrize("filename", ["config", "config.toml"])
def test_ancestor_cargo_configuration_is_rejected_before_compilation(
    compiler, filename
):
    configuration = compiler.cache.parent / ".cargo" / filename
    configuration.parent.mkdir()
    configuration.write_text('[build]\nrustflags = ["--cfg", "ambient"]\n')

    with pytest.raises(ValueError, match="External Cargo configuration") as error:
        asyncio.run(_build.build_core(compiler.runtime))

    assert str(configuration) in str(error.value)
    assert "isolated CARGO_HOME" in str(error.value)
    assert "FLASHRSI_CODEX_BUILD_CACHE" in str(error.value)
    assert _records(compiler) == []


@pytest.mark.parametrize("filename", ["config", "config.toml"])
@pytest.mark.parametrize("default_home", [False, True], ids=["explicit", "default"])
def test_cargo_home_configuration_is_rejected(
    compiler, tmp_path, monkeypatch, filename, default_home
):
    if default_home:
        monkeypatch.delenv("CARGO_HOME", raising=False)
        monkeypatch.setattr(
            _build.Path, "home", classmethod(lambda cls: tmp_path / "user-home")
        )
        cargo_home = tmp_path / "user-home/.cargo"
    else:
        cargo_home = tmp_path / "cargo-home"
        monkeypatch.setenv("CARGO_HOME", str(cargo_home))
    configuration = cargo_home / filename
    configuration.parent.mkdir(parents=True)
    configuration.write_text('[build]\nrustflags = ["--cfg", "ambient"]\n')

    with pytest.raises(ValueError, match="External Cargo configuration") as error:
        asyncio.run(_build.build_core(compiler.runtime))

    assert str(configuration) in str(error.value)
    assert _records(compiler) == []


def test_relative_cargo_home_is_resolved_from_the_cargo_workspace(
    compiler, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CARGO_HOME", "../relative-cargo-home")
    # Cargo runs in cache/workspace, which differs from both Python's cwd and
    # the selected runtime directory used for the rustc identity probe.
    configuration = compiler.cache / "relative-cargo-home/config.toml"
    configuration.parent.mkdir(parents=True)
    configuration.write_text('[build]\nrustflags = ["--cfg", "ambient"]\n')

    with pytest.raises(ValueError, match="External Cargo configuration") as error:
        asyncio.run(_build.build_core(compiler.runtime))

    assert str(configuration) in str(error.value)
    assert _records(compiler) == []


@pytest.mark.parametrize("location", ["ancestor", "cargo-home", "default-home"])
def test_a_cached_build_still_rejects_new_external_cargo_configuration(
    compiler, tmp_path, monkeypatch, location
):
    if location == "ancestor":
        directory = compiler.cache.parent / ".cargo"
    elif location == "cargo-home":
        directory = tmp_path / "cargo-home"
        monkeypatch.setenv("CARGO_HOME", str(directory))
    else:
        monkeypatch.delenv("CARGO_HOME", raising=False)
        monkeypatch.setattr(
            _build.Path, "home", classmethod(lambda cls: tmp_path / "user-home")
        )
        directory = tmp_path / "user-home/.cargo"
    baseline = asyncio.run(_build.build_core(compiler.runtime))
    assert asyncio.run(_build.build_core(compiler.runtime)) == baseline
    configuration = directory / "config.toml"
    configuration.parent.mkdir(parents=True)
    configuration.write_text('[build]\nrustflags = ["--cfg", "ambient"]\n')

    with pytest.raises(ValueError, match="External Cargo configuration") as error:
        asyncio.run(_build.build_core(compiler.runtime))

    assert str(configuration) in str(error.value)
    assert len(_records(compiler)) == 1
    assert _artifact(baseline)["selected"] == "BASELINE"


@pytest.mark.parametrize("filename", ["config", "config.toml"])
def test_selected_runtime_cargo_configuration_is_allowed(compiler, filename):
    configuration = compiler.runtime / ".cargo" / filename
    configuration.parent.mkdir()
    configuration.write_text('[build]\nrustflags = ["--cfg", "selected"]\n')

    binary = asyncio.run(_build.build_core(compiler.runtime))

    assert _artifact(binary)["selected"] == "BASELINE"
    assert f".cargo/{filename}" in _records(compiler)[0]["files"]
    assert (compiler.cache / "workspace/.cargo" / filename).read_bytes() == (
        configuration.read_bytes()
    )


def test_staging_removes_stale_directory_links_and_dangling_links(compiler, tmp_path):
    destination = tmp_path / "workspace"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "preserved.rs"
    protected.write_text("outside the selected source\n")
    (destination / "obsolete-directory").symlink_to(outside, target_is_directory=True)
    dangling = destination / "dangling-directory"
    dangling.symlink_to(tmp_path / "missing-directory", target_is_directory=True)

    _build._stage_source(compiler.runtime, destination)

    assert not (destination / "obsolete-directory").is_symlink()
    assert not dangling.is_symlink()
    assert protected.read_text() == "outside the selected source\n"
    assert (destination / "src/behavior.txt").read_text() == "BASELINE"
    assert not any(path.is_symlink() for path in destination.rglob("*"))


@pytest.mark.parametrize("link_kind", ["file", "parent-directory"])
def test_staging_replaces_desired_links_without_writing_outside_source(
    compiler, tmp_path, link_kind
):
    destination = tmp_path / "workspace"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    external_file = outside / "behavior.txt"
    external_file.write_text("BASELINE")
    if link_kind == "file":
        (destination / "src").mkdir()
        (destination / "src/behavior.txt").symlink_to(external_file)
    else:
        (destination / "src").symlink_to(outside, target_is_directory=True)

    _build._stage_source(compiler.runtime, destination)

    assert not (destination / "src").is_symlink()
    assert not (destination / "src/behavior.txt").is_symlink()
    assert (destination / "src/behavior.txt").read_text() == "BASELINE"
    (compiler.runtime / "src/behavior.txt").write_text("CANDIDATE")
    _build._stage_source(compiler.runtime, destination)
    assert (destination / "src/behavior.txt").read_text() == "CANDIDATE"
    assert external_file.read_text() == "BASELINE"
