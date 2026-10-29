"""Source-directed traversal bounds from the pinned file-system walk."""

import pytest

from flashrsi.agents.codex.python_core import resources


def _walk(root, **kwargs):
    events = []
    found = resources._walk_skill_files(
        root,
        follow_symlinks=kwargs.get("follow", True),
        direct_children=kwargs.get("direct", False),
        emit=events.append,
    )
    return [path.relative_to(root).as_posix() for path in found], events


def _skill(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def test_walk_depth_counts_directories_and_does_not_stop_at_skill(tmp_path):
    _skill(tmp_path / "SKILL.md")
    _skill(tmp_path / "a/b/c/d/e/f/SKILL.md")
    _skill(tmp_path / "a/b/c/d/e/f/g/SKILL.md")
    found, _ = _walk(tmp_path)
    assert found == ["SKILL.md", "a/b/c/d/e/f/SKILL.md"]


def test_walk_directory_budget_counts_enqueues_in_breadth_first_order(
    tmp_path, monkeypatch
):
    for name in ("a/deep", "b", "c"):
        _skill(tmp_path / name / "SKILL.md")
    monkeypatch.setattr(resources, "_SKILL_SCAN_DIRECTORIES", 3)
    found, events = _walk(tmp_path)
    assert found == ["b/SKILL.md"]
    assert any("traversal limit" in event["message"] for event in events)


def test_walk_entry_budget_stops_before_processing_queued_children(
    tmp_path, monkeypatch
):
    _skill(tmp_path / "a/SKILL.md")
    (tmp_path / "b").touch()
    (tmp_path / "c").touch()
    monkeypatch.setattr(resources, "_SKILL_SCAN_ENTRIES", 2)
    found, events = _walk(tmp_path)
    assert found == []
    assert any("traversal limit" in event["message"] for event in events)


@pytest.mark.parametrize("extra,expected", [(0, ["SKILL.md"]), (-1, [])])
def test_walk_response_bytes_reserve_item_before_including_it(
    tmp_path, monkeypatch, extra, expected
):
    path = tmp_path / "SKILL.md"
    path.touch()
    item_bytes = len(resources._skill_path_uri(path).encode()) + 64
    monkeypatch.setattr(resources, "_SKILL_WALK_RESPONSE_BYTES", item_bytes + extra)
    found, events = _walk(tmp_path)
    assert found == expected
    assert bool(events) is (extra < 0)


def test_direct_child_inventory_and_scope_dependent_directory_aliases(tmp_path):
    _skill(tmp_path / "SKILL.md")
    _skill(tmp_path / "direct/SKILL.md")
    _skill(tmp_path / "direct/nested/SKILL.md")
    _skill(tmp_path / ".hidden/SKILL.md")
    (tmp_path / "alias").symlink_to(tmp_path / ".hidden", target_is_directory=True)
    assert _walk(tmp_path, direct=True)[0] == ["alias/SKILL.md", "direct/SKILL.md"]
    assert _walk(tmp_path, direct=True, follow=False)[0] == ["direct/SKILL.md"]


def test_cyclic_root_is_a_recoverable_inventory_error(tmp_path):
    root = tmp_path / "cycle"
    root.symlink_to(root, target_is_directory=True)
    found, events = _walk(root)
    assert found == []
    assert len(events) == 1 and events[0]["type"] == "warning"
