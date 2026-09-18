"""Check the native Harbor boundary without Docker or remote model calls."""

import asyncio
import json
import os
import shlex
import shutil
import sys
import warnings
from dataclasses import replace
from datetime import date
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("harbor")

from harbor.agents.installed.base import NonZeroAgentExitCodeError  # noqa: E402
from harbor.environments.base import BaseEnvironment, ExecResult  # noqa: E402
from harbor.environments.factory import EnvironmentFactory  # noqa: E402
from harbor.models.trial.paths import TrialPaths  # noqa: E402

from flashrsi._records import _config_record, _trajectory_record  # noqa: E402
from flashrsi.agents import ClaudeCode, MiniAgent  # noqa: E402
from flashrsi.benchmarks import TerminalBench  # noqa: E402
from flashrsi.core import Snapshot, Task, Trajectory  # noqa: E402
from flashrsi.integrations import _container, harbor  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore:Task.checksum will be deprecated")


@pytest.fixture
def task(tmp_path):
    directory = tmp_path / "native-task"
    (directory / "environment").mkdir(parents=True)
    (directory / "environment/Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /\n")
    (directory / "tests").mkdir()
    (directory / "task.toml").write_text(
        '[verifier.env]\nVERIFIER_DIR = "/logs/verifier"\n'
    )
    (directory / "instruction.md").write_text("Write SOLVED to answer.txt")
    (directory / "tests/test.sh").write_text(
        '#!/bin/sh\nmkdir -p "$VERIFIER_DIR"\n'
        'if [ "$(cat answer.txt 2>/dev/null)" = SOLVED ]; then\n'
        '  echo 1 > "$VERIFIER_DIR/reward.txt"\n'
        'else\n  echo 0 > "$VERIFIER_DIR/reward.txt"\nfi\n'
        'echo "native verifier ran"\n'
    )
    native = harbor.HarborTask(directory)
    with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
        checksum = native.checksum
    return Task(
        native.name,
        native.instruction,
        env=str(directory),
        metadata={"task_checksum": checksum},
    )


@pytest.fixture(params=[ClaudeCode, MiniAgent], ids=["claude_code", "miniagent"])
def agent(monkeypatch, request):
    monkeypatch.setattr(harbor.shutil, "which", lambda command: "/fake/docker")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "native-private-token")
    monkeypatch.setenv("OPENAI_API_KEY", "native-private-token")
    target = request.param(
        {
            "name": request.param.name,
            "llm": {"model_name": "local-model", "api_key": "target-private-key"},
            "timeout": 19,
            "max_turns": 5,
            "allowed_tools": ["Read", "Write"],
            "harbor": {"setup_timeout": 23, "cleanup_grace": 7},
            "custom": {"created": date(2026, 9, 17)},
        }
    )
    harbor.bind(target)
    return target


@pytest.fixture
def fake_trial(monkeypatch):
    state = SimpleNamespace(calls=[], variant="success", change_defaults=None)

    async def create(config):
        payload = Path(config.agent.kwargs["payload_dir"])
        request = json.loads((payload / "request.json").read_text())
        snapshot = Snapshot.load(payload / "snapshot.json")
        runtime = yaml.safe_load(request["config_yaml"])
        paths = TrialPaths(config.trials_dir / "fake-trial")
        paths.mkdir()
        state.calls.append((config, payload, request, snapshot, runtime))
        assert (payload / "request.json").stat().st_mode & 0o777 == 0o600
        assert (payload / "package/flashrsi/integrations/_container.py").is_file()
        assert not list((payload / "package").rglob("__pycache__"))
        state.requirements = (payload / "requirements.txt").read_text()
        if state.variant == "create-error":
            raise RuntimeError("create failed target-private-key")

        async def run():
            if state.change_defaults:
                state.change_defaults()
            if state.variant == "cancel":
                raise asyncio.CancelledError()
            if state.variant == "raise":
                raise RuntimeError("run failed native-private-token")
            record = _trajectory_record(
                Trajectory(
                    output="finished target-private-key",
                    messages=(
                        {
                            "type": "RunConfig",
                            "config": _config_record(runtime),
                            "snapshot_id": "wrong"
                            if state.variant == "wrong-snapshot"
                            else snapshot.id,
                        },
                        {"type": "AssistantMessage", "parent_tool_use_id": "child-1"},
                        {"type": "HarborVerifier", "rewards": {"reward": 0.99}},
                    ),
                    usage={"num_turns": 2, "detail": "native-private-token"},
                )
            )
            if state.variant != "missing-output":
                (paths.agent_dir / "flashrsi.json").write_text(
                    json.dumps(record, default=dict)
                )
            paths.test_stdout_path.write_text("verification target-private-key")
            paths.test_stderr_path.write_text("diagnostic native-private-token")
            exception = (
                SimpleNamespace(
                    exception_message="native error target-private-key",
                    exception_type="RuntimeError",
                )
                if state.variant == "native-error"
                else None
            )
            return SimpleNamespace(
                id="trial-id",
                verifier_result=None
                if state.variant == "no-rewards"
                else SimpleNamespace(rewards={"reward": 1.0}),
                exception_info=exception,
            )

        return SimpleNamespace(paths=paths, run=run)

    monkeypatch.setattr(harbor, "Trial", SimpleNamespace(create=create))
    return state


def test_trial_arguments_trace_and_host_verifier_event(agent, task, fake_trial):
    agent.config.source_dir = Path(task.env)
    baseline = agent.snapshot
    (result,) = asyncio.run(agent.rollout([task]))
    config, payload, request, snapshot, runtime = fake_trial.calls[0]
    assert config.task.path == Path(task.env)
    assert config.agent.import_path == "flashrsi.integrations.harbor:_SnapshotAgent"
    assert config.agent.override_timeout_sec == 26
    assert config.agent.override_setup_timeout_sec == 23
    assert config.environment.type == "docker" and config.environment.delete
    assert config.agent.kwargs == {"payload_dir": str(payload)}
    assert "target-private-key" not in config.model_dump_json()
    assert "native-private-token" not in config.model_dump_json()
    assert request["prompt"] == task.question
    assert request["agent_class"] == (
        f"{type(agent).__module__}:{type(agent).__qualname__}"
    )
    assert "environment" not in request
    assert "native-private-token" not in json.dumps(request)
    assert "PyYAML==" in fake_trial.requirements
    if isinstance(agent, ClaudeCode):
        assert "claude-agent-sdk==" in fake_trial.requirements
        assert "openai==" not in fake_trial.requirements
    else:
        assert "openai==" in fake_trial.requirements
        assert "requests==" in fake_trial.requirements
        assert "claude-agent-sdk" not in fake_trial.requirements
    assert runtime["custom"]["created"] == date(2026, 9, 17)
    assert runtime["source_dir"] == task.env
    assert snapshot.id == baseline.id
    assert not payload.exists()
    assert result.task == task
    assert result.status == "finished"
    assert result.messages[0]["snapshot_id"] == baseline.id
    assert result.messages[1]["parent_tool_use_id"] == "child-1"
    assert result.messages[-1]["type"] == "HarborVerifier"
    assert result.messages[-1]["rewards"] == {"reward": 1.0}
    assert result.messages[-1]["task_id"] == task.task_id
    assert result.messages[-1]["task_checksum"] == task.metadata["task_checksum"]
    assert result.messages[-1]["stdout"] == "verification [REDACTED]"
    assert result.usage["num_turns"] == 2
    serialized = json.dumps(_trajectory_record(result), default=dict)
    assert "target-private-key" not in serialized
    assert "native-private-token" not in serialized


def test_entire_batch_keeps_candidate_and_configuration(agent, task, fake_trial):
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        skill = directory / "skills/batch-check.md"
        skill.parent.mkdir(exist_ok=True)
        skill.write_text("CANDIDATE")
        candidate = baseline.commit(directory)
    original = agent.config

    def change_defaults():
        original.llm.model_name = "later-model"
        original.timeout = 3
        agent.update(candidate)

    fake_trial.change_defaults = change_defaults
    results = asyncio.run(agent.rollout([task, task], snapshot=candidate))
    assert len(results) == 2
    assert all(call[3].id == candidate.id for call in fake_trial.calls)
    assert all(
        call[4]["llm"]["model_name"] == "local-model" for call in fake_trial.calls
    )
    assert all(call[4]["timeout"] == 19 for call in fake_trial.calls)
    assert agent.config.llm.model_name == "later-model"


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("missing-output", "without a FlashRSI trajectory"),
        ("wrong-snapshot", "requested Snapshot"),
        ("no-rewards", "without rewards"),
        ("native-error", "native error [REDACTED]"),
        ("raise", "run failed [REDACTED]"),
        ("create-error", "create failed [REDACTED]"),
    ],
)
def test_false_success_and_failures_are_error_trajectories(
    agent, task, fake_trial, variant, expected
):
    fake_trial.variant = variant
    (result,) = asyncio.run(agent.rollout([task]))
    assert result.status == "error"
    assert expected in result.error_message
    assert result.messages[-1]["type"] == "HarborVerifier"
    assert "error" in result.messages[-1]
    assert not fake_trial.calls[0][1].exists()


def test_cancellation_propagates_and_cleans_staged_credentials(agent, task, fake_trial):
    fake_trial.variant = "cancel"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.rollout([task]))
    assert not fake_trial.calls[0][1].exists()


def test_native_task_without_timeout_uses_default(agent, task, fake_trial):
    del agent.config["timeout"]
    asyncio.run(agent.rollout([task]))
    assert fake_trial.calls[0][4]["timeout"] == 300


def test_changed_task_is_rejected_before_trial(agent, task, fake_trial):
    (Path(task.env) / "tests/test.sh").write_text("changed test")
    with pytest.raises(ValueError, match="files changed"):
        asyncio.run(agent.rollout([task]))
    assert not fake_trial.calls


@pytest.mark.parametrize("mounted", [False, True])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("has_output", [False, True])
def test_bridge_shell_arguments_and_error_output_download(
    tmp_path, mounted, stream, has_output
):
    payload = tmp_path / "payload with spaces"
    payload.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    calls = []

    class Environment:
        capabilities = SimpleNamespace(mounted=mounted)

        async def upload_dir(self, source, target):
            calls.append(("upload", source, target))

        async def exec(self, command, **kwargs):
            calls.append(("exec", command, kwargs))
            running = "flashrsi.integrations._container" in command
            if mounted and running and has_output:
                (logs / "flashrsi.json").write_text('{"status":"error"}')
            return ExecResult(
                return_code=3 if running else 0, **{stream: "failed to start"}
            )

        async def is_file(self, path):
            calls.append(("is_file", path))
            return has_output

        async def download_file(self, source, target):
            assert has_output, "bootstrap failed before writing a trajectory"
            calls.append(("download", source, target))
            target.write_text('{"status":"error"}')

    bridge = harbor._SnapshotAgent(logs_dir=logs, payload_dir=str(payload))
    context = SimpleNamespace(metadata=None)

    async def run():
        await bridge.setup(Environment())
        with pytest.raises(
            NonZeroAgentExitCodeError, match="exited with 3: failed to start"
        ):
            await bridge.run(
                "a prompt with $(shell) and 'quotes'", Environment(), context
            )

    asyncio.run(run())
    assert calls[0] == ("upload", payload, harbor._ROOT)
    assert "uv venv --python 3.12" in calls[1][1]
    _, command, options = calls[2]
    arguments = shlex.split(command)
    assert arguments[:3] == [
        f"{harbor._ROOT}/venv/bin/python",
        "-I",
        "-c",
    ]
    assert arguments[-2:] == [
        f"{harbor._ROOT}/request.json",
        "/logs/agent/flashrsi.json",
    ]
    assert "cwd" not in options
    assert "env" not in options
    expected = ["upload", "exec", "exec"]
    if not mounted:
        expected.append("is_file")
        if has_output:
            expected.append("download")
    assert [call[0] for call in calls] == expected
    assert (logs / "flashrsi.json").exists() is has_output


def test_bridge_bootstrap_preserves_task_pythonpath_and_isolates_imports(
    tmp_path, monkeypatch
):
    runtime, task_dir, imports, logs = (
        tmp_path / name for name in ("runtime", "task", "imports", "logs")
    )
    for directory in (runtime, task_dir, imports, logs):
        directory.mkdir()
    (imports / "task_dependency.py").write_text('VALUE = "task import worked"\n')
    # Neither task cwd nor task PYTHONPATH may shadow the bridge's dependencies.
    for directory in (task_dir, imports):
        for name in ("yaml.py", "runpy.py", "flashrsi.py"):
            (directory / name).write_text(
                'raise RuntimeError("task shadow imported")\n'
            )

    agent = MiniAgent({"llm": {"model_name": "unused"}, "timeout": 10})
    with agent.snapshot.check_out() as directory:
        (directory / "runtime/agent.py").write_text(
            "import asyncio, sys\n"
            "async def run(**kwargs):\n"
            "    process = await asyncio.create_subprocess_exec(\n"
            "        sys.executable, '-c',\n"
            "        'import json, os, task_dependency; '\n"
            "        'print(json.dumps(dict(cwd=os.getcwd(), '\n"
            "        'pythonpath=os.environ.get(\"PYTHONPATH\"), '\n"
            "        'value=task_dependency.VALUE)))',\n"
            "        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)\n"
            "    stdout, stderr = await process.communicate()\n"
            "    assert process.returncode == 0, stderr.decode()\n"
            "    return dict(answer=stdout.decode(), stop_reason='completed', "
            "usage=[], turns=1)\n"
        )
        agent.update(agent.snapshot.commit(directory))
    monkeypatch.setattr(harbor, "_ROOT", str(runtime))
    harbor._stage(runtime, agent, agent.config, "Check task imports")
    bridge = harbor._SnapshotAgent(
        logs_dir=logs,
        payload_dir=str(runtime),
        environment_logs_dir=PurePosixPath(str(logs)),
    )

    class Environment:
        capabilities = SimpleNamespace(mounted=True)

        async def exec(self, command, **kwargs):
            arguments = shlex.split(command)
            # Use the test environment's installed dependencies in place of the
            # container venv; execute the actual isolated bootstrap and harness.
            arguments[0] = sys.executable
            process = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=task_dir,
                env={**os.environ, "PYTHONPATH": str(imports), **kwargs.get("env", {})},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await process.communicate()
            return ExecResult(return_code=process.returncode, stdout=stdout.decode())

    asyncio.run(bridge.run("Check task imports", Environment(), SimpleNamespace()))
    result = json.loads((logs / "flashrsi.json").read_text())
    assert result["status"] == "finished"
    assert json.loads(result["output"]) == {
        "cwd": str(task_dir),
        "pythonpath": str(imports),
        "value": "task import worked",
    }
    assert not (runtime / "request.json").exists()


class _LocalEnvironment(BaseEnvironment):
    """Filesystem simulation; actual Harbor Trial and Verifier remain in use."""

    def __init__(self, *, remote_root, **kwargs):
        self.remote_root = remote_root
        self.events = []
        super().__init__(**kwargs)

    @staticmethod
    def type():
        return "docker"

    def _validate_definition(self):
        pass

    def _path(self, value):
        return self.remote_root / str(value).lstrip("/")

    async def start(self, force_build):
        self.events.append("start")
        for directory in ("/logs/agent", "/logs/verifier", "/logs/artifacts"):
            self._path(directory).mkdir(parents=True)

    async def stop(self, delete):
        self.events.append("stop")
        assert delete

    async def upload_dir(self, source_dir, target_dir):
        self.events.append(("upload", str(target_dir)))
        shutil.copytree(source_dir, self._path(target_dir), dirs_exist_ok=True)

    async def upload_file(self, source_path, target_path):
        target = self._path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)

    async def download_file(self, source_path, target_path):
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(source_path), target_path)

    async def download_dir(self, source_dir, target_dir):
        shutil.copytree(self._path(source_dir), target_dir, dirs_exist_ok=True)

    async def is_dir(self, path, user=None):
        return self._path(path).is_dir()

    async def is_file(self, path, user=None):
        return self._path(path).is_file()

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        if "uv venv --python" in command:
            self.events.append("install")
            return ExecResult(return_code=0)
        if "flashrsi.integrations._container" in command:
            self.events.append("agent")
            assert cwd is None  # Preserve a task whose WORKDIR is the root directory.
            assert not self._path("/tests").exists()
            request_path, output_path = map(self._path, shlex.split(command)[-2:])
            request = json.loads(request_path.read_text())
            request["snapshot_path"] = str(self._path(request["snapshot_path"]))
            request_path.write_text(json.dumps(request))
            previous_cwd, previous_env = Path.cwd(), dict(os.environ)
            try:
                os.chdir(self.remote_root)
                return_code = await _container._run(request_path, output_path)
            finally:
                os.chdir(previous_cwd)
                os.environ.clear()
                os.environ.update(previous_env)
            return ExecResult(return_code=return_code)
        self.events.append("verifier")
        # Execute only this test's local verifier script, translating its paths.
        command = command.replace("/tests/", str(self._path("/tests")) + "/")
        command = command.replace("/logs/", str(self._path("/logs")) + "/")
        translated = {
            key: str(self._path(value)) if value.startswith("/logs/") else value
            for key, value in (env or {}).items()
        }
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            cwd=self._path(cwd or "/"),
            env={**os.environ, **translated},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return ExecResult(
            return_code=process.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )


@pytest.mark.parametrize("mode", ["success", "error", "cancel"])
def test_real_harbor_trial_verifier_and_container_boundary(
    agent, task, monkeypatch, tmp_path, mode
):
    environments = []

    def create_environment(config, **kwargs):
        assert config.type == "docker"
        environment = _LocalEnvironment(remote_root=tmp_path / "remote", **kwargs)
        environments.append(environment)
        return environment

    async def solve(self, prompt, working_dir=None):
        assert prompt == task.question
        assert working_dir == Path.cwd()
        assert self.snapshot.id == agent.snapshot.id
        assert not (working_dir / "opt/flashrsi-lite/request.json").exists()
        if mode == "cancel":
            raise asyncio.CancelledError()
        (working_dir / "answer.txt").write_text("SOLVED")
        if mode == "error":
            return Trajectory(
                status="error",
                error_message="provider failed target-private-key",
                usage={"input_tokens": 12},
            )
        return Trajectory(
            output="done",
            messages=({"type": "AssistantMessage", "text": "native-adapter-result"},),
            usage={"num_turns": 1, "input_tokens": 12},
        )

    monkeypatch.setattr(
        EnvironmentFactory, "create_environment_from_config", create_environment
    )
    monkeypatch.setattr(type(agent), "_run", solve)
    if mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(agent.rollout([task]))
        assert environments[0].events[-1] == "stop"
        assert not environments[0].trial_paths.trial_dir.exists()
        return
    (result,) = asyncio.run(agent.rollout([task]))
    assert result.usage["input_tokens"] == 12
    (environment,) = environments
    assert environment.events[0] == "start"
    assert environment.events[-1] == "stop"
    assert result.messages[-1]["rewards"] == {"reward": 1.0}
    assert "native verifier ran" in result.messages[-1]["stdout"]
    assert environment.events.index("agent") < environment.events.index(
        ("upload", "/tests")
    )
    if mode == "error":
        assert result.status == "error"
        assert result.error_message == "provider failed [REDACTED]"
        assert "Container agent exited with 1" in result.messages[-1]["error"]
        benchmark = TerminalBench(
            {"data_path": task.env, "split": {"train": 0, "dev": 0, "test": 1}}
        )
        benchmark.load()
        graded = benchmark.grade((replace(result, task=benchmark.test[0]),))[0]
        assert graded.metrics["reward"] == 0.0
    else:
        assert result.status == "finished", result.error_message
        assert result.output == "done"


def test_container_extra_uses_distribution_metadata_and_linux_markers(monkeypatch):
    original = harbor.requires("flashrsi-lite")
    monkeypatch.setattr(
        harbor,
        "requires",
        lambda name: [
            *original,
            'linux-tool>=1; extra == "miniagent" and sys_platform == "linux"',
            'windows-tool>=1; extra == "miniagent" and sys_platform == "win32"',
        ],
    )
    agent = SimpleNamespace(_container_extra="miniagent", _container_dependencies=None)
    packages = harbor._dependencies(agent)
    assert set(packages) == {"PyYAML", "openai", "requests", "linux-tool"}
    agent._container_extra = "claude-code"
    assert set(harbor._dependencies(agent)) == {"PyYAML", "claude-agent-sdk"}
    agent._container_extra = "unknown-extra"
    with pytest.raises(ValueError, match="Unknown.*container extra"):
        harbor._dependencies(agent)


def test_external_adapter_can_declare_distribution_dependencies():
    agent = SimpleNamespace(
        _container_extra=None, _container_dependencies=("external-adapter", "PyYAML")
    )
    assert list(harbor._dependencies(agent)) == ["PyYAML", "external-adapter"]
