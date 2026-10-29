"""Build code-mode's native host, reusing one verified upstream build only.

The official executable is a cache for the unchanged pinned dependency closure.
It is never used after a relevant source, asset, manifest, or lockfile change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

_METADATA = Path(__file__).with_name("_companion.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unchanged(
    runtime_dir: Path, metadata: dict, *, injected_bridge: bool = False
) -> bool:
    """Match the host source closure and the complete feature-unifying manifest set."""
    if any(
        (runtime_dir / relative).exists() or (runtime_dir / relative).is_symlink()
        for relative in metadata.get("absent_workspace_files", [])
    ):
        return False
    actual = set(metadata["workspace_files"])
    for root in metadata["dependency_roots"] + metadata["configuration_roots"]:
        directory = runtime_dir / root
        if not directory.is_dir() or directory.is_symlink():
            return False
        for path in directory.rglob("*"):
            if path.is_symlink():
                return False
            if path.is_file():
                actual.add(path.relative_to(runtime_dir).as_posix())
    if actual != set(metadata["files"]):
        return False
    for relative, expected in metadata["files"].items():
        path = runtime_dir / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or bool(path.stat().st_mode & 0o111) != expected["executable"]
            or _sha256(path) != expected["sha256"]
        ):
            return False
    # Any workspace crate can enable features on a dependency shared with the
    # host. Therefore all manifests are bound, including crates outside its
    # path dependency closure; their ordinary source files remain independent.
    manifests = dict(metadata["workspace_manifests"])
    if injected_bridge:
        manifests.update(metadata["injected_manifests"])
    actual_manifests = {
        path.relative_to(runtime_dir).as_posix()
        for path in runtime_dir.rglob("Cargo.toml")
    }
    if actual_manifests != set(manifests):
        return False
    for relative, expected in manifests.items():
        path = runtime_dir / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or bool(path.stat().st_mode & 0o111) != expected["executable"]
            or _sha256(path) != expected["sha256"]
        ):
            return False
    return True


def _platform_asset(env: dict, metadata: dict) -> dict | None:
    if sys.platform != "darwin" or platform.machine().lower() not in {
        "arm64",
        "aarch64",
    }:
        return None
    triple = "aarch64-apple-darwin"
    if env.get("CARGO_BUILD_TARGET", triple) != triple:
        return None
    # These inputs can request a different binary even for identical source.
    if any(
        value
        for key, value in env.items()
        if key
        in {
            "CC",
            "CXX",
            "CPP",
            "AR",
            "RANLIB",
            "CFLAGS",
            "CXXFLAGS",
            "CPPFLAGS",
            "LDFLAGS",
            "LINKFLAGS",
            "CXXSTDLIB",
            "TARGET_CC",
            "HOST_CC",
            "SDKROOT",
            "DEVELOPER_DIR",
            "MACOSX_DEPLOYMENT_TARGET",
            "ARCHFLAGS",
            "RUSTUP_TOOLCHAIN",
            "RUSTC",
            "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER",
            "CARGO_BUILD_RUSTC",
            "CARGO_BUILD_RUSTC_WRAPPER",
            "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
            "CARGO_BUILD_RUSTFLAGS",
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "V8_FROM_SOURCE",
            "V8_FORCE_DEBUG",
            "DISABLE_CLANG",
            "CLANG_BASE_PATH",
            "CLANG_PATH",
            "GN",
            "NINJA",
            "CCACHE",
            "SCCACHE",
            "DOCS_RS",
            "DENO_TRYBUILD",
            "GN_ARGS",
            "EXTRA_GN_ARGS",
            "RUSTY_V8_ARCHIVE",
            "RUSTY_V8_MIRROR",
            "RUSTY_V8_SRC_BINDING_PATH",
        }
        or key.startswith(
            ("CC_", "CXX_", "AR_", "CFLAGS_", "CXXFLAGS_", "CPPFLAGS_", "LDFLAGS_")
        )
        or (
            key.startswith("CARGO_TARGET_")
            and key.endswith(("_RUSTFLAGS", "_LINKER", "_AR"))
        )
        or key.startswith("CARGO_PROFILE_")
    ):
        return None
    return metadata["assets"].get(triple)


def _write_record(directory: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as output:
        temporary = Path(output.name)
        json.dump(record, output, indent=2)
        output.write("\n")
    try:
        temporary.replace(directory / "companion.json")
    finally:
        temporary.unlink(missing_ok=True)


def _official_companion(cache_root: Path, metadata: dict, asset: dict) -> Path:
    directory = cache_root / "companions" / asset["archive_sha256"]
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "codex-code-mode-host"
    if binary.is_file():
        if _sha256(binary) != asset["binary_sha256"]:
            raise RuntimeError(
                "Cached official code-mode host failed its SHA-256 check"
            )
    else:
        # Read a single regular member; never extract archive paths or symlinks.
        with tempfile.TemporaryDirectory(
            prefix="download-", dir=directory
        ) as temporary:
            staging = Path(temporary)
            archive = staging / "host.tar.gz"
            with urllib.request.urlopen(asset["url"], timeout=120) as response:
                with archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
            if (
                archive.stat().st_size != asset["archive_size"]
                or _sha256(archive) != asset["archive_sha256"]
            ):
                raise RuntimeError(
                    "Official code-mode host archive failed its SHA-256/size check"
                )
            staged_binary = staging / binary.name
            with tarfile.open(archive, "r:gz") as bundle:
                members = bundle.getmembers()
                if (
                    len(members) != 1
                    or members[0].name != asset["member"]
                    or not members[0].isfile()
                ):
                    raise RuntimeError(
                        "Official code-mode host archive has unexpected members"
                    )
                with bundle.extractfile(members[0]) as source:
                    with staged_binary.open("wb") as output:
                        shutil.copyfileobj(source, output)
            if _sha256(staged_binary) != asset["binary_sha256"]:
                raise RuntimeError(
                    "Official code-mode host executable failed its SHA-256 check"
                )
            staged_binary.chmod(0o755)
            archive.replace(directory / "host.tar.gz")
            staged_binary.replace(binary)
    _write_record(
        directory,
        {
            "kind": "verified-upstream-build-cache",
            "package": "codex-code-mode-host",
            "profile": "release",
            "tag": metadata["tag"],
            "commit": metadata["commit"],
            "url": asset["url"],
            "archive_sha256": asset["archive_sha256"],
            "binary_sha256": asset["binary_sha256"],
            "closure_metadata_sha256": _sha256(_METADATA),
            "reason": "All pinned host dependency sources, assets, manifests, and lockfile match.",
        },
    )
    return binary


def _workspace_digest(workspace: Path, env: dict) -> str:
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode())
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            relative = path.relative_to(workspace).as_posix().encode()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(bytes.fromhex(_sha256(path)))
            digest.update(bytes([bool(path.stat().st_mode & 0o111)]))
    return digest.hexdigest()


async def prepare_companion(
    runtime_dir: Path,
    workspace: Path,
    target_dir: Path,
    cache_root: Path,
    env: dict,
) -> Path:
    """Return a verified unchanged host build, or compile the selected sources."""
    metadata = json.loads(_METADATA.read_text())
    asset = _platform_asset(env, metadata)
    if (
        asset is not None
        and _unchanged(workspace, metadata, injected_bridge=True)
        and (
            runtime_dir.resolve() == workspace.resolve()
            or _unchanged(runtime_dir, metadata)
        )
    ):
        directory = cache_root / "companions" / asset["archive_sha256"]
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / "fetch.log"
        with log_path.open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--fetch",
                str(_METADATA.resolve()),
                str(cache_root.resolve()),
                "aarch64-apple-darwin",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
                start_new_session=os.name == "posix",
            )
            try:
                stdout, _ = await process.communicate()
            except BaseException:
                from flashrsi.agents.codex import _stop

                await _stop(process)
                raise
        if process.returncode:
            tail = log_path.read_text(errors="replace")[-12000:]
            raise RuntimeError(
                f"Pinned code-mode host cache fetch failed ({log_path}):\n{tail}"
            )
        binary = Path(stdout.decode().strip())
        if (
            binary != directory.resolve() / "codex-code-mode-host"
            or _sha256(binary) != asset["binary_sha256"]
        ):
            raise RuntimeError(
                "Pinned code-mode host cache process returned an invalid executable"
            )
        return binary

    cargo = shutil.which("cargo", path=env.get("PATH"))
    if cargo is None:
        raise ValueError(
            "Building the selected code-mode host requires Cargo and Rust 1.95.0"
        )
    env = dict(env)
    env.setdefault("V8_FROM_SOURCE", "1")
    directory = (
        cache_root / "companions" / ("source-" + _workspace_digest(workspace, env))
    )
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "build.log"
    command = [
        cargo,
        "build",
        "--locked",
        "--profile",
        "release",
        "--package",
        "flashrsi-codex-core",
        "--package",
        "codex-code-mode-host",
        "--bins",
        "--target-dir",
        str(target_dir),
    ]
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=os.name == "posix",
        )
        try:
            await process.wait()
        except BaseException:
            from flashrsi.agents.codex import _stop

            await _stop(process)
            raise
    if process.returncode:
        tail = log_path.read_text(errors="replace")[-12000:]
        raise RuntimeError(
            f"Codex code-mode host source build failed ({log_path}):\n{tail}"
        )
    built = target_dir
    if env.get("CARGO_BUILD_TARGET"):
        built /= env["CARGO_BUILD_TARGET"]
    name = "codex-code-mode-host" + (".exe" if os.name == "nt" else "")
    built /= "release"
    binary = directory / name
    with tempfile.NamedTemporaryFile(
        prefix="binary-", dir=directory, delete=False
    ) as output:
        temporary = Path(output.name)
    try:
        shutil.copy2(built / name, temporary)
        temporary.replace(binary)
    finally:
        temporary.unlink(missing_ok=True)
    _write_record(
        directory,
        {
            "kind": "selected-source-build",
            "package": "codex-code-mode-host",
            "profile": "release",
            "workspace_sha256": _workspace_digest(workspace, env),
            "binary_sha256": _sha256(binary),
            "build_log": str(log_path),
            "command": command,
            "reason": "Selected host closure or build configuration differs, or platform has no verified cache.",
        },
    )
    return binary


if __name__ == "__main__":
    # This isolated stdlib-only worker makes an HTTP wait cancellable by killing
    # its process group. No project imports or user site packages are executed.
    if len(sys.argv) != 5 or sys.argv[1] != "--fetch":
        sys.exit("Expected the private --fetch METADATA CACHE_ROOT TARGET invocation")
    try:
        _METADATA = Path(sys.argv[2])
        _metadata = json.loads(_METADATA.read_text())
        _asset = _metadata["assets"][sys.argv[4]]
        print(_official_companion(Path(sys.argv[3]), _metadata, _asset))
    except Exception as error:
        sys.exit(f"Code-mode host cache fetch failed: {error}")
