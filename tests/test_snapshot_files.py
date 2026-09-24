import os
import shutil

import pytest

from flashrsi.core import Snapshot, SnapshotFile
from flashrsi.core.snapshot import _create_snapshot, discard_runtime_files

RULES = {"skill": ("skills/**",), "prompt": ("prompts/*.md",), "code": ("src/**",)}


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "files"
    for path, content in {
        "skills/main.md": b"initial skill",
        "prompts/system.md": b"initial prompt",
        "src/run.py": b"print('initial')\n",
    }.items():
        file = directory / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    (directory / "src/run.py").chmod(0o755)
    return directory


@pytest.fixture
def snapshot(source):
    return Snapshot.from_directory(source, agent_type="test", component_rules=RULES)


def test_directory_is_copied_and_export_preserves_bytes_tags_modes(
    snapshot, source, tmp_path
):
    (source / "skills/main.md").write_text("external edit")
    assert snapshot.files["skills/main.md"] == SnapshotFile(b"initial skill", "skill")
    with snapshot.check_out(working_dir=tmp_path / "working") as directory:
        assert directory.parent.name == "working"
        assert (directory / "skills/main.md").read_bytes() == b"initial skill"
        assert (directory / "src/run.py").stat().st_mode & 0o111
        assert not (directory / "skills/main.md").stat().st_mode & 0o111
        candidate = snapshot.commit(directory)
        assert candidate.files == snapshot.files
        assert candidate.parent_id == snapshot.id
    assert not directory.exists()


def test_checkout_cleanup_on_failure_and_commit_accepts_normal_directory(
    snapshot, tmp_path
):
    copied = tmp_path / "edited"
    with pytest.raises(RuntimeError, match="worker failed"):
        with snapshot.check_out() as directory:
            shutil.copytree(directory, copied)
            raise RuntimeError("worker failed")
    assert not directory.exists()
    (copied / "skills/main.md").write_text("edited outside checkout")
    candidate = snapshot.commit(copied)
    assert candidate.parent_id == snapshot.id
    assert candidate.files["skills/main.md"].content == b"edited outside checkout"


def test_parallel_exports_have_explicit_independent_baselines(snapshot):
    with snapshot.check_out() as first, snapshot.check_out() as second:
        assert first != second
        (first / "skills/main.md").write_text("first")
        one = snapshot.commit(first)
        assert (second / "skills/main.md").read_text() == "initial skill"
        (second / "skills/main.md").write_text("second")
        two = snapshot.commit(second)
    assert one.parent_id == two.parent_id == snapshot.id
    assert snapshot.files["skills/main.md"].content == b"initial skill"


def test_add_delete_rename_and_binary_executable_files(snapshot):
    with snapshot.check_out() as directory:
        (directory / "skills/main.md").rename(directory / "skills/renamed.md")
        nested = directory / "skills/nested/new.bin"
        nested.parent.mkdir()
        nested.write_bytes(b"\x00\xff")
        nested.chmod(0o755)
        candidate = snapshot.commit(directory)
    assert "skills/main.md" not in candidate.files
    assert candidate.files["skills/renamed.md"].component == "skill"
    assert candidate.files["skills/nested/new.bin"] == SnapshotFile(
        b"\x00\xff", "skill", True
    )


def test_loaded_snapshot_classifies_new_files_without_external_rules(
    snapshot, tmp_path
):
    path = tmp_path / "snapshot.json"
    snapshot.save(path)
    restored = Snapshot.load(path)
    with restored.check_out() as directory:
        (directory / "skills/new.md").write_text("new skill")
        (directory / "src/new.py").write_text("new source")
        candidate = restored.commit(directory)

    assert candidate.files["skills/new.md"].component == "skill"
    assert candidate.files["src/new.py"].component == "code"
    assert candidate.parent_id == restored.id
    assert candidate.component_rules == RULES
    assert restored.files == snapshot.files


@pytest.mark.parametrize("change", ["content", "delete", "mode", "rename", "add"])
def test_commit_automatically_rejects_read_only_changes(snapshot, change):
    view = snapshot._with_scope({"skill": "rw", "code": "r", "prompt": "r"})
    with view.check_out() as directory:
        protected = directory / "src/run.py"
        assert protected.stat().st_mode & 0o777 == 0o555
        if change == "content":
            protected.chmod(0o755)
            protected.write_text("changed")
        elif change == "delete":
            protected.unlink()
        elif change == "mode":
            protected.chmod(0o644)
        elif change == "rename":
            protected.rename(directory / "skills/stolen.py")
        else:
            (directory / "src/new.py").write_text("new")
        with pytest.raises(ValueError, match="outside allowed components"):
            view.commit(directory)


@pytest.mark.parametrize("path", ["unknown.md", "prompts/nested/new.md"])
def test_unclassified_files_and_single_star_not_crossing_directories(snapshot, path):
    with snapshot.check_out() as directory:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("new")
        with pytest.raises(ValueError, match="exactly one component"):
            snapshot.commit(directory)


def test_classification_conflicts_rejected_on_import_and_commit(source):
    rules = {**RULES, "other": ("skills/new*",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        (directory / "skills/new.md").write_text("new")
        with pytest.raises(ValueError, match="exactly one component"):
            snapshot.commit(directory)
    (source / "skills/new.md").write_text("new")
    with pytest.raises(ValueError, match="exactly one component"):
        Snapshot.from_directory(source, agent_type="test", component_rules=rules)


@pytest.mark.parametrize("invalid", ["type", "root", "content", "none"])
def test_candidate_check_enforces_bound_scope_after_loading(
    snapshot, invalid, tmp_path
):
    files = dict(snapshot.files)
    if invalid == "type":
        candidate = _create_snapshot(files, agent_type="other", component_rules=RULES)
    elif invalid == "root":
        files["skills/main.md"] = SnapshotFile(b"other", "skill")
        candidate = _create_snapshot(files, agent_type="test", component_rules=RULES)
    elif invalid == "none":
        candidate = None
    else:
        files["src/run.py"] = SnapshotFile(b"changed", "code", True)
        candidate = _create_snapshot(
            files, agent_type="test", component_rules=RULES, parent=snapshot
        )
    if candidate is not None:
        path = tmp_path / "candidate.json"
        candidate.save(path)
        candidate = Snapshot.load(path)
    with pytest.raises(ValueError):
        snapshot._with_scope({"skill": "rw"})._validate_candidate(candidate)


def test_checkout_visibility_and_read_only_modes_preserve_full_candidate(snapshot):
    view = snapshot._with_scope({"skill": "rw", "prompt": "r"})
    with view.check_out() as directory:
        assert not (directory / "src").exists()
        assert (directory / "prompts/system.md").stat().st_mode & 0o777 == 0o444
        assert (directory / "skills/main.md").stat().st_mode & 0o777 == 0o644
        (directory / "skills/main.md").write_text("improved skill")
        candidate = view.commit(directory)

    assert candidate.files["skills/main.md"].content == b"improved skill"
    assert candidate.files["prompts/system.md"] == snapshot.files["prompts/system.md"]
    assert candidate.files["src/run.py"] == snapshot.files["src/run.py"]
    assert candidate.parent_id == snapshot.id
    assert candidate.component_rules == snapshot.component_rules
    assert candidate._scope == view._scope
    with candidate.check_out() as directory:
        assert not (directory / "src").exists()
        assert (directory / "prompts/system.md").stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("permission", [None, "none"])
@pytest.mark.parametrize("path", ["src/run.py", "src/new.py"])
def test_commit_rejects_writes_at_hidden_component_paths(snapshot, permission, path):
    scope = {"skill": "rw", "prompt": "r"}
    if permission is not None:
        scope["code"] = permission
    view = snapshot._with_scope(scope)
    with view.check_out() as directory:
        target = directory / path
        target.parent.mkdir()
        target.write_text("write into hidden code")
        with pytest.raises(ValueError, match="hidden component"):
            view.commit(directory)


def test_empty_scope_exports_nothing_and_commit_retains_all_files(snapshot):
    view = snapshot._with_scope({})
    with view.check_out() as directory:
        assert list(directory.iterdir()) == []
        candidate = view.commit(directory)
    assert candidate.files == snapshot.files
    assert candidate._scope == {}
    assert candidate.parent_id == snapshot.id


def test_read_only_scope_cleanup_on_error(snapshot):
    view = snapshot._with_scope({"code": "r", "prompt": "r"})
    with pytest.raises(RuntimeError, match="worker failed"):
        with view.check_out() as directory:
            assert (directory / "src/run.py").stat().st_mode & 0o777 == 0o555
            assert (directory / "prompts/system.md").stat().st_mode & 0o777 == 0o444
            raise RuntimeError("worker failed")
    assert not directory.exists()


def test_full_runtime_export_and_loaded_snapshot_ignore_editing_scope(
    snapshot, tmp_path
):
    view = snapshot._with_scope({"skill": "r"})
    with view._export(full=True) as directory:
        assert (directory / "skills/main.md").stat().st_mode & 0o777 == 0o644
        assert (directory / "src/run.py").stat().st_mode & 0o777 == 0o755
        assert snapshot.commit(directory).files == snapshot.files

    path = tmp_path / "snapshot.json"
    view.save(path)
    restored = Snapshot.load(path)
    with restored.check_out() as directory:
        assert (directory / "src/run.py").exists()
        (directory / "skills/main.md").write_text("loaded scope is unrestricted")
        candidate = restored.commit(directory)
    assert candidate.files["skills/main.md"].content == b"loaded scope is unrestricted"


@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "fifo"])
def test_import_and_commit_reject_links_and_special_files(
    snapshot, source, tmp_path, kind
):
    external = tmp_path / "external"
    external.mkdir()
    (external / "private").write_text("must not be imported")

    def add_special(directory):
        target = directory / "skills/special"
        if kind == "fifo":
            os.mkfifo(target)
        else:
            target.symlink_to(
                {
                    "file": external / "private",
                    "directory": external,
                    "dangling": external / "missing",
                }[kind]
            )

    with snapshot.check_out() as directory:
        add_special(directory)
        with pytest.raises(ValueError, match="regular files"):
            snapshot.commit(directory)
    add_special(source)
    with pytest.raises(ValueError, match="regular files"):
        Snapshot.from_directory(source, agent_type="test", component_rules=RULES)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".git/config",
        "logs/run.txt",
        "src/__pycache__/x.pyc",
        ".venv/bin/python",
    ],
)
def test_runtime_artifacts_rejected_even_with_broad_rules(source, path):
    rules = {"code": ("**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("runtime data")
        with pytest.raises(ValueError, match="cannot enter a Snapshot"):
            snapshot.commit(directory)


@pytest.mark.parametrize(
    "paths", [("skills/A.md", "skills/a.md"), ("skills/A/x", "skills/a/y")]
)
def test_checkout_never_silently_merges_distinct_paths(snapshot, tmp_path, paths):
    (tmp_path / "CaseProbe").mkdir()
    case_sensitive = not (tmp_path / "caseprobe").exists()
    files = dict(snapshot.files)
    files.update({path: SnapshotFile(path.encode(), "skill") for path in paths})
    candidate = _create_snapshot(
        files, agent_type="test", component_rules=RULES, parent=snapshot
    )
    if case_sensitive:
        with candidate.check_out(working_dir=tmp_path / "working") as directory:
            assert candidate.commit(directory).files == files
    else:
        with pytest.raises(ValueError, match="filesystem"):
            with candidate.check_out(working_dir=tmp_path / "working"):
                pytest.fail("checkout silently merged distinct Snapshot paths")
    assert not list((tmp_path / "working").iterdir())


def test_capture_collects_only_declared_files_and_ignores_runtime_data(source):
    (source / "README.md").write_text("documentation")
    for relative in (".env", "src/__pycache__/run.pyc", ".git/config", "logs/run.txt"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"runtime data")
    captured = Snapshot._capture(source, agent_type="test", component_rules=RULES)
    assert set(captured.files) == {"src/run.py", "skills/main.md", "prompts/system.md"}
    assert captured.files["src/run.py"].executable
    assert (source / ".env").read_bytes() == b"runtime data"


def test_capture_keeps_real_source_modules_and_config_templates(source):
    (source / "src/logs").mkdir()
    (source / "src/logs/logger.py").write_text("logger code")
    (source / ".env.example").write_text("API_KEY=")
    rules = {**RULES, "config": (".env.example",)}
    captured = Snapshot._capture(source, agent_type="test", component_rules=rules)
    assert captured.files["src/logs/logger.py"].component == "code"
    assert captured.files[".env.example"].component == "config"
    with captured.check_out() as directory:
        assert (directory / "src/logs/logger.py").read_text() == "logger code"


def test_capture_does_not_read_unselected_files(source, monkeypatch):
    (source / "large.bin").write_bytes(b"unused")
    original = type(source).read_bytes
    seen = []

    def read(path):
        seen.append(path.name)
        assert path.name != "large.bin"
        return original(path)

    monkeypatch.setattr(type(source), "read_bytes", read)
    Snapshot._capture(source, agent_type="test", component_rules=RULES)
    assert set(seen) == {"run.py", "main.md", "system.md"}


def test_capture_rejects_component_conflicts(source):
    with pytest.raises(ValueError, match="exactly one component"):
        Snapshot._capture(
            source,
            agent_type="test",
            component_rules={**RULES, "other": ("skills/**",)},
        )


@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "fifo"])
def test_capture_rejects_selected_links_and_special_files(source, tmp_path, kind):
    external = tmp_path / "external"
    external.mkdir()
    (external / "file").write_text("external data")
    selected = source / "skills/selected"
    if kind == "fifo":
        os.mkfifo(selected)
    else:
        selected.symlink_to(
            {
                "file": external / "file",
                "directory": external,
                "dangling": external / "missing",
            }[kind]
        )
    with pytest.raises(ValueError, match="regular files"):
        Snapshot._capture(source, agent_type="test", component_rules=RULES)


def test_capture_empty_directory_and_rejects_linked_root(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        Snapshot._capture(empty, agent_type="test", component_rules=RULES).files == {}
    )
    link = tmp_path / "link"
    link.symlink_to(empty)
    with pytest.raises(ValueError, match="symbolic link"):
        Snapshot._capture(link, agent_type="test", component_rules=RULES)


def test_capture_skips_unrelated_links_directories_and_noncanonical_names(
    source, tmp_path
):
    external = tmp_path / "docs"
    external.mkdir()
    (external / "doc.txt").write_text("unrelated")
    (source / "docs-link").symlink_to(external)
    (source / "unrelated").mkdir()
    (source / "unrelated/nested-link").symlink_to(external)
    (source / "unrelated\\name.txt").write_text("not a portable snapshot path")
    captured = Snapshot._capture(source, agent_type="test", component_rules=RULES)
    assert set(captured.files) == {"src/run.py", "skills/main.md", "prompts/system.md"}


@pytest.mark.parametrize("rule", ["skills/linked/*.md", "skills/**/*.md", "**/*.md"])
def test_capture_rejects_link_hiding_selected_descendants(source, tmp_path, rule):
    external = tmp_path / "external"
    external.mkdir()
    (external / "answer.md").write_text("external")
    (source / "skills/linked").symlink_to(external)
    with pytest.raises(ValueError, match="regular files"):
        Snapshot._capture(source, agent_type="test", component_rules={"skill": (rule,)})


def test_discarding_runtime_files_lets_a_tool_edited_directory_commit(source):
    """An Agent editing a checkout also leaves what its own tools produce.

    ``commit`` refuses those paths outright, which is right for a curated tree
    but would cost a whole evolution iteration here.
    """
    rules = {"skill": ("skills/**",), "prompt": ("prompts/**",), "code": ("src/**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        (directory / "src/run.py").write_text("print('edited')\n")
        (directory / "src/__pycache__").mkdir()
        (directory / "src/__pycache__/run.pyc").write_bytes(b"\x00")
        (directory / "src/build.log").write_text("tool output")
        (directory / "src/.env").write_text("SECRET=value")

        discarded = discard_runtime_files(directory)
        candidate = snapshot.commit(directory)

    # A removed directory is reported once; its contents went with it.
    assert discarded == ("src/.env", "src/__pycache__", "src/build.log")
    assert candidate.files["src/run.py"].content == b"print('edited')\n"
    assert set(candidate.files) == set(snapshot.files)


def test_discarding_runtime_files_is_not_a_licence_to_add_anything(source):
    """A file the Agent genuinely added is still classified by the rules."""
    rules = {"skill": ("skills/**",), "prompt": ("prompts/**",), "code": ("src/**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        (directory / "nowhere.md").write_text("unplaceable")
        assert discard_runtime_files(directory) == ()
        with pytest.raises(ValueError, match="exactly one component"):
            snapshot.commit(directory)


def test_changed_paths_reports_the_edit_the_snapshot_itself_sees(source):
    """File identity is bytes, component and the executable bit."""
    rules = {"skill": ("skills/**",), "prompt": ("prompts/**",), "code": ("src/**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        (directory / "skills/main.md").write_text("edited")
        (directory / "skills/added.md").write_text("new")
        (directory / "prompts/system.md").unlink()
        candidate = snapshot.commit(directory)

    # Edited, added and removed paths alike; untouched files are absent.
    assert snapshot.changed_paths(candidate) == (
        "prompts/system.md",
        "skills/added.md",
        "skills/main.md",
    )
    assert snapshot.changed_paths(snapshot) == ()
    # A commit always mints a new id, so identity cannot stand in for this.
    assert candidate.id != snapshot.id


def test_changed_paths_notices_a_mode_change_with_identical_bytes(source):
    rules = {"code": ("src/**",), "skill": ("skills/**",), "prompt": ("prompts/**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    with snapshot.check_out() as directory:
        (directory / "src/run.py").chmod(0o644)
        candidate = snapshot.commit(directory)

    assert snapshot.files["src/run.py"].content == candidate.files["src/run.py"].content
    assert snapshot.changed_paths(candidate) == ("src/run.py",)


def test_changed_paths_refuses_a_snapshot_from_another_lineage(source, tmp_path):
    rules = {"skill": ("skills/**",), "prompt": ("prompts/**",), "code": ("src/**",)}
    snapshot = Snapshot.from_directory(source, agent_type="test", component_rules=rules)
    other = Snapshot.from_directory(source, agent_type="other", component_rules=rules)

    with pytest.raises(ValueError, match="different Agent type"):
        snapshot.changed_paths(other)
