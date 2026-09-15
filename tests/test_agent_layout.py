import asyncio
import importlib.util
import sys
from itertools import count

import pytest

from flashrsi.core import Agent, Snapshot, Task, Trajectory

_MODULE_IDS = count()
_ADAPTER = """from flashrsi.core import Agent, Trajectory

class LocalAgent(Agent):
    name = "local_agent"

    async def _run(self, prompt, working_dir=None):
        return Trajectory(output=(self.files_dir / "skills/main.md").read_text())
"""


def _load_adapter(root, monkeypatch, *, source=_ADAPTER):
    root.mkdir(parents=True, exist_ok=True)
    entry = root / "__init__.py"
    entry.write_text(source)
    name = f"_flashrsi_layout_test_{next(_MODULE_IDS)}"
    spec = importlib.util.spec_from_file_location(name, entry)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module.LocalAgent


def _write_files(root, *, manifest="skill: ['skills/**']\n", answer="bundled answer"):
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "skills/main.md").write_text(answer)
    (root / "components.yaml").write_text(manifest)
    return root


def test_module_directory_discovers_manifest_independently_of_cwd(
    tmp_path, monkeypatch
):
    root = _write_files(tmp_path / "bundled")
    agent_type = _load_adapter(root, monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    agent = agent_type()

    assert agent.component_rules == {"skill": ("skills/**",)}
    assert set(agent.snapshot.files) == {"skills/main.md"}
    assert asyncio.run(agent.run("question")).output == "bundled answer"


@pytest.mark.parametrize("path_style", ["absolute", "relative"])
def test_source_override_uses_its_own_manifest_and_files(
    tmp_path, monkeypatch, path_style
):
    bundled = _write_files(tmp_path / "bundled", answer="original")
    agent_type = _load_adapter(bundled, monkeypatch)
    external = _write_files(
        tmp_path / "external", manifest="prompt: ['skills/**']\n", answer="external"
    )
    monkeypatch.chdir(tmp_path)
    if path_style == "relative":
        source = "external"
    else:
        source = external

    agent = agent_type({"agent": {"source_dir": source, "model_name": "offline"}})

    assert agent.component_rules == {"prompt": ("skills/**",)}
    assert agent.snapshot.files["skills/main.md"].component == "prompt"
    assert asyncio.run(agent.run("question")).output == "external"


def test_manifest_is_fixed_at_capture_and_persists_with_candidates(
    tmp_path, monkeypatch
):
    root = _write_files(tmp_path / "bundled")
    agent_type = _load_adapter(root, monkeypatch)
    agent = agent_type()
    baseline = agent.snapshot
    (root / "components.yaml").write_text("prompt: ['skills/**']\n")
    (root / "skills/main.md").write_text("external changes")
    with pytest.raises(TypeError):
        agent.component_rules["skill"] = ("**",)
    with pytest.raises(AttributeError):
        agent.component_rules = {"prompt": ("skills/**",)}

    with baseline.check_out() as directory:
        (directory / "skills/main.md").write_text("candidate")
        candidate = baseline.commit(directory)
    path = tmp_path / "candidate.json"
    candidate.save(path)
    restored = Snapshot.load(path)
    result = asyncio.run(agent.rollout([Task("q", "question")], snapshot=restored))

    assert result[0].output == "candidate"
    assert agent.snapshot is baseline
    assert restored.component_rules == {"skill": ("skills/**",)}
    assert asyncio.run(agent.run("question")).output == "bundled answer"


def test_module_without_manifest_remains_a_stateless_worker(tmp_path, monkeypatch):
    source = _ADAPTER.replace(
        '(self.files_dir / "skills/main.md").read_text()', "prompt.upper()"
    )
    agent_type = _load_adapter(tmp_path / "worker", monkeypatch, source=source)
    agent = agent_type()

    assert agent.component_rules == {}
    assert asyncio.run(agent.run("hello")).output == "HELLO"
    with pytest.raises(RuntimeError, match="no versioned files"):
        agent.snapshot


def test_nonfilesystem_class_can_use_explicit_source(tmp_path):
    class InteractiveAgent(Agent):
        __module__ = "_nonexistent_interactive_module"
        name = "interactive"

        async def _run(self, prompt, working_dir=None):
            return Trajectory(output=(self.files_dir / "skills/main.md").read_text())

    source = _write_files(tmp_path / "external", answer="explicit files")
    agent = InteractiveAgent({"source_dir": source})
    assert asyncio.run(agent.run("question")).output == "explicit files"


@pytest.mark.parametrize("bad_source", ["missing", "file", "missing_manifest"])
def test_explicit_source_never_falls_back_to_bundled_manifest(
    tmp_path, monkeypatch, bad_source
):
    bundled = _write_files(tmp_path / "bundled")
    agent_type = _load_adapter(bundled, monkeypatch)
    external = tmp_path / "external"
    if bad_source == "file":
        external.write_text("not a directory")
    elif bad_source == "missing_manifest":
        external.mkdir()

    with pytest.raises(ValueError, match="source_dir|components.yaml|directory"):
        agent_type({"source_dir": external})


@pytest.mark.parametrize(
    "manifest",
    [
        "",
        "null\n",
        "[]\n",
        "skill: 'skills/**'\n",
        "skill: []\n",
        "skill: [123]\n",
        "skill: ['../outside/**']\n",
        "skill: ['/absolute/**']\n",
        "skill: ['skills/**']\nskill: ['other/**']\n",
        "true: ['skills/**']\n",
        "[skill, code]: ['skills/**']\n",
        "skill: !!python/object/apply:builtins.print ['private-content']\n",
        "skill: [\n",
    ],
)
def test_invalid_manifests_fail_clearly_without_dumping_content(
    tmp_path, monkeypatch, manifest
):
    root = _write_files(tmp_path / "bundled", manifest=manifest)
    agent_type = _load_adapter(root, monkeypatch)

    with pytest.raises(ValueError, match="components.yaml") as error:
        agent_type()
    assert "private-content" not in str(error.value)


def test_empty_manifest_creates_an_empty_version(tmp_path, monkeypatch):
    root = _write_files(tmp_path / "bundled", manifest="{}\n")
    agent = _load_adapter(root, monkeypatch)()

    assert agent.component_rules == {}
    assert agent.snapshot.files == {}
    with agent.snapshot.check_out() as directory:
        assert list(directory.iterdir()) == []


@pytest.mark.parametrize("pattern", ["**", "*.py", "__init__.py"])
def test_adapter_module_cannot_be_captured_as_evolvable_code(
    tmp_path, monkeypatch, pattern
):
    root = _write_files(tmp_path / "bundled", manifest=f"code: ['{pattern}']\n")
    agent_type = _load_adapter(root, monkeypatch)

    with pytest.raises(ValueError, match="adapter|module|__init__"):
        agent_type()


def test_external_broad_rule_excludes_manifest_but_collects_execution_files(
    tmp_path, monkeypatch
):
    agent_type = _load_adapter(tmp_path / "adapter", monkeypatch)
    external = _write_files(tmp_path / "external", manifest="code: ['**']\n")
    agent = agent_type({"source_dir": external})

    assert set(agent.snapshot.files) == {"skills/main.md"}
    assert agent.snapshot.files["skills/main.md"].component == "code"
    with agent.snapshot.check_out() as directory:
        assert not (directory / "components.yaml").exists()
        (directory / "components.yaml").write_text("code: ['**']\n")
        with pytest.raises(ValueError, match="components.yaml|reserved"):
            agent.snapshot.commit(directory)
