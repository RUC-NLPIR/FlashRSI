"""Keep installed Codex plugin resources separate from plugin runtime data."""

import inspect
import json
import shutil
from pathlib import Path

import pytest

from flashrsi.agents import Codex
from flashrsi.core import Snapshot


@pytest.fixture
def plugin_agent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    shutil.copyfile(
        Path(inspect.getfile(Codex)).with_name("components.yaml"),
        source / "components.yaml",
    )
    (source / "config.toml").write_text(
        '[features]\nplugins = true\n[plugins."demo@flashrsi"]\nenabled = true\n'
    )
    bundle = source / "plugins/cache/flashrsi/demo/local"
    files = {
        ".codex-plugin/plugin.json": json.dumps({"name": "demo"}),
        ".codex-remote-plugin-install.json": json.dumps(
            {"remote_plugin_id": "plugins_fixture"}
        ),
        ".app.json": json.dumps({"apps": {}}),
        "skills/probe/SKILL.md": "---\nname: probe\ndescription: Probe\n---\nBASELINE\n",
        "hooks/hooks.json": json.dumps({"hooks": {}}),
        "assets/schema.json": json.dumps({"type": "object"}),
    }
    for relative, content in files.items():
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    runtime_files = {
        "plugins/data/demo@flashrsi/session.json": '{"last_task": "PRIVATE_TASK"}',
        "plugins/data/demo@flashrsi/oauth.json": '{"refresh_token": "PRIVATE_TOKEN"}',
        "plugins/state.json": '{"last_session": "PRIVATE_SESSION"}',
        "plugins/credentials.json": '{"token": "PRIVATE_CREDENTIAL"}',
        "plugins/marketplaces/catalog.json": '{"fetched_at": "PRIVATE_FETCH"}',
    }
    for relative, content in runtime_files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    agent = Codex(
        {"source_dir": source, "llm": {"model_name": "gpt-5", "api_key": "test"}}
    )
    return agent, source, bundle.relative_to(source), files, runtime_files


def test_capture_and_roundtrip_preserve_bundle_without_plugin_runtime_data(
    plugin_agent, tmp_path
):
    agent, source, relative_root, bundle_files, runtime_files = plugin_agent
    snapshot = agent.snapshot
    assert set(snapshot.files) == {
        "config.toml",
        *((relative_root / relative).as_posix() for relative in bundle_files),
    }
    assert (
        snapshot.files["config.toml"].content == (source / "config.toml").read_bytes()
    )
    for relative, content in bundle_files.items():
        entry = snapshot.files[(relative_root / relative).as_posix()]
        assert entry.component == "plugin"
        assert entry.content == content.encode()

    saved = tmp_path / "snapshot.json"
    snapshot.save(saved)
    restored = Snapshot.load(saved)
    assert restored.id == snapshot.id
    assert restored.files == snapshot.files
    with restored.check_out() as directory:
        for relative in bundle_files:
            assert (directory / relative_root / relative).is_file()
        for relative in runtime_files:
            assert not (directory / relative).exists()
            assert (source / relative).is_file()


def test_plugin_scope_edits_bundle_and_rejects_runtime_data(plugin_agent):
    agent, _, relative_root, _, _ = plugin_agent
    agent.set_scope({"plugin": "rw"})
    baseline = agent.snapshot
    relative_skill = relative_root / "skills/probe/SKILL.md"
    with baseline.check_out() as directory:
        assert not (directory / "config.toml").exists()
        path = directory / relative_skill
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)
    assert b"CANDIDATE" in candidate.files[relative_skill.as_posix()].content
    assert candidate.files["config.toml"] == baseline.files["config.toml"]

    with baseline.check_out() as directory:
        path = directory / "plugins/data/demo@flashrsi/session.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"last_task": "NEW_PRIVATE_TASK"}')
        with pytest.raises(ValueError, match="path must match exactly one component"):
            baseline.commit(directory)
