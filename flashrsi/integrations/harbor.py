"""Run an existing FlashRSI adapter inside one native Harbor trial."""

from __future__ import annotations

import copy
import json
import math
import os
import shlex
import shutil
import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

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
        VerifierConfig,
    )
    from harbor.trial.trial import Trial
except ImportError as exc:
    raise ImportError("Install flashrsi-lite[harbor] for environment tasks") from exc

from flashrsi._records import _config_record, _redact, _secrets
from flashrsi.core import Trajectory
from flashrsi.integrations._container import _agent_class
from flashrsi.integrations._container_payload import _plain, _setup_script
from flashrsi.integrations._container_payload import _stage as _stage_payload

_ROOT = "/opt/flashrsi-lite"


def bind(agent):
    """Connect an Agent to Harbor; CLI runs do this in the runner.

    The adapter must be importable in the container. Built-ins travel with the
    current FlashRSI source; external adapters must include their distribution
    in _container_dependencies. No task or model is executed here.
    """
    agent._check_container()
    from flashrsi.integrations._terminal_integrity import validate

    validate(agent.config.get("harbor", {}).get("integrity_review"))
    agent.snapshot  # Container execution requires a versioned harness.
    cls = type(agent)
    if _agent_class(f"{cls.__module__}:{cls.__qualname__}") is not cls:
        raise ValueError("Container execution requires an importable Agent class")
    agent._env_runner = _run


async def _run(agent, task, *, verifier_env=None, agent_allowed_hosts=None):
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
    from flashrsi.integrations._terminal_integrity import validate

    validate(options.get("integrity_review"))
    remote_docker = options.get("remote_docker", False)
    if not isinstance(remote_docker, bool):
        raise ValueError("harbor.remote_docker must be a boolean")
    install_source = options.get("uv_install_source", "astral")
    installers = {
        "astral": "https://astral.sh/uv/0.11.4/install.sh",
        "github": "https://github.com/astral-sh/uv/releases/download/0.11.4/uv-installer.sh",
    }
    if not isinstance(install_source, str) or install_source not in installers:
        raise ValueError("harbor.uv_install_source must be astral or github")
    timeout = _positive(
        config.get("timeout", native.config.agent.timeout_sec or 300), "timeout"
    )
    setup_timeout = _positive(options.get("setup_timeout", 600), "harbor.setup_timeout")
    grace = _positive(options.get("cleanup_grace", 30), "harbor.cleanup_grace")
    config["timeout"] = timeout
    secrets = sorted(
        set(_secrets(config) + _secrets(os.environ) + _secrets(verifier_env)),
        key=len,
        reverse=True,
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
                        extra_allowed_hosts=agent_allowed_hosts or [],
                        kwargs={
                            "payload_dir": str(payload),
                            "uv_installer_url": installers[install_source],
                        },
                    ),
                    environment=EnvironmentConfig(
                        type="docker",
                        delete=True,
                        env=_plain(options.get("environment_env", {})),
                        import_path=(
                            "flashrsi.integrations._harbor_remote:_RemoteDockerEnvironment"
                            if remote_docker
                            else None
                        ),
                    ),
                    verifier=VerifierConfig(env=verifier_env or {}),
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
                event["exception_type"] = result.exception_info.exception_type
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
        review_options = options.get("integrity_review")
        if review_options is not None:
            from flashrsi.integrations._terminal_integrity import review

            # Outside the solver exception path: retry the judge, not the task.
            event = _redact(event, secrets)
            await review(
                task,
                replace(
                    trajectory,
                    output=_redact(trajectory.output, secrets),
                    messages=_redact(trajectory.messages, secrets),
                    usage=_redact(trajectory.usage, secrets),
                    error_message=_redact(trajectory.error_message, secrets),
                ),
                event,
                review_options,
            )
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
    config = copy.deepcopy(config)
    config.get("harbor", {}).pop("integrity_review", None)
    # Keep evaluation rules outside the candidate's mutable snapshot. Public
    # benchmark repositories expose hidden tests and oracle answers online.
    prompt += (
        "\n\nEvaluation integrity rules: Solve the task independently. Do not "
        "search for, download, read, or use benchmark-specific reference solutions, "
        "hidden verifier tests, expected answers, or other agents' task solutions "
        "from benchmark repositories, mirrors, datasets, or discussion threads. "
        "Do not modify the verifier or forge reward files. Internet access for "
        "ordinary documentation, dependencies, and resources requested by the task "
        "is permitted. Tests and source files explicitly supplied as task inputs "
        "may be inspected; this does not permit fetching hidden benchmark files."
    )
    _stage_payload(directory, agent, config, prompt)


class _SnapshotAgent(BaseAgent):
    """Harbor adapter for our existing, independently versioned harness adapter."""

    def __init__(
        self,
        *args,
        payload_dir,
        uv_installer_url="https://astral.sh/uv/0.11.4/install.sh",
        working_dir=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.payload_dir = Path(payload_dir)
        self.uv_installer_url = uv_installer_url
        self.working_dir = working_dir

    @staticmethod
    def name():
        return "flashrsi-lite"

    def version(self):
        return version("flashrsi-lite")

    async def setup(self, environment):
        await environment.upload_dir(self.payload_dir, _ROOT)
        # uv installs the requested Python independently of a task's Python.
        # Minimal Debian/Ubuntu task images may not include a downloader yet.
        command = _setup_script(self.uv_installer_url)
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
        command = getattr(self, "_command_prefix", "") + command
        # Isolate bridge imports without changing the task's cwd or PYTHONPATH;
        # native tools inherit the image's environment. The entry point removes
        # request.json before starting the harness.
        result = await environment.exec(
            command, **({"cwd": self.working_dir} if self.working_dir else {})
        )
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
