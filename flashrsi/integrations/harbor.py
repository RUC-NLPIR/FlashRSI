"""Run an existing FlashRSI adapter inside one native Harbor trial."""

from __future__ import annotations

import copy
import json
import math
import os
import shlex
import shutil
import sys
from collections.abc import Mapping
from dataclasses import replace
from importlib.metadata import metadata, requires, version
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from packaging.markers import default_environment
from packaging.requirements import Requirement

if sys.version_info < (3, 12):
    raise ImportError("Harbor execution requires Python 3.12 or newer")

try:
    from harbor.agents.base import BaseAgent
    from harbor.agents.installed.base import NonZeroAgentExitCodeError
    from harbor.models.task.task import Task as HarborTask
    from harbor.models.trial.config import (
        AgentConfig,
        EnvironmentConfig,
        TaskConfig,
        TrialConfig,
    )
    from harbor.trial.trial import Trial
except ImportError as exc:
    raise ImportError("Install flashrsi-lite[harbor] for environment tasks") from exc

from flashrsi._records import _config_record, _redact, _secrets
from flashrsi.core import Trajectory
from flashrsi.integrations._container import _agent_class

_ROOT = "/opt/flashrsi-lite"


def bind(agent):
    """Connect an Agent to Harbor; CLI runs do this in the runner.

    The adapter must be importable in the container. Built-ins travel with the
    current FlashRSI source; external adapters must include their distribution
    in _container_dependencies. No task or model is executed here.
    """
    agent._check_container()
    agent.snapshot  # Container execution requires a versioned harness.
    cls = type(agent)
    if _agent_class(f"{cls.__module__}:{cls.__qualname__}") is not cls:
        raise ValueError("Container execution requires an importable Agent class")
    agent._env_runner = _run


async def _run(agent, task):
    """The caller's rollout has already pinned its Snapshot and configuration."""
    if shutil.which("docker") is None:
        raise ValueError("Harbor execution requires Docker with the Compose plugin")
    agent._check_container()
    native = HarborTask(Path(task.env))
    if native.config.steps or native.config.environment.os.value != "linux":
        raise ValueError("This integration supports single-step Linux Harbor tasks")
    if native.instruction != task.question:
        raise ValueError("Harbor task instruction changed after benchmark.load()")
    checksum = native.checksum
    if task.metadata.get("task_checksum", checksum) != checksum:
        raise ValueError("Harbor task files changed after benchmark.load()")

    snapshot = agent.snapshot
    config = copy.deepcopy(agent.config)
    options = config.get("harbor", {})
    timeout = _positive(
        config.get("timeout", native.config.agent.timeout_sec or 300), "timeout"
    )
    setup_timeout = _positive(options.get("setup_timeout", 600), "harbor.setup_timeout")
    grace = _positive(options.get("cleanup_grace", 30), "harbor.cleanup_grace")
    config["timeout"] = timeout
    secrets = sorted(
        set(_secrets(config) + _secrets(os.environ)), key=len, reverse=True
    )
    record = {
        "type": "RunConfig",
        "config": _config_record(config),
        "snapshot_id": snapshot.id,
    }
    trajectory = Trajectory(messages=(record,))
    event = {
        "type": "HarborVerifier",
        "task_id": task.task_id,
        "task_checksum": checksum,
    }

    with TemporaryDirectory(prefix="flashrsi-harbor-") as temporary:
        root = Path(temporary)
        payload = root / "payload"
        payload.mkdir(mode=0o700)
        _stage(payload, agent, config, task.question)
        trial = None
        try:
            trial = await Trial.create(
                TrialConfig(
                    task=TaskConfig(path=Path(task.env)),
                    trials_dir=root / "trials",
                    agent=AgentConfig(
                        import_path="flashrsi.integrations.harbor:_SnapshotAgent",
                        model_name=config["llm"]["model_name"],
                        override_timeout_sec=timeout + grace,
                        override_setup_timeout_sec=setup_timeout,
                        kwargs={"payload_dir": str(payload)},
                    ),
                    environment=EnvironmentConfig(type="docker", delete=True),
                )
            )
            # Harbor owns environment setup, phase deadlines, verifier and cleanup.
            result = await trial.run()
            output = trial.paths.agent_dir / "flashrsi.json"
            if output.is_file():
                values = json.loads(output.read_text())
                values.pop("task", None)
                trajectory = Trajectory(**values)
                if not any(
                    message.get("type") == "RunConfig"
                    and message.get("snapshot_id") == snapshot.id
                    for message in trajectory.messages
                ):
                    raise ValueError(
                        "Container result does not identify the requested Snapshot"
                    )
            elif result.exception_info is None:
                raise ValueError("Harbor agent ended without a FlashRSI trajectory")
            event["trial_id"] = str(result.id)
            event["rewards"] = (
                result.verifier_result.rewards
                if result.verifier_result is not None
                else None
            )
            event["stdout"] = _read_log(trial.paths.test_stdout_path)
            event["stderr"] = _read_log(trial.paths.test_stderr_path)
            if result.exception_info is not None:
                error = (
                    result.exception_info.exception_message
                    or result.exception_info.exception_type
                )
                event["error"] = error
                trajectory = replace(
                    trajectory,
                    status="error",
                    error_message=trajectory.error_message or error,
                )
            elif trajectory.status == "finished" and event["rewards"] is None:
                raise ValueError("Harbor verifier ended without rewards")
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            event["error"] = error
            trajectory = replace(trajectory, status="error", error_message=error)
        return replace(
            trajectory,
            output=_redact(trajectory.output, secrets),
            messages=_redact((*trajectory.messages, event), secrets),
            usage=_redact(trajectory.usage, secrets),
            error_message=_redact(trajectory.error_message, secrets),
        )


def _positive(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"agent.{field} must be a positive finite number")
    return value


def _read_log(path):
    return path.read_text(errors="replace") if path.is_file() else ""


def _stage(directory, agent, config, prompt):
    # Copy the adapter code separately from evolvable files. Linux dependencies
    # are installed in the container; never copy a host virtual environment.
    shutil.copytree(
        Path(__file__).parents[1],
        directory / "package" / "flashrsi",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env"),
    )
    agent.snapshot.save(directory / "snapshot.json")
    cls = type(agent)
    runtime_config = _plain(config)
    source = runtime_config.get("source_dir")
    if source is None:
        module_file = getattr(sys.modules[cls.__module__], "__file__", None)
        if module_file is not None:
            source = Path(module_file).resolve().parent
    if source is not None:
        # The container keeps this host path only as private provenance for
        # relocating native resource references, never as a file source to load.
        runtime_config["source_dir"] = str(Path(source).expanduser().resolve())
    request = directory / "request.json"
    request.write_text(
        json.dumps(
            {
                "agent_class": f"{cls.__module__}:{cls.__qualname__}",
                "config_yaml": yaml.safe_dump(runtime_config),
                "snapshot_path": f"{_ROOT}/snapshot.json",
                "prompt": prompt,
            },
        )
    )
    request.chmod(0o600)
    (directory / "requirements.txt").write_text(
        "".join(f"{package}=={version(package)}\n" for package in _dependencies(agent))
    )


def _dependencies(agent):
    """Read built-in dependency names from installed wheel metadata."""
    packages = ["PyYAML", *(agent._container_dependencies or ())]
    extra = agent._container_extra
    if extra is not None:
        if extra not in metadata("flashrsi-lite").get_all("Provides-Extra", []):
            raise ValueError(f"Unknown flashrsi-lite container extra: {extra}")
        environment = {
            **default_environment(),
            "sys_platform": "linux",
            "platform_system": "Linux",
            "os_name": "posix",
            "python_version": "3.12",
            "python_full_version": "3.12.0",
        }
        for value in requires("flashrsi-lite") or ():
            requirement = Requirement(value)
            marker = requirement.marker
            if (
                marker is not None
                and marker.evaluate({**environment, "extra": extra})
                and not marker.evaluate({**environment, "extra": ""})
            ):
                packages.append(requirement.name)
    return dict.fromkeys(packages)


def _plain(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class _SnapshotAgent(BaseAgent):
    """Harbor adapter for our existing, independently versioned harness adapter."""

    def __init__(self, *args, payload_dir, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload_dir = Path(payload_dir)

    @staticmethod
    def name():
        return "flashrsi-lite"

    def version(self):
        return version("flashrsi-lite")

    async def setup(self, environment):
        await environment.upload_dir(self.payload_dir, _ROOT)
        # uv installs the requested Python independently of a task's Python.
        # Minimal Debian/Ubuntu task images may not include a downloader yet.
        command = f"""set -eu
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl
fi
if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/0.11.4/install.sh -o {_ROOT}/install-uv.sh
else
    wget -q https://astral.sh/uv/0.11.4/install.sh -O {_ROOT}/install-uv.sh
fi
UV_INSTALL_DIR={_ROOT}/bin UV_NO_MODIFY_PATH=1 sh {_ROOT}/install-uv.sh
{_ROOT}/bin/uv venv --python 3.12 --managed-python {_ROOT}/venv
{_ROOT}/bin/uv pip install --python {_ROOT}/venv/bin/python -r {_ROOT}/requirements.txt
"""
        result = await environment.exec(command)
        if result.return_code:
            raise RuntimeError(
                f"Container dependency setup failed: {result.stderr or result.stdout}"
            )

    async def run(self, instruction, environment, context):
        command = shlex.join(
            [
                f"{_ROOT}/venv/bin/python",
                "-I",
                "-c",
                f"import sys; sys.path.insert(0, {_ROOT + '/package'!r}); "
                "import runpy; runpy.run_module('flashrsi.integrations._container', "
                "run_name='__main__', alter_sys=True)",
                f"{_ROOT}/request.json",
                str(self.environment_logs_dir / "flashrsi.json"),
            ]
        )
        # Isolate bridge imports without changing the task's cwd or PYTHONPATH;
        # native tools inherit the image's environment. The entry point removes
        # request.json before starting the harness.
        result = await environment.exec(command)
        if not environment.capabilities.mounted and await environment.is_file(
            str(self.environment_logs_dir / "flashrsi.json")
        ):
            await environment.download_file(
                str(self.environment_logs_dir / "flashrsi.json"),
                self.logs_dir / "flashrsi.json",
            )
        context.metadata = {"flashrsi_trajectory": "flashrsi.json"}
        if result.return_code:
            # Harbor continues the verifier for this exception, preserving task
            # feedback even when the harness has failed or reached its timeout.
            raise NonZeroAgentExitCodeError(
                f"Container agent exited with {result.return_code}: "
                f"{result.stderr or result.stdout or ''}"
            )
