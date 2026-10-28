#!/usr/bin/env python3
"""Mechanically extract the pinned Codex Rust core; never rewrite Rust sources.

The local upstream Git tree supplies the authoritative blob IDs. A tarball is
used to avoid one network fetch per blob in a sparse/partial upstream checkout.
Every copied file is checked against that Git tree before it is written.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import posixpath
import re
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

UPSTREAM_COMMIT = "be6e8eac029b183056b7e4402879f15d2c85f61b"
UPSTREAM_TAG = "rust-v0.147.0"
UPSTREAM_REPOSITORY = "https://github.com/openai/codex"
ARCHIVE_URL = f"https://codeload.github.com/openai/codex/tar.gz/{UPSTREAM_COMMIT}"
ROOT_CRATES = (
    "codex-analytics",
    "codex-arg0",
    "codex-cloud-config",
    "codex-code-mode-host",
    "codex-config",
    "codex-core",
    "codex-core-api",
    "codex-home",
    "codex-exec-server",
    "codex-extension-api",
    "codex-features",
    "codex-goal-extension",
    "codex-git-attribution",
    "codex-guardian",
    "codex-login",
    "codex-image-generation-extension",
    "codex-memories-extension",
    "codex-mcp-extension",
    "codex-otel",
    "codex-protocol",
    "codex-skills-extension",
    "codex-utils-absolute-path",
)
SUPPORT_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    "rustfmt.toml",
    "clippy.toml",
    ".cargo/config.toml",
)
MANIFEST_NAME = "UPSTREAM.json"
PATCH_NAME = "upstream-build.patch"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_tree(repository: Path) -> dict[str, tuple[str, str]]:
    actual = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", UPSTREAM_COMMIT], text=True
    ).strip()
    if actual != UPSTREAM_COMMIT:
        raise ValueError("the upstream repository does not contain the pinned commit")
    tagged = subprocess.check_output(
        [
            "git",
            "-C",
            str(repository),
            "rev-parse",
            f"refs/tags/{UPSTREAM_TAG}^{{commit}}",
        ],
        text=True,
    ).strip()
    if tagged != UPSTREAM_COMMIT:
        raise ValueError(
            f"upstream tag {UPSTREAM_TAG} does not match the pinned commit"
        )
    output = subprocess.check_output(
        ["git", "-C", str(repository), "ls-tree", "-r", "-z", UPSTREAM_COMMIT]
    )
    tree = {}
    for row in output.split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split()
            if kind == "blob":
                tree[path.decode()] = (mode, object_id)
    return tree


def read_archive(path: Path) -> dict[str, bytes]:
    files = {}
    with tarfile.open(path, "r:gz") as archive:
        prefix = f"codex-{UPSTREAM_COMMIT}/"
        for member in archive:
            if member.name == prefix.rstrip("/") and member.isdir():
                continue
            if not member.name.startswith(prefix):
                raise ValueError(f"unexpected archive root: {member.name}")
            relative = member.name.removeprefix(prefix)
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                files[relative] = stream.read()
    return files


def dependencies(manifest: dict, *, development: bool):
    for section in ("dependencies", "build-dependencies", "dev-dependencies"):
        if section == "dev-dependencies" and not development:
            continue
        for name, value in manifest.get(section, {}).items():
            if isinstance(value, dict):
                yield name, value
    for target in manifest.get("target", {}).values():
        yield from dependencies(target, development=development)


def dependency_closure(manifests: dict, *, development: bool) -> set[str]:
    workspace = manifests["codex-rs"]["workspace"]["dependencies"]
    package_dirs = {
        manifest["package"]["name"]: directory
        for directory, manifest in manifests.items()
        if "package" in manifest
    }
    pending = [package_dirs[name] for name in ROOT_CRATES]
    selected = set()
    while pending:
        directory = pending.pop()
        if directory in selected:
            continue
        selected.add(directory)
        for name, entry in dependencies(manifests[directory], development=development):
            base = directory
            if entry.get("workspace"):
                entry = workspace.get(name, {})
                base = "codex-rs"
            if isinstance(entry, dict) and "path" in entry:
                dependency = posixpath.normpath(f"{base}/{entry['path']}")
                if dependency not in manifests:
                    raise ValueError(f"missing path dependency: {directory}: {name}")
                pending.append(dependency)
    return selected


def select_files(files: dict[str, bytes], crates: set[str]) -> set[str]:
    selected = {
        path
        for path in files
        if any(path.startswith(directory + "/") for directory in crates)
    }
    selected.update(f"codex-rs/{path}" for path in SUPPORT_FILES)
    selected.update(("LICENSE", "NOTICE"))
    # Literal compile-time includes occasionally refer to shared data outside a
    # crate. Follow those references without pulling in UI/CLI workspace members.
    pending = list(selected)
    while pending:
        source = pending.pop()
        if not source.endswith(".rs"):
            continue
        text = files[source].decode("utf-8")
        for name in re.findall(r'include_(?:str|bytes)!\s*\(\s*"([^"]+)"', text):
            target = posixpath.normpath(posixpath.dirname(source) + "/" + name)
            if target in files and target not in selected:
                if not target.startswith("codex-rs/"):
                    raise ValueError(f"include outside the Rust workspace: {target}")
                selected.add(target)
                pending.append(target)
    return selected


def workspace_source(original: bytes, crates: set[str]) -> bytes:
    members = sorted(path.removeprefix("codex-rs/") for path in crates)
    members.append("bridge")
    replacement = (
        "members = [\n"
        + "".join(f'    "{member}",\n' for member in members)
        + ']\ndefault-members = ["bridge"]'
    )
    text, replacements = re.subn(
        r"(?ms)^members\s*=\s*\[.*?^\]", replacement, original.decode(), count=1
    )
    if replacements != 1:
        raise ValueError("cannot locate the upstream workspace member list")
    return text.encode()


def patch_text(originals: dict[str, bytes], destination: Path) -> str:
    patches = []
    for relative, original in originals.items():
        current = (destination / relative).read_bytes()
        if current != original:
            patches.extend(
                difflib.unified_diff(
                    original.decode().splitlines(keepends=True),
                    current.decode().splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            )
    return "".join(patches)


def write_metadata(metadata: dict, destination: Path) -> None:
    (destination / MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def extract(repository: Path, archive: Path, destination: Path) -> None:
    tree, files = git_tree(repository), read_archive(archive)
    manifests = {
        posixpath.dirname(path): tomllib.loads(data.decode())
        for path, data in files.items()
        if path.startswith("codex-rs/") and path.endswith("/Cargo.toml")
    }
    production = dependency_closure(manifests, development=False)
    crates = dependency_closure(manifests, development=True)
    selected = select_files(files, crates)
    excluded = {"cli", "exec", "tui", "app-server", "app-server-daemon"}
    if excluded & {path.removeprefix("codex-rs/") for path in crates}:
        raise ValueError(
            "the dependency closure unexpectedly includes an app entry point"
        )
    destination.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_COMMIT,
        "tag": UPSTREAM_TAG,
        "version": manifests["codex-rs"]["workspace"]["package"]["version"],
        "archive_url": ARCHIVE_URL,
        "archive_sha256": sha256(archive.read_bytes()),
        "root_crates": list(ROOT_CRATES),
        "production_crates": sorted(
            path.removeprefix("codex-rs/") for path in production
        ),
        "development_only_crates": sorted(
            path.removeprefix("codex-rs/") for path in crates - production
        ),
        "excluded_entry_points": sorted(excluded),
        "bridge": "The adapter injects its fixed _bridge directory at build time; it is outside Snapshot.",
        "files": {},
    }
    for upstream_path in sorted(selected):
        data = files[upstream_path]
        mode, blob = tree[upstream_path]
        computed = hashlib.sha1(
            f"blob {len(data)}\0".encode() + data, usedforsecurity=False
        ).hexdigest()
        if blob != computed:
            raise ValueError(
                f"archive content differs from the Git blob: {upstream_path}"
            )
        relative = upstream_path.removeprefix("codex-rs/")
        current = workspace_source(data, crates) if relative == "Cargo.toml" else data
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(current)
        target.chmod(0o755 if mode == "100755" else 0o644)
        metadata["files"][relative] = {
            "upstream_path": upstream_path,
            "git_blob_sha1": blob,
            "upstream_sha256": sha256(data),
            "sha256": sha256(current),
            "executable": mode == "100755",
        }
    originals = {"Cargo.toml": files["codex-rs/Cargo.toml"]}
    patch = patch_text(originals, destination)
    (destination / PATCH_NAME).write_text(patch)
    metadata["patch_sha256"] = sha256(patch.encode())
    metadata["patches"] = {
        "Cargo.toml": "Only workspace members/default-members are mechanically replaced."
    }
    write_metadata(metadata, destination)
    print(
        f"Extracted {len(production)} production crates, "
        f"{len(crates - production)} test-support crates, "
        f"{len(selected)} verified upstream files into {destination}"
    )


def _verify_baseline(destination: Path, metadata: dict, *, ignored=()) -> None:
    if (
        (destination / MANIFEST_NAME).is_symlink()
        or metadata["commit"] != UPSTREAM_COMMIT
        or metadata["tag"] != UPSTREAM_TAG
        or metadata["repository"] != UPSTREAM_REPOSITORY
        or metadata["version"] != UPSTREAM_TAG.removeprefix("rust-v")
    ):
        raise ValueError("the provenance does not identify the pinned upstream release")
    failures = []
    patch = destination / PATCH_NAME
    if (
        patch.is_symlink()
        or not patch.is_file()
        or sha256(patch.read_bytes()) != metadata["patch_sha256"]
    ):
        failures.append(PATCH_NAME)
    for relative, expected in metadata["files"].items():
        path = destination / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or (
                relative not in ignored
                and sha256(path.read_bytes()) != expected["sha256"]
            )
            or bool(path.stat().st_mode & 0o111) != expected["executable"]
        ):
            failures.append(relative)
    recorded = set(metadata["files"]) | {MANIFEST_NAME, PATCH_NAME}
    failures.extend(
        str(path.relative_to(destination))
        for path in destination.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.relative_to(destination).as_posix() not in recorded
    )
    if failures:
        raise ValueError("upstream baseline differs: " + ", ".join(failures[:20]))


def verify(destination: Path) -> None:
    metadata = json.loads((destination / MANIFEST_NAME).read_text())
    _verify_baseline(destination, metadata)
    print(f"Verified {len(metadata['files'])} baseline files against {MANIFEST_NAME}")


def record_lock(archive: Path, destination: Path) -> None:
    """Record derived local packages while preserving every external lock identity."""
    metadata = json.loads((destination / MANIFEST_NAME).read_text())
    # Reject source, mode, provenance and patch changes before publishing anything.
    # Cargo.lock is the only file this operation is allowed to re-record.
    _verify_baseline(destination, metadata, ignored={"Cargo.lock"})
    if sha256(archive.read_bytes()) != metadata["archive_sha256"]:
        raise ValueError(
            "the archive SHA-256 differs from the recorded upstream archive"
        )
    files = read_archive(archive)
    original_lock = tomllib.loads(files["codex-rs/Cargo.lock"].decode())
    current_lock = tomllib.loads((destination / "Cargo.lock").read_text())
    manifests = {
        posixpath.dirname(path): tomllib.loads(data.decode())
        for path, data in files.items()
        if path.startswith("codex-rs/") and path.endswith("/Cargo.toml")
    }
    crates = dependency_closure(manifests, development=True)
    workspace = manifests["codex-rs"]["workspace"]["package"]
    if (destination / "Cargo.toml").read_bytes() != workspace_source(
        files["codex-rs/Cargo.toml"], crates
    ):
        raise ValueError("the generated workspace manifest was modified")
    local_packages = set()
    for crate in sorted(crates):
        upstream_path = f"{crate}/Cargo.toml"
        local_path = upstream_path.removeprefix("codex-rs/")
        if (destination / local_path).read_bytes() != files[upstream_path]:
            raise ValueError(f"the upstream local crate manifest was modified: {crate}")
        package = manifests[crate]["package"]
        version = package["version"]
        if version == {"workspace": True}:
            version = workspace["version"]
        if not isinstance(version, str):
            raise ValueError(f"unsupported upstream local crate version: {crate}")
        local_packages.add((package["name"], version, None, None))

    def identity(package):
        return (
            package["name"],
            package["version"],
            package.get("source"),
            package.get("checksum"),
        )

    external_packages = {
        identity(package) for package in original_lock["package"] if "source" in package
    }
    bridge_package = ("flashrsi-codex-core", workspace["version"], None, None)
    for package in current_lock["package"]:
        current = identity(package)
        allowed = external_packages if "source" in package else local_packages
        if current not in allowed and current != bridge_package:
            raise ValueError(
                "build lock changed an upstream dependency or added a package: "
                f"{package['name']} {package['version']} ({package.get('source', 'path')})"
            )
    metadata["files"]["Cargo.lock"]["sha256"] = sha256(
        (destination / "Cargo.lock").read_bytes()
    )
    metadata["patches"]["Cargo.lock"] = (
        "Cargo-generated local workspace/bridge identities; external lock identities unchanged."
    )
    originals = {
        relative: files[f"codex-rs/{relative}"]
        for relative in ("Cargo.toml", "Cargo.lock")
    }
    patch = patch_text(originals, destination)
    metadata["patch_sha256"] = sha256(patch.encode())
    (destination / PATCH_NAME).write_text(patch)
    write_metadata(metadata, destination)
    verify(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "flashrsi/agents/codex/runtime",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--record-build-lock", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.destination)
        return
    archive = args.archive
    if archive is None:
        archive = (
            Path(__file__).resolve().parents[1]
            / ".cache/codex-build"
            / (f"codex-{UPSTREAM_COMMIT}.tar.gz")
        )
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
    if args.record_build_lock:
        record_lock(archive, args.destination)
    else:
        if args.upstream is None:
            parser.error(
                "extraction requires --upstream pointing to a local Git repository"
            )
        extract(args.upstream, archive, args.destination)


if __name__ == "__main__":
    main()
