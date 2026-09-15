"""Immutable file versions: checkout, commit, validation, and persistence."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import Any


def _validate_label(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError(f"{name} must be a non-empty string without NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be valid UTF-8") from error


def _validate_path(path: str) -> None:
    """Require a canonical relative POSIX file path, suitable for checkout."""
    if (
        not isinstance(path, str)
        or not path
        or "\0" in path
        or "\\" in path
        or re.match(r"^[A-Za-z]:", path)
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError(f"invalid snapshot file path: {path!r}")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"invalid snapshot file path: {path!r}") from error


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    """A file's exact bytes, Agent-assigned component, and executable flag."""

    content: bytes
    component: str
    executable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise ValueError("content must be bytes")
        _validate_label(self.component, "component")
        if not isinstance(self.executable, bool):
            raise ValueError("executable must be a bool")


def _copy_files(files: Mapping[str, SnapshotFile]) -> dict[str, SnapshotFile]:
    if not isinstance(files, Mapping):
        raise ValueError("files must be a mapping")
    copied = dict(files)
    for path, entry in copied.items():
        _validate_path(path)
        if not isinstance(entry, SnapshotFile):
            raise ValueError("files must map paths to SnapshotFile entries")
    for path in copied:
        parts = path.split("/")
        if any("/".join(parts[:end]) in copied for end in range(1, len(parts))):
            raise ValueError(f"snapshot file has a file as its parent: {path!r}")
    return copied


def _payload(
    files: Mapping[str, SnapshotFile],
    *,
    component_rules: Mapping[str, tuple[str, ...]],
    agent_type: str,
    root_id: str | None,
    parent_id: str | None,
    format_version: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "format_version": format_version,
        "agent_type": agent_type,
        "parent_id": parent_id,
        "component_rules": dict(component_rules),
        "files": {
            path: {
                "content": base64.b64encode(entry.content).decode("ascii"),
                "component": entry.component,
                "executable": entry.executable,
            }
            for path, entry in files.items()
        },
    }
    # A root's own ID cannot be included in its hash. Descendants bind both
    # their root and immediate parent, so equal files can have distinct history.
    if root_id is not None:
        result["root_id"] = root_id
    return result


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 identifier")


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A validated immutable file tree and its content-addressed version history.

    ``save`` and ``load`` use a single JSON file, not a checkout directory.
    The ID covers files, component rules, and version metadata. Rules are fixed
    at capture and inherited by descendants. An Agent can bind a temporary
    editing scope; it does not participate in version identity or persistence.
    """

    files: Mapping[str, SnapshotFile]
    component_rules: Mapping[str, tuple[str, ...]]
    id: str
    agent_type: str
    root_id: str
    parent_id: str | None
    format_version: int = 2
    _scope: Mapping[str, str] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        files = _copy_files(self.files)
        rules = _copy_rules(self.component_rules)
        _validate_label(self.agent_type, "agent_type")
        if type(self.format_version) is not int or self.format_version != 2:
            raise ValueError("unsupported snapshot format_version; expected 2")
        _identifier(self.id, "id")
        _identifier(self.root_id, "root_id")
        if self.parent_id is None:
            if self.root_id != self.id:
                raise ValueError("root snapshot root_id must equal id")
        else:
            _identifier(self.parent_id, "parent_id")
            if self.id in {self.root_id, self.parent_id}:
                raise ValueError("descendant id must differ from root_id and parent_id")
        payload = _payload(
            files,
            component_rules=rules,
            agent_type=self.agent_type,
            root_id=self.root_id if self.parent_id is not None else None,
            parent_id=self.parent_id,
            format_version=self.format_version,
        )
        if hashlib.sha256(_encode(payload)).hexdigest() != self.id:
            raise ValueError("snapshot id does not match its files and metadata")
        object.__setattr__(self, "files", MappingProxyType(files))
        object.__setattr__(self, "component_rules", rules)
        if self._scope is not None:
            object.__setattr__(self, "_scope", _copy_scope(self._scope, rules))
        self._validate_layout()

    def _with_scope(self, scope: Mapping[str, str] | None) -> Snapshot:
        """Bind checkout defaults without changing the version's file contents."""
        return self if scope == self._scope else replace(self, _scope=scope)

    def _permission(self, component: str) -> str:
        return "rw" if self._scope is None else self._scope.get(component, "none")

    @classmethod
    def _capture(
        cls,
        directory: Path,
        *,
        agent_type: str,
        component_rules: Mapping[str, tuple[str, ...]],
    ) -> Snapshot:
        """Capture declared execution files from a source tree automatically.

        Unselected files and known runtime artifacts are omitted. Links are not
        followed, and links/special files in selected paths are rejected. In
        contrast, from_directory/commit validate a complete curated file tree.
        """
        rules = _copy_rules(component_rules)
        files = _read_tree(Path(directory), component_rules=rules, capture=True)
        return _create_snapshot(files, agent_type=agent_type, component_rules=rules)

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        agent_type: str,
        component_rules: Mapping[str, tuple[str, ...]],
    ) -> Snapshot:
        """Read a curated file directory into an initial version."""
        rules = _copy_rules(component_rules)
        return _create_snapshot(
            _read_tree(
                Path(directory).expanduser(),
                component_rules=rules,
            ),
            agent_type=agent_type,
            component_rules=rules,
        )

    @contextmanager
    def check_out(
        self,
        *,
        working_dir: Path | None = None,
    ) -> Iterator[Path]:
        """Export the visible editing files, applying the Agent's default scope."""
        with self._export(working_dir=working_dir) as directory:
            yield directory

    @contextmanager
    def _export(
        self, *, working_dir: Path | None = None, full: bool = False
    ) -> Iterator[Path]:
        """Export an editing view, or the full version for harness execution."""
        visible = {
            path: entry
            for path, entry in self.files.items()
            if full or self._permission(entry.component) != "none"
        }
        for path in self.files:
            _check_runtime_path(path)
        if working_dir is not None:
            working_dir = Path(working_dir).expanduser()
            working_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="checkout-", dir=working_dir
        ) as temporary:
            directory = Path(temporary).resolve()
            for path, entry in visible.items():
                destination = directory / path
                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as stream:
                        stream.write(entry.content)
                except FileExistsError as error:
                    raise ValueError(
                        "Snapshot paths collide on the checkout filesystem"
                    ) from error
                mode = 0o755 if entry.executable else 0o644
                if not full and self._permission(entry.component) == "r":
                    mode &= ~0o222
                destination.chmod(mode)
            # Some filesystems merge distinct directory names even if exclusive
            # file creation succeeds. Never expose a silently altered tree.
            try:
                restored = _read_tree(directory, component_rules=self.component_rules)
            except ValueError as error:
                raise ValueError(
                    "checkout filesystem cannot preserve Snapshot paths"
                ) from error
            if restored != visible:
                raise ValueError("checkout filesystem cannot preserve Snapshot paths")
            yield directory

    def commit(self, working_dir: Path) -> Snapshot:
        """Create a candidate from an edited directory, inheriting this version's rules.

        The directory must contain the complete visible editing view. Hidden
        baseline files are retained; read-only or hidden edits are rejected
        automatically using the scope bound by Agent.set_scope.
        """
        files = _read_tree(
            Path(working_dir).expanduser(), component_rules=self.component_rules
        )
        for path, entry in files.items():
            if self._permission(entry.component) == "none":
                raise ValueError(f"file belongs to a hidden component: {path}")
        files = {
            **{
                path: entry
                for path, entry in self.files.items()
                if self._permission(entry.component) == "none"
            },
            **files,
        }
        _check_changes(self.files, files, components=self._writable_components())
        return _create_snapshot(
            files,
            agent_type=self.agent_type,
            component_rules=self.component_rules,
            parent=self,
        )

    def _writable_components(self) -> frozenset[str]:
        return frozenset(
            name for name in self.component_rules if self._permission(name) == "rw"
        )

    def _validate_candidate(self, candidate: Snapshot) -> None:
        """Enforce this Agent view's policy even for unscoped or loaded candidates."""
        self._validate_compatible(candidate)
        _check_changes(
            self.files, candidate.files, components=self._writable_components()
        )

    def _validate_compatible(self, candidate: Snapshot) -> None:
        if not isinstance(candidate, Snapshot):
            raise ValueError("expected a Snapshot")
        if candidate.agent_type != self.agent_type:
            raise ValueError("Snapshot belongs to a different Agent type")
        if candidate.format_version != self.format_version:
            raise ValueError("incompatible Snapshot format_version")
        if candidate.root_id != self.root_id:
            raise ValueError("Snapshot has a different root")
        if candidate.component_rules != self.component_rules:
            raise ValueError("Snapshot has different component rules")

    def _validate_layout(self) -> None:
        for path, entry in self.files.items():
            _check_runtime_path(path)
            expected = _classify(path, self.component_rules)
            if entry.component != expected:
                raise ValueError(f"Snapshot changed the component label: {path}")

    def save(self, path: Path) -> None:
        """Atomically save a JSON file without replacing any existing path.

        The parent directory must already exist. An incomplete write is never
        published at ``path``; even concurrent writers cannot overwrite it.
        """
        path = Path(path)
        payload = _payload(
            self.files,
            component_rules=self.component_rules,
            agent_type=self.agent_type,
            root_id=self.root_id,
            parent_id=self.parent_id,
            format_version=self.format_version,
        )
        payload["id"] = self.id
        data = _encode(payload) + b"\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink()

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        """Load and validate schema, paths, file bytes, and version integrity."""
        try:
            payload = json.loads(
                Path(path).read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
            )
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid snapshot JSON") from error
        if isinstance(payload, dict) and payload.get("format_version") == 1:
            raise ValueError(
                "snapshot format_version 1 has no component rules; recapture the source"
            )
        fields = {
            "files",
            "component_rules",
            "id",
            "agent_type",
            "root_id",
            "parent_id",
            "format_version",
        }
        if not isinstance(payload, dict) or payload.keys() != fields:
            raise ValueError("invalid snapshot schema")
        if not isinstance(payload["files"], dict):
            raise ValueError("snapshot files must be an object")
        raw_rules = payload["component_rules"]
        if not isinstance(raw_rules, dict) or any(
            not isinstance(patterns, list) for patterns in raw_rules.values()
        ):
            raise ValueError("snapshot component_rules must map names to arrays")
        rules = {name: tuple(patterns) for name, patterns in raw_rules.items()}
        files = {}
        for name, raw_entry in payload["files"].items():
            if not isinstance(raw_entry, dict) or raw_entry.keys() != {
                "content",
                "component",
                "executable",
            }:
                raise ValueError("invalid snapshot file schema")
            encoded = raw_entry["content"]
            if not isinstance(encoded, str):
                raise ValueError("snapshot file content must be base64 text")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError(
                    "snapshot file content must be valid base64"
                ) from error
            if base64.b64encode(content).decode("ascii") != encoded:
                raise ValueError("snapshot file content must use canonical base64")
            files[name] = SnapshotFile(
                content, raw_entry["component"], raw_entry["executable"]
            )
        return cls(**{**payload, "files": files, "component_rules": rules})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate snapshot JSON key: {key!r}")
        result[key] = value
    return result


def _create_snapshot(
    files: Mapping[str, SnapshotFile],
    *,
    agent_type: str,
    component_rules: Mapping[str, tuple[str, ...]],
    parent: Snapshot | None = None,
) -> Snapshot:
    """Create an initial version or a candidate descended from ``parent``."""
    files = _copy_files(files)
    rules = _copy_rules(component_rules)
    _validate_label(agent_type, "agent_type")
    if parent is not None and (
        not isinstance(parent, Snapshot) or parent.agent_type != agent_type
    ):
        raise ValueError("snapshot parent must have the same agent_type")
    if parent is not None and rules != parent.component_rules:
        raise ValueError("snapshot parent must have the same component rules")
    payload = _payload(
        files,
        component_rules=rules,
        agent_type=agent_type,
        root_id=parent.root_id if parent is not None else None,
        parent_id=parent.id if parent is not None else None,
        format_version=2,
    )
    identifier = hashlib.sha256(_encode(payload)).hexdigest()
    return Snapshot(
        files=files,
        component_rules=rules,
        id=identifier,
        agent_type=agent_type,
        root_id=parent.root_id if parent is not None else identifier,
        parent_id=parent.id if parent is not None else None,
        _scope=parent._scope if parent is not None else None,
    )


# Callers supply curated files; these guards also reject common runtime files
# produced while editing them. They are not a substitute for backend curation.
_RUNTIME_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".cache",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)


def _check_runtime_path(path: str) -> None:
    if path == "components.yaml":
        raise ValueError(
            "components.yaml is adapter metadata and cannot enter a Snapshot"
        )
    if _is_runtime_path(path):
        raise ValueError(
            f"runtime files and credentials cannot enter a Snapshot: {path}"
        )


def _is_runtime_path(path: str) -> bool:
    # A source package can legitimately contain a logs module or .env.example.
    # Exclude conventional output roots and real dotenv files, not those assets.
    if any(
        part in _RUNTIME_PARTS
        or part == ".env"
        or (part.startswith(".env.") and part not in {".env.example", ".env.template"})
        for part in path.split("/")
    ):
        return True
    return path.split("/")[0] in {"logs", "runs"} or path.endswith(
        (".pyc", ".pyo", ".log")
    )


def _copy_rules(
    rules: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(rules, Mapping):
        raise ValueError("component_rules must be a mapping")
    copied = {}
    for component, patterns in rules.items():
        _validate_label(component, "component")
        if not isinstance(patterns, tuple) or not patterns:
            raise ValueError("component rules must be non-empty tuples of patterns")
        for pattern in patterns:
            _validate_path(pattern)
        copied[component] = patterns
    return MappingProxyType(copied)


def _copy_scope(
    scope: Mapping[str, str],
    rules: Mapping[str, tuple[str, ...]],
) -> Mapping[str, str]:
    if not isinstance(scope, Mapping):
        raise ValueError("scope must map component names to rw, r, or none")
    copied = dict(scope)
    if any(not isinstance(name, str) for name in copied):
        raise ValueError("scope component names must be strings")
    unsupported = copied.keys() - rules.keys()
    if unsupported:
        raise ValueError(f"unsupported components: {', '.join(sorted(unsupported))}")
    if any(
        not isinstance(permission, str) or permission not in {"rw", "r", "none"}
        for permission in copied.values()
    ):
        raise ValueError("scope permissions must be rw, r, or none")
    return MappingProxyType(copied)


def _matches_rule(path: str, rule: str, *, directory: bool = False) -> bool:
    """Match from the tree root; only a whole '**' segment crosses directories."""
    parts, patterns = path.split("/"), rule.split("/")

    def match(index: int, pattern_index: int) -> bool:
        if directory and index == len(parts):
            return True  # Some descendant could complete the remaining pattern.
        if pattern_index == len(patterns):
            return index == len(parts)
        pattern = patterns[pattern_index]
        if pattern == "**":
            return match(index, pattern_index + 1) or (
                index < len(parts) and match(index + 1, pattern_index)
            )
        return (
            index < len(parts)
            and fnmatchcase(parts[index], pattern)
            and match(index + 1, pattern_index + 1)
        )

    return match(0, 0)


def _classify(path: str, rules: Mapping[str, tuple[str, ...]]) -> str:
    matches = _matching_components(path, rules)
    if len(matches) != 1:
        raise ValueError(f"path must match exactly one component: {path}")
    return matches.pop()


def _matching_components(path: str, rules: Mapping[str, tuple[str, ...]]) -> set[str]:
    return {
        component
        for component, patterns in rules.items()
        if any(_matches_rule(path, pattern) for pattern in patterns)
    }


def _read_tree(
    directory: Path,
    *,
    component_rules: Mapping[str, tuple[str, ...]],
    capture: bool = False,
) -> dict[str, SnapshotFile]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("file source must be a directory, not a symbolic link")
    files = {}

    def onerror(error: OSError) -> None:
        raise error

    for root, dirs, names in os.walk(directory, onerror=onerror, followlinks=False):
        for name in sorted((*dirs, *names)):
            source = Path(root) / name
            path = source.relative_to(directory).as_posix()
            if capture and (path == "components.yaml" or _is_runtime_path(path)):
                if name in dirs:
                    dirs.remove(name)
                continue
            mode = source.lstat().st_mode
            if capture and not _matching_components(path, component_rules):
                descendant_selected = (
                    stat.S_ISDIR(mode) or stat.S_ISLNK(mode)
                ) and any(
                    _matches_rule(path, rule, directory=True)
                    for patterns in component_rules.values()
                    for rule in patterns
                )
                if not descendant_selected:
                    if name in dirs:
                        dirs.remove(name)
                    continue
            _validate_path(path)
            _check_runtime_path(path)
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"only regular files are allowed in Snapshots: {path}")
            files[path] = SnapshotFile(
                content=source.read_bytes(),
                component=_classify(path, component_rules),
                executable=bool(mode & 0o111),
            )
    return files


def _check_changes(
    before: Mapping[str, SnapshotFile],
    after: Mapping[str, SnapshotFile],
    *,
    components: frozenset[str],
) -> None:
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if old is not None and new is not None and old.component != new.component:
            raise ValueError(f"Snapshot changed the component label: {path}")
        component = old.component if old is not None else new.component
        if component not in components:
            raise ValueError(f"edit outside allowed components ({component}): {path}")
