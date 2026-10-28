"""Build the selected upstream source, with the fixed bridge outside Snapshot."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

_BRIDGE = Path(__file__).with_name("_bridge")


@asynccontextmanager
async def _build_lock(cache_root):
    """Serialize source staging, Cargo, and publication across Python processes."""
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / "build.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.write(b"\0")
            lock.flush()
        else:
            import fcntl
        while True:
            try:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK}:
                    raise
                await asyncio.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _stage_source(runtime_dir, destination):
    # A stable compiler source path lets unchanged native crates reuse Cargo's
    # artifacts across candidates. No source outside the selected tree survives.
    desired = {}
    for root, prefix in ((runtime_dir, Path()), (_BRIDGE, Path("bridge"))):
        for path in root.rglob("*"):
            if path.is_file():
                desired[prefix / path.relative_to(root)] = path
    if destination.exists():
        for path in sorted(destination.rglob("*"), reverse=True):
            if path.is_symlink():
                path.unlink()
            elif path.is_file() and path.relative_to(destination) not in desired:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    for relative, original in desired.items():
        target = destination / relative
        if target.is_symlink():
            target.unlink()
        if target.is_file() and target.read_bytes() == original.read_bytes():
            if bool(target.stat().st_mode & 0o111) == bool(
                original.stat().st_mode & 0o111
            ):
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)


def _source_digest(directory: Path, digest) -> None:
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(directory).as_posix().encode()
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
            digest.update(bytes([bool(path.stat().st_mode & 0o111)]))


async def build_core(runtime_dir: Path) -> Path:
    """Compile exactly this source version; never substitute an installed engine.

    A file lock serializes concurrent builds in the shared target directory. A binary
    is published into its immutable source/toolchain cache only after success.
    The source and bridge hashes bind the executable, not its temporary path.
    """
    if not (runtime_dir / "Cargo.toml").is_file():
        raise ValueError("Codex Snapshot has no runtime/Cargo.toml core source")
    cargo = shutil.which("cargo")
    if cargo is None:
        raise ValueError(
            "Building Codex Snapshot source requires Cargo and Rust 1.95.0"
        )
    env = dict(os.environ)
    env["CARGO_INCREMENTAL"] = "0"
    rustc = env.get("RUSTC") or shutil.which("rustc")
    if rustc is None:
        raise ValueError("Building Codex Snapshot source requires rustc")
    compiler = await asyncio.create_subprocess_exec(
        rustc,
        "--version",
        "--verbose",
        cwd=runtime_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=os.name == "posix",
    )
    try:
        compiler_stdout, compiler_stderr = await compiler.communicate()
    except BaseException:
        from flashrsi.agents.codex import _stop

        await _stop(compiler)
        raise
    if compiler.returncode:
        raise RuntimeError(
            "Cannot identify Codex compiler: "
            + compiler_stderr.decode(errors="replace")
        )
    digest = hashlib.sha256()
    _source_digest(runtime_dir, digest)
    digest.update(b"\0flashrsi-bridge\0")
    _source_digest(_BRIDGE, digest)
    for policy in ("_companion.py", "_companion.json"):
        path = Path(__file__).with_name(policy)
        if path.is_file():
            digest.update(path.read_bytes())
    digest.update(compiler_stdout)
    # Build scripts can inspect arbitrary environment variables. Hash all of
    # them conservatively; only the digest is retained, never credentials.
    digest.update(json.dumps(env, sort_keys=True).encode())
    digest.update(b"\0release\0locked\0incremental=0")
    source_hash = digest.hexdigest()
    cache_root = (
        Path(
            os.environ.get(
                "FLASHRSI_CODEX_BUILD_CACHE",
                str(
                    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
                    / "flashrsi"
                    / "codex-core"
                ),
            )
        )
        .expanduser()
        .resolve()
    )
    cached = cache_root / source_hash
    binary_name = "flashrsi-codex-core" + (".exe" if os.name == "nt" else "")
    binary = cached / binary_name
    metadata_path = cached / "build.json"
    async with _build_lock(cache_root):
        if binary.is_file() and metadata_path.is_file():
            record = json.loads(metadata_path.read_text())
            if (
                record["binary_sha256"]
                == hashlib.sha256(binary.read_bytes()).hexdigest()
                and record["companion_sha256"]
                == hashlib.sha256(
                    binary.with_name(
                        "codex-code-mode-host" + binary.suffix
                    ).read_bytes()
                ).hexdigest()
            ):
                return binary
            raise RuntimeError("Cached Codex core executable failed its SHA-256 check")
        cached.mkdir(parents=True, exist_ok=True)
        source = cache_root / "workspace"
        _stage_source(runtime_dir, source)
        return await _compile(
            cargo,
            env,
            cache_root,
            cached,
            source,
            binary,
            metadata_path,
            source_hash,
            compiler_stdout,
        )


async def _compile(
    cargo,
    env,
    cache_root,
    cached,
    source,
    binary,
    metadata_path,
    source_hash,
    compiler_stdout,
):
    binary_name = binary.name
    command = [
        cargo,
        "build",
        "--locked",
        "--profile",
        "release",
        "--package",
        "flashrsi-codex-core",
        "--bin",
        "flashrsi-codex-core",
        "--target-dir",
        str(cache_root / "target"),
    ]
    log_path = cached / "build.log"
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=source,
            stdout=log,
            stderr=log,
            env=env,
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
        raise RuntimeError(f"Codex core source build failed ({log_path}):\n{tail}")
    from flashrsi.agents.codex._companion import prepare_companion

    companion = await prepare_companion(
        source,
        source,
        cache_root / "target",
        cache_root,
        env,
    )
    # Cargo places cross-compiled binaries beneath the requested target triple.
    target = cache_root / "target"
    if env.get("CARGO_BUILD_TARGET"):
        target /= env["CARGO_BUILD_TARGET"]
    for name in (binary_name, "codex-code-mode-host" + binary.suffix):
        built = target / "release" / name if name == binary_name else companion
        with tempfile.NamedTemporaryFile(
            prefix="binary-", dir=cached, delete=False
        ) as temporary:
            published = Path(temporary.name)
        try:
            shutil.copy2(built, published)
            published.replace(cached / name)
        finally:
            published.unlink(missing_ok=True)
    record = {
        "source_sha256": source_hash,
        "compiler": compiler_stdout.decode().strip(),
        "profile": "release",
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "companion_sha256": hashlib.sha256(
            binary.with_name("codex-code-mode-host" + binary.suffix).read_bytes()
        ).hexdigest(),
        "companion_build": json.loads(companion.with_name("companion.json").read_text())
        if companion.with_name("companion.json").is_file()
        else {"method": "source"},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="record-", dir=cached, delete=False
    ) as temporary:
        json.dump(record, temporary, indent=2)
        staged_record = Path(temporary.name)
    staged_record.replace(metadata_path)
    return binary
