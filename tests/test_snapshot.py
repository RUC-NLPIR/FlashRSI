import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace

import pytest

from flashrsi.core.snapshot import (
    Snapshot,
    SnapshotFile,
    _create_snapshot,
    _validate_path,
)


def _snapshot(files=None, *, agent_type="test", component_rules=None, parent=None):
    if files is None:
        files = {"skills/answer.md": SnapshotFile(b"answer accurately", "skill")}
    if component_rules is None:
        if parent is not None:
            component_rules = parent.component_rules
        else:
            component_rules = {}
            if isinstance(files, Mapping):
                for path, entry in files.items():
                    if isinstance(entry, SnapshotFile):
                        component_rules[entry.component] = (
                            *component_rules.get(entry.component, ()),
                            path,
                        )
    return _create_snapshot(
        files,
        agent_type=agent_type,
        component_rules=component_rules,
        parent=parent,
    )


def _saved_payload(tmp_path):
    path = tmp_path / "snapshot.json"
    _snapshot().save(path)
    return path, json.loads(path.read_text())


def test_snapshot_files_are_frozen_and_defensively_copied():
    original = {"skill.md": SnapshotFile(b"original", "skill")}
    snapshot = _snapshot(original)
    original["skill.md"] = SnapshotFile(b"changed", "skill")
    original["new.md"] = SnapshotFile(b"new", "skill")

    assert snapshot.files == {"skill.md": SnapshotFile(b"original", "skill")}
    with pytest.raises(TypeError):
        snapshot.files["new.md"] = original["new.md"]
    with pytest.raises(FrozenInstanceError):
        snapshot.files["skill.md"].content = b"changed"
    with pytest.raises(FrozenInstanceError):
        snapshot.id = "0" * 64


def test_component_rules_are_copied_immutable_and_inherited():
    rules = {"skill": ("skills/**",), "code": ("src/**",)}
    root = _snapshot(component_rules=rules)
    rules["skill"] = ("different/**",)
    rules["resource"] = ("assets/**",)

    assert root.component_rules == {"skill": ("skills/**",), "code": ("src/**",)}
    with pytest.raises(TypeError):
        root.component_rules["skill"] = ("different/**",)
    with pytest.raises(FrozenInstanceError):
        root.component_rules = {}
    child = _snapshot(parent=root)
    assert child.component_rules == root.component_rules


def test_component_rules_are_bound_to_identifiers_and_fixed_within_a_lineage():
    rules = {"skill": ("skills/**",), "code": ("src/**",)}
    root = _snapshot(component_rules=rules)
    reordered = {"code": rules["code"], "skill": rules["skill"]}
    assert _snapshot(component_rules=reordered).id == root.id
    changed = {**rules, "skill": ("skills/*.md",)}
    assert _snapshot(component_rules=changed).id != root.id
    with pytest.raises(ValueError, match="same component rules"):
        _snapshot(component_rules=changed, parent=root)


def test_candidate_check_rejects_loaded_candidate_with_changed_lineage_rules(tmp_path):
    root = _snapshot(component_rules={"skill": ("skills/**",)})
    candidate = _snapshot(parent=root)
    path = tmp_path / "candidate.json"
    candidate.save(path)
    payload = json.loads(path.read_text())
    payload["component_rules"]["skill"] = ["skills/*.md"]
    data = {key: value for key, value in payload.items() if key != "id"}
    payload["id"] = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    path.write_text(json.dumps(payload))

    external = Snapshot.load(path)
    assert external.root_id == root.id
    assert external.files == root.files
    with pytest.raises(ValueError, match="different component rules"):
        root._validate_candidate(external)


def test_scope_is_copied_and_does_not_change_version_identity_or_persistence(tmp_path):
    snapshot = _snapshot(component_rules={"skill": ("skills/**",), "code": ("src/**",)})
    scope = {"skill": "rw", "code": "none"}
    view = snapshot._with_scope(scope)
    scope["skill"] = "none"

    assert view._scope == {"skill": "rw", "code": "none"}
    with pytest.raises(TypeError):
        view._scope["skill"] = "none"
    assert view == snapshot
    assert view.id == snapshot.id
    assert view.root_id == snapshot.root_id
    assert view.parent_id == snapshot.parent_id
    assert "_scope" not in repr(view)

    original_path = tmp_path / "original.json"
    scoped_path = tmp_path / "scoped.json"
    snapshot.save(original_path)
    view.save(scoped_path)
    assert scoped_path.read_bytes() == original_path.read_bytes()
    assert "_scope" not in json.loads(scoped_path.read_text())
    restored = Snapshot.load(scoped_path)
    assert restored == view
    assert restored._scope is None


def test_roundtrip_preserves_arbitrary_bytes_modes_and_history(tmp_path):
    rules = {
        "skill": ("skills/**",),
        "code": ("src/**",),
        "resource": ("data/**", "empty"),
    }
    root = _snapshot(component_rules=rules)
    candidate = _snapshot(
        {
            "src/run.sh": SnapshotFile(b"#!/bin/sh\necho hi\n", "code", True),
            "data/二进制.bin": SnapshotFile(bytes(range(256)), "resource"),
            "empty": SnapshotFile(b"", "resource"),
        },
        parent=root,
    )
    path = tmp_path / "candidate.json"

    candidate.save(path)
    restored = Snapshot.load(path)

    assert path.is_file()
    assert restored == candidate
    assert restored.component_rules == rules
    assert restored.format_version == 2
    assert restored.root_id == root.id
    assert restored.parent_id == root.id
    assert restored.id != root.id
    assert restored.files["src/run.sh"].executable is True
    assert restored.files["data/二进制.bin"].content == bytes(range(256))
    assert restored.files["data/二进制.bin"].executable is False
    second = tmp_path / "second.json"
    restored.save(second)
    assert second.read_bytes() == path.read_bytes()


def test_identifiers_are_deterministic_and_bind_file_state_and_history():
    first = SnapshotFile(b"one", "skill")
    second = SnapshotFile(b"two", "code")
    root = _snapshot({"a": first, "b": second})

    assert root.id == _snapshot({"b": second, "a": first}).id
    assert root.root_id == root.id
    assert root.parent_id is None
    variants = [
        _snapshot({"renamed": first, "b": second}),
        _snapshot({"a": replace(first, content=b"edited"), "b": second}),
        _snapshot({"a": replace(first, component="code"), "b": second}),
        _snapshot({"a": replace(first, executable=True), "b": second}),
        _snapshot(root.files, agent_type="other"),
        _snapshot(root.files, parent=root),
    ]
    assert len({root.id, *(item.id for item in variants)}) == len(variants) + 1
    sibling = _snapshot({"a": SnapshotFile(b"sibling", "skill")}, parent=root)
    grandchild = _snapshot(root.files, parent=sibling)
    assert grandchild.id != variants[-1].id
    assert grandchild.root_id == root.id
    assert grandchild.parent_id == sibling.id
    other_root = _snapshot({"a": first}, component_rules=root.component_rules)
    assert _snapshot(root.files, parent=other_root).id != variants[-1].id


@pytest.mark.parametrize("existing", ["file", "directory", "symlink"])
def test_save_never_overwrites_existing_paths_and_cleans_temporary_files(
    tmp_path, existing
):
    path = tmp_path / "snapshot.json"
    if existing == "file":
        path.write_bytes(b"keep this")
    elif existing == "directory":
        path.mkdir()
    else:
        path.symlink_to(tmp_path / "absent")

    with pytest.raises(FileExistsError):
        _snapshot().save(path)

    assert list(tmp_path.iterdir()) == [path]
    if existing == "file":
        assert path.read_bytes() == b"keep this"
    elif existing == "directory":
        assert path.is_dir()
    else:
        assert path.is_symlink()
        assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", base64.b64encode(b"tampered").decode()),
        ("component", "code"),
        ("executable", True),
    ],
)
def test_load_detects_tampered_file_entries(tmp_path, field, value):
    path, payload = _saved_payload(tmp_path)
    payload["files"]["skills/answer.md"][field] = value
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="id does not match"):
        Snapshot.load(path)


def test_load_detects_renamed_and_removed_files(tmp_path):
    path, payload = _saved_payload(tmp_path)
    payload["files"]["renamed.md"] = payload["files"].pop("skills/answer.md")
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="id does not match"):
        Snapshot.load(path)
    payload["files"].clear()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="id does not match"):
        Snapshot.load(path)


def test_load_detects_tampered_rules(tmp_path):
    path, payload = _saved_payload(tmp_path)
    payload["component_rules"]["skill"] = ["skills/**"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="id does not match"):
        Snapshot.load(path)


@pytest.mark.parametrize(
    "rules",
    [
        None,
        [],
        {"skill": "skills/**"},
        {"skill": []},
        {"skill": [1]},
        {"": ["**"]},
        {"skill": ["../escape"]},
    ],
)
def test_load_rejects_invalid_component_rule_schema(tmp_path, rules):
    path, payload = _saved_payload(tmp_path)
    payload["component_rules"] = rules
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        Snapshot.load(path)


def test_load_rejects_old_format_without_component_rules(tmp_path):
    path, payload = _saved_payload(tmp_path)
    payload["format_version"] = 1
    del payload["component_rules"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="format_version 1"):
        Snapshot.load(path)


@pytest.mark.parametrize("invalid", ["label", "unknown", "runtime", "ambiguous"])
def test_load_rejects_invalid_layout_even_with_a_matching_identifier(tmp_path, invalid):
    path, payload = _saved_payload(tmp_path)
    if invalid == "label":
        payload["files"]["skills/answer.md"]["component"] = "code"
    elif invalid == "unknown":
        payload["files"]["unknown.md"] = payload["files"].pop("skills/answer.md")
    elif invalid == "runtime":
        payload["files"][".env"] = payload["files"].pop("skills/answer.md")
        payload["component_rules"] = {"skill": ["**"]}
    else:
        payload["component_rules"]["other"] = ["skills/**"]
    # Recompute the root hash so that this exercises layout validation rather
    # than simple corruption detection. A valid hash does not imply valid files.
    data = {
        key: value for key, value in payload.items() if key not in {"id", "root_id"}
    }
    identifier = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    payload.update(id=identifier, root_id=identifier)
    path.write_text(json.dumps(payload))
    with pytest.raises(
        ValueError,
        match="component label|exactly one component|cannot enter a Snapshot",
    ):
        Snapshot.load(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "0" * 64),
        ("root_id", "0" * 64),
        ("parent_id", "0" * 64),
        ("agent_type", "different"),
        ("agent_type", ""),
        ("agent_type", 3),
        ("id", "not-a-hash"),
        ("root_id", "A" * 64),
        ("parent_id", False),
        ("format_version", 1),
        ("format_version", 3),
        ("format_version", True),
        ("format_version", 1.0),
    ],
)
def test_load_rejects_wrong_metadata(tmp_path, field, value):
    path, payload = _saved_payload(tmp_path)
    payload[field] = value
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError):
        Snapshot.load(path)


def test_descendant_metadata_is_bound_to_identifier(tmp_path):
    root = _snapshot()
    child = _snapshot(parent=root)
    grandchild = _snapshot(parent=child)
    path = tmp_path / "snapshot.json"
    grandchild.save(path)
    original = json.loads(path.read_text())
    for field in ("root_id", "parent_id"):
        path.write_text(json.dumps({**original, field: "0" * 64}))
        with pytest.raises(ValueError, match="id does not match"):
            Snapshot.load(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "..",
        "/root/file",
        "../escape",
        "dir/../escape",
        "dir/./file",
        "dir//file",
        "dir/",
        "dir\\file",
        "nul\0file",
        "C:/file",
        "C:file",
        "C:",
        "\ud800",
        1,
    ],
)
def test_rejects_noncanonical_unsafe_paths(path):
    with pytest.raises(ValueError, match="file path"):
        _validate_path(path)
    with pytest.raises(ValueError, match="file path"):
        _snapshot({path: SnapshotFile(b"file", "skill")})


def test_rejects_file_parent_conflicts_and_allows_empty_tree():
    with pytest.raises(ValueError, match="file as its parent"):
        _snapshot(
            {
                "skills": SnapshotFile(b"file", "skill"),
                "skills/nested/file.md": SnapshotFile(b"file", "skill"),
            }
        )
    assert _snapshot({}).files == {}


@pytest.mark.parametrize(
    "values",
    [
        {"content": bytearray(b"mutable"), "component": "skill"},
        {"content": "text", "component": "skill"},
        {"content": b"file", "component": ""},
        {"content": b"file", "component": " \t"},
        {"content": b"file", "component": None},
        {"content": b"file", "component": "skill", "executable": 1},
    ],
)
def test_snapshot_file_validates_types(values):
    with pytest.raises(ValueError):
        SnapshotFile(**values)


@pytest.mark.parametrize("files", [[], {"file": b"raw"}])
def test_snapshot_rejects_invalid_files_mapping(files):
    with pytest.raises(ValueError):
        _snapshot(files)


def test_snapshot_constructor_rejects_forged_content_and_cross_type_parent():
    root = _snapshot()
    with pytest.raises(ValueError, match="id does not match"):
        replace(root, files={})
    with pytest.raises(ValueError, match="same agent_type"):
        _snapshot(agent_type="other", parent=root)


@pytest.mark.parametrize("content", ["!invalid!", "YQ", "YR==", "YQ==\n", "非", 3])
def test_load_rejects_invalid_or_noncanonical_base64(tmp_path, content):
    path, payload = _saved_payload(tmp_path)
    payload["files"]["skills/answer.md"]["content"] = content
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="base64"):
        Snapshot.load(path)


@pytest.mark.parametrize("raw", [b"{", b"[]", b"null", b"\xff", b'{"id":1,"id":2}'])
def test_load_rejects_invalid_json_and_duplicate_keys(tmp_path, raw):
    path = tmp_path / "snapshot.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        Snapshot.load(path)


@pytest.mark.parametrize("change", ["extra", "missing", "files", "entry", "duplicate"])
def test_load_requires_exact_schema(tmp_path, change):
    path, payload = _saved_payload(tmp_path)
    if change == "extra":
        payload["unexpected"] = None
    elif change == "missing":
        del payload["format_version"]
    elif change == "files":
        payload["files"] = []
    elif change == "entry":
        payload["files"]["skills/answer.md"]["unexpected"] = None
    raw = json.dumps(payload)
    if change == "duplicate":
        raw = raw.replace(
            '"executable": false', '"executable": false,"executable": false'
        )
    path.write_text(raw)

    with pytest.raises(ValueError):
        Snapshot.load(path)
