"""A companion cache must never conceal a selected host source change."""

import asyncio
import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.agents.codex import _companion


@pytest.fixture
def selected_host(tmp_path):
    metadata = json.loads(_companion._METADATA.read_text())
    original = _companion._METADATA.with_name("runtime")
    runtime = tmp_path / "runtime"
    for relative in set(metadata["files"]) | set(metadata["workspace_manifests"]):
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original / relative, destination)
    return runtime, metadata


def test_only_the_unchanged_host_closure_can_reuse_its_official_build(selected_host):
    runtime, metadata = selected_host
    assert _companion._unchanged(runtime, metadata)
    unrelated = runtime / "models-manager/src/models_manager.rs"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("A different selected core implementation")
    assert _companion._unchanged(runtime, metadata)


def test_a_new_workspace_toolchain_file_requires_a_source_build(selected_host):
    runtime, metadata = selected_host
    (runtime / "rust-toolchain").write_text("nightly")
    assert not _companion._unchanged(runtime, metadata)


@pytest.mark.parametrize(
    "relative",
    [
        "code-mode-host/src/lib.rs",
        "code-mode-runtime/Cargo.toml",
        "models-manager/Cargo.toml",
        "protocol/src/prompts/base_instructions/default.md",
        "Cargo.toml",
        "Cargo.lock",
        ".cargo/config.toml",
    ],
)
def test_relevant_change_forces_source_compilation(
    selected_host, tmp_path, monkeypatch, relative
):
    runtime, metadata = selected_host
    changed = runtime / relative
    changed.write_bytes(changed.read_bytes() + b"\nchanged candidate\n")
    assert not _companion._unchanged(runtime, metadata)
    monkeypatch.setattr(
        _companion,
        "_platform_asset",
        lambda *_: metadata["assets"]["aarch64-apple-darwin"],
    )
    monkeypatch.setattr(
        _companion,
        "_official_companion",
        lambda *_: pytest.fail("Changed source used an old binary"),
    )
    monkeypatch.setattr(_companion.shutil, "which", lambda *_args, **_kwargs: "cargo")
    target = tmp_path / "target"
    calls = []

    async def compile_selected(*command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["V8_FROM_SOURCE"] == "1"
        output = target / "release/codex-code-mode-host"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"compiled selected source")

        async def wait():
            return 0

        return SimpleNamespace(returncode=0, wait=wait)

    monkeypatch.setattr(_companion.asyncio, "create_subprocess_exec", compile_selected)
    binary = asyncio.run(
        _companion.prepare_companion(runtime, runtime, target, tmp_path / "cache", {})
    )
    assert binary.read_bytes() == b"compiled selected source"
    assert "flashrsi-codex-core" in calls[0] and "codex-code-mode-host" in calls[0]
    assert "--locked" in calls[0]
    assert calls[0][calls[0].index("--profile") + 1] == "release"
    record = json.loads(binary.with_name("companion.json").read_text())
    assert record["kind"] == "selected-source-build"
    assert Path(record["build_log"]).is_file()


@pytest.mark.parametrize("change", ["add", "remove", "executable", "symlink"])
def test_closure_presence_permissions_and_links_are_checked(selected_host, change):
    runtime, metadata = selected_host
    source = runtime / "code-mode-host/src/lib.rs"
    if change == "add":
        source.with_name("additional.rs").write_text("new input")
    elif change == "remove":
        source.unlink()
    elif change == "executable":
        source.chmod(source.stat().st_mode ^ 0o100)
    else:
        target = source.with_name("original.rs")
        source.rename(target)
        source.symlink_to(target)
    assert not _companion._unchanged(runtime, metadata)


@pytest.mark.parametrize("change", ["add", "remove", "executable"])
def test_manifests_outside_the_host_closure_cannot_change(selected_host, change):
    runtime, metadata = selected_host
    manifest = runtime / "models-manager/Cargo.toml"
    if change == "add":
        added = manifest.with_name("nested") / "Cargo.toml"
        added.parent.mkdir()
        added.write_text('[package]\nname = "additional"\n')
    elif change == "remove":
        manifest.unlink()
    else:
        manifest.chmod(manifest.stat().st_mode ^ 0o100)
    assert not _companion._unchanged(runtime, metadata)


def _inject_fixed_bridge(runtime, metadata):
    fixed = _companion._METADATA.with_name("_bridge")
    for relative in metadata["injected_manifests"]:
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixed / Path(relative).relative_to("bridge"), destination)


@pytest.mark.parametrize("change", ["modify", "add", "remove"])
def test_staged_bridge_manifests_are_part_of_the_feature_union_guard(
    selected_host, change
):
    runtime, metadata = selected_host
    _inject_fixed_bridge(runtime, metadata)
    assert _companion._unchanged(runtime, metadata, injected_bridge=True)
    assert not _companion._unchanged(runtime, metadata)
    manifest = runtime / "bridge/Cargo.toml"
    if change == "modify":
        manifest.write_bytes(manifest.read_bytes() + b"\n# different bridge\n")
    elif change == "add":
        added = manifest.with_name("new-crate") / "Cargo.toml"
        added.parent.mkdir()
        added.write_text('[package]\nname = "new-bridge-dependency"\n')
    else:
        manifest.unlink()
    assert not _companion._unchanged(runtime, metadata, injected_bridge=True)


def _tiny_release():
    binary = b"verified upstream helper"
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        member = tarfile.TarInfo("pinned-host")
        member.size = len(binary)
        bundle.addfile(member, io.BytesIO(binary))
    archive = output.getvalue()
    return archive, {
        "url": "https://example.invalid/pinned-host.tar.gz",
        "member": "pinned-host",
        "archive_size": len(archive),
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
    }


def test_official_archive_and_binary_are_verified_before_atomic_publication(
    tmp_path, monkeypatch
):
    archive, asset = _tiny_release()
    monkeypatch.setattr(
        _companion.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(archive),
    )
    binary = _companion._official_companion(
        tmp_path, {"tag": "fixed", "commit": "fixed"}, asset
    )
    assert _companion._sha256(binary) == asset["binary_sha256"]
    record = json.loads(binary.with_name("companion.json").read_text())
    assert record["kind"] == "verified-upstream-build-cache"
    assert record["archive_sha256"] == asset["archive_sha256"]
    binary.write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="SHA-256"):
        _companion._official_companion(
            tmp_path, {"tag": "fixed", "commit": "fixed"}, asset
        )


def test_bad_download_cannot_publish_a_companion(tmp_path, monkeypatch):
    archive, asset = _tiny_release()
    monkeypatch.setattr(
        _companion.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(archive + b"corrupt"),
    )
    with pytest.raises(RuntimeError, match="SHA-256/size"):
        _companion._official_companion(
            tmp_path, {"tag": "fixed", "commit": "fixed"}, asset
        )
    assert not list(tmp_path.rglob("codex-code-mode-host"))


def test_changed_source_build_failure_cannot_return_a_cached_host(
    selected_host, tmp_path, monkeypatch
):
    runtime, metadata = selected_host
    (runtime / "code-mode-runtime/src/lib.rs").write_text("selected different runtime")
    monkeypatch.setattr(
        _companion,
        "_platform_asset",
        lambda *_: metadata["assets"]["aarch64-apple-darwin"],
    )
    monkeypatch.setattr(
        _companion,
        "_official_companion",
        lambda *_: pytest.fail("Changed source returned a cached binary"),
    )
    monkeypatch.setattr(_companion.shutil, "which", lambda *_args, **_kwargs: "cargo")

    async def unavailable_toolchain(*command, **kwargs):
        kwargs["stderr"].write(b"selected source requires its original toolchain")

        async def wait():
            return 7

        return SimpleNamespace(returncode=7, wait=wait)

    monkeypatch.setattr(
        _companion.asyncio, "create_subprocess_exec", unavailable_toolchain
    )
    with pytest.raises(RuntimeError, match="original toolchain"):
        asyncio.run(
            _companion.prepare_companion(
                runtime, runtime, tmp_path / "target", tmp_path / "cache", {}
            )
        )
    assert not list(tmp_path.rglob("companion.json"))


@pytest.mark.parametrize("relative", ["models-manager/Cargo.toml", "bridge/Cargo.toml"])
def test_prepare_checks_the_actual_staged_manifest_union(
    selected_host, tmp_path, monkeypatch, relative
):
    runtime, metadata = selected_host
    workspace = tmp_path / "workspace"
    shutil.copytree(runtime, workspace)
    _inject_fixed_bridge(workspace, metadata)
    manifest = workspace / relative
    manifest.write_bytes(
        manifest.read_bytes() + b"\n# selected feature union changed\n"
    )
    assert _companion._unchanged(runtime, metadata)
    monkeypatch.setattr(
        _companion,
        "_platform_asset",
        lambda *_: metadata["assets"]["aarch64-apple-darwin"],
    )
    monkeypatch.setattr(
        _companion,
        "_official_companion",
        lambda *_: pytest.fail("A changed staged manifest reused the old host"),
    )
    monkeypatch.setattr(_companion.shutil, "which", lambda *_args, **_kwargs: "cargo")

    async def source_compiler(*command, **kwargs):
        assert kwargs["cwd"] == workspace

        async def wait():
            return 7

        return SimpleNamespace(returncode=7, wait=wait)

    monkeypatch.setattr(_companion.asyncio, "create_subprocess_exec", source_compiler)
    with pytest.raises(RuntimeError, match="source build failed"):
        asyncio.run(
            _companion.prepare_companion(
                runtime, workspace, tmp_path / "target", tmp_path / "cache", {}
            )
        )


@pytest.mark.parametrize(
    "key",
    [
        "CC",
        "CXX",
        "CFLAGS",
        "CXXFLAGS",
        "LDFLAGS",
        "V8_FORCE_DEBUG",
        "V8_FROM_SOURCE",
        "DISABLE_CLANG",
        "CLANG_BASE_PATH",
        "GN_ARGS",
        "RUSTFLAGS",
        "RUSTY_V8_ARCHIVE",
        "CARGO_TARGET_AARCH64_APPLE_DARWIN_RUSTFLAGS",
    ],
)
def test_explicit_build_inputs_disable_the_official_cache(monkeypatch, key):
    metadata = json.loads(_companion._METADATA.read_text())
    monkeypatch.setattr(_companion.sys, "platform", "darwin")
    monkeypatch.setattr(_companion.platform, "machine", lambda: "arm64")
    assert _companion._platform_asset({}, metadata) is not None
    assert _companion._platform_asset({key: "1"}, metadata) is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SDKROOT", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"),
        ("DEVELOPER_DIR", "/Applications/Xcode-beta.app/Contents/Developer"),
        ("MACOSX_DEPLOYMENT_TARGET", "15.0"),
        ("ARCHFLAGS", "-arch x86_64"),
        ("RUSTUP_TOOLCHAIN", "nightly"),
        ("RUSTUP_TOOLCHAIN", "1.95.0"),
        ("CARGO_BUILD_RUSTC", "/custom/toolchain/bin/rustc"),
        ("CARGO_BUILD_RUSTC_WRAPPER", "/custom/compiler-wrapper"),
        ("CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER", "/custom/workspace-wrapper"),
    ],
)
def test_explicit_sdk_and_toolchain_selection_requires_selected_source(
    monkeypatch, key, value
):
    metadata = json.loads(_companion._METADATA.read_text())
    monkeypatch.setattr(_companion.sys, "platform", "darwin")
    monkeypatch.setattr(_companion.platform, "machine", lambda: "arm64")
    assert _companion._platform_asset({}, metadata) is not None
    assert _companion._platform_asset({key: value}, metadata) is None


def test_unrelated_runtime_settings_allow_the_verified_build_cache(monkeypatch):
    metadata = json.loads(_companion._METADATA.read_text())
    monkeypatch.setattr(_companion.sys, "platform", "darwin")
    monkeypatch.setattr(_companion.platform, "machine", lambda: "arm64")
    assert (
        _companion._platform_asset(
            {"RUST_BACKTRACE": "1", "LANG": "zh_CN.UTF-8"}, metadata
        )
        is not None
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process cancellation")
def test_cancelling_an_http_worker_reaps_the_process_promptly(
    selected_host, tmp_path, monkeypatch
):
    runtime, metadata = selected_host
    _inject_fixed_bridge(runtime, metadata)
    monkeypatch.setattr(
        _companion,
        "_platform_asset",
        lambda *_: metadata["assets"]["aarch64-apple-darwin"],
    )
    original_spawn = asyncio.create_subprocess_exec
    processes = []

    async def waiting_http_worker(*command, **kwargs):
        assert "--fetch" in command
        process = await original_spawn(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=True,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(
        _companion.asyncio, "create_subprocess_exec", waiting_http_worker
    )

    async def cancel():
        pending = asyncio.create_task(
            _companion.prepare_companion(
                runtime,
                runtime,
                tmp_path / "target",
                tmp_path / "cache",
                {},
            )
        )
        while not processes:
            await asyncio.sleep(0.01)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=5)

    asyncio.run(asyncio.wait_for(cancel(), timeout=10))
    assert processes[0].returncode is not None
    assert not list(tmp_path.rglob("companion.json"))
