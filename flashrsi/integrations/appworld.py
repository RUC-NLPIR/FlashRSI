"""Isolated AppWorld execution, native shell bridge and official evaluation."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import math
import os
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

from flashrsi._records import _config_record, _redact, _secrets
from flashrsi.benchmarks.appworld import _tree_checksum
from flashrsi.core import Trajectory
from flashrsi.integrations._container import _agent_class
from flashrsi.integrations._container_payload import _ROOT, _stage
from flashrsi.integrations._docker import _docker
from flashrsi.integrations._docker_harness import _cleanup, _run, _setup

_HERE = Path(__file__).parent
_IMAGE = "flashrsi-appworld:0.1.3.post1"
_CLIENT = f"{_ROOT}/venv/bin/python {_ROOT}/appworld_client.py"
_TOOLS = f"""AppWorld tools are available through your native shell tool:
- List apps: {_CLIENT} metadata
- Read API docs: {_CLIENT} docs [app_name] [api_name]
- Execute Python in the persistent AppWorld session:
  {_CLIENT} execute <<'PY'
  print(apis.api_docs.show_app_descriptions())
  PY
The session provides `apis`; API names and arguments are in the docs tool.
Use the supervisor completion API when the task is complete. Evaluation is performed
by the host after your session ends; no grading or environment reset tool is exposed.
"""


def bind(agent, config):
    """Connect container-capable harnesses without changing their native prompts."""
    agent._check_container()
    cls = type(agent)
    if _agent_class(f"{cls.__module__}:{cls.__qualname__}") is not cls:
        raise ValueError("AppWorld execution requires an importable Agent class")
    if shutil.which("docker") is None:
        raise ValueError("AppWorld execution requires Docker CLI and a Linux daemon")
    options = copy.deepcopy(dict(config))
    for name, default in (
        ("setup_timeout", 600),
        ("evaluation_timeout", 120),
        ("cleanup_grace", 30),
    ):
        value = options.setdefault(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"benchmark.{name} must be a positive finite number")
    execution_timeout = options.setdefault("execution_timeout", 100)
    if type(execution_timeout) is not int or execution_timeout < 1:
        raise ValueError("benchmark.execution_timeout must be a positive integer")
    count = options.setdefault("max_interactions", 1000)
    if type(count) is not int or count < 1:
        raise ValueError("benchmark.max_interactions must be a positive integer")
    seed = options.setdefault("world_seed", 100)
    if type(seed) is not int:
        raise ValueError("benchmark.world_seed must be an integer")

    async def run(target, task):
        return await _solve(target, task, options)

    agent._env_runner = run


def _data_payload(task, directory):
    source = Path(task.env).resolve()
    if source.name != task.task_id or source.parent.name != "tasks":
        raise ValueError("AppWorld Task.env must identify its native task directory")
    root = source.parent.parent
    base_checksum = _tree_checksum(root / "base_dbs")
    checksum = hashlib.sha256(
        f"{base_checksum}:{_tree_checksum(source)}".encode()
    ).hexdigest()
    if checksum != task.metadata["task_checksum"]:
        raise ValueError("AppWorld data changed after benchmark loading")
    # The execution container receives only initial state and public specs.
    # Hidden labels are copied separately, only into the fresh grading container.
    public = directory / "public"
    trusted = directory / "trusted"
    apps = {path.stem for path in (root / "base_dbs").glob("*.db")}
    # Task.load reads the standard API docs even with load_ground_truth=False.
    # These are public tool schemas, required by both execution and evaluation.
    for destination in (public, trusted):
        docs = destination / "data" / "api_docs" / "standard"
        docs.mkdir(parents=True)
        for path in (root / "api_docs" / "standard").glob("*.json"):
            if path.stem in apps:
                shutil.copyfile(path, docs / path.name)
    shutil.copytree(root / "base_dbs", public / "data" / "base_dbs")
    task_dir = public / "data" / "tasks" / task.task_id
    shutil.copytree(source / "dbs", task_dir / "dbs")
    specs = json.loads((source / "specs.json").read_text(encoding="utf-8"))
    public_specs = {
        key: specs[key] for key in ("instruction", "datetime", "db_version")
    }
    identity = specs.get("supervisor", specs.get("main_user"))
    public_specs["supervisor"] = {
        key: identity[key]
        for key in ("first_name", "last_name", "email", "phone_number")
    }
    (task_dir / "specs.json").write_text(json.dumps(public_specs), encoding="utf-8")
    shutil.copytree(root / "base_dbs", trusted / "data" / "base_dbs")
    shutil.copytree(source, trusted / "data" / "tasks" / task.task_id)
    shutil.copyfile(_HERE / "_appworld_server.py", public / "server.py")
    shutil.copyfile(_HERE / "_appworld_client.py", public / "client.py")
    shutil.copyfile(_HERE / "_appworld_grade.py", trusted / "grade.py")
    return public, trusted, apps


def _save_state(raw, destination, apps):
    """Read frozen state as data; never extract candidate-controlled tar paths."""
    destination.mkdir(parents=True)
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if parts and parts[0] == "dbs":
                parts = parts[1:]
            if member.isdir() and not parts:
                continue
            if len(parts) != 1 or not member.isfile():
                raise ValueError(
                    "AppWorld output contains an unsafe state archive entry"
                )
            name = parts[0]
            if name != "model_hashes.json" and name not in {
                f"{app}.jsonl" for app in apps
            }:
                raise ValueError(f"Unexpected AppWorld state file: {name}")
            if name in seen:
                raise ValueError("Duplicate AppWorld state file")
            seen.add(name)
            total += member.size
            if total > 128 * 1024 * 1024:
                raise ValueError("AppWorld state exceeds 128 MiB")
            (destination / name).write_bytes(archive.extractfile(member).read())
    if not seen or not any(name.endswith(".jsonl") for name in seen):
        raise ValueError("AppWorld output has no database state")


async def _solve(agent, task, options):
    config = copy.deepcopy(agent.config)
    snapshot = agent.snapshot
    timeout = config.get("timeout", 300)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("agent.timeout must be a positive finite number")
    setup_timeout = options["setup_timeout"]
    evaluation_timeout = options["evaluation_timeout"]
    grace = options["cleanup_grace"]
    secrets = sorted(
        set(_secrets(config) + _secrets(os.environ)), key=len, reverse=True
    )
    record = {
        "type": "RunConfig",
        "config": _config_record(config),
        "snapshot_id": snapshot.id,
    }
    trajectory = Trajectory(messages=(record,))
    run_id = f"flashrsi-appworld-{uuid4().hex}"
    world, harness, grader = (
        f"{run_id}-{role}" for role in ("world", "agent", "grader")
    )
    network = run_id
    containers = (world, harness, grader)
    phase = "setup"
    with TemporaryDirectory(prefix="flashrsi-appworld-") as temporary:
        root = Path(temporary)
        try:
            async with asyncio.timeout(setup_timeout):
                public, trusted, apps = _data_payload(task, root)
                payload = root / "agent"
                payload.mkdir(mode=0o700)
                _stage(payload, agent, config, task.question + "\n\n" + _TOOLS)
                shutil.copyfile(
                    _HERE / "_appworld_client.py", payload / "appworld_client.py"
                )
                await _docker(
                    "network", "create", "--internal", network, timeout=setup_timeout
                )
                image = options.get("image", _IMAGE)
                hardening = (
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=512",
                )
                await _docker(
                    "create",
                    "--name",
                    world,
                    "--init",
                    *hardening,
                    "--memory=1g",
                    "--network",
                    network,
                    "--network-alias",
                    "appworld",
                    "--workdir",
                    "/world",
                    "--entrypoint",
                    "python",
                    "--",
                    image,
                    "/world/server.py",
                    task.task_id,
                    "--max-interactions",
                    str(options["max_interactions"]),
                    "--seed",
                    str(options["world_seed"]),
                    "--timeout",
                    str(options["execution_timeout"]),
                    timeout=setup_timeout,
                )
                await _docker(
                    "cp",
                    str(public) + os.sep + ".",
                    f"{world}:/world",
                    timeout=setup_timeout,
                )
                await _docker("start", world, timeout=setup_timeout)
                image_id = (
                    await _docker(
                        "inspect",
                        "--format",
                        "{{.Image}}",
                        world,
                        timeout=setup_timeout,
                    )
                ).stdout.strip()
                await _docker(
                    "exec",
                    world,
                    "python",
                    "/world/client.py",
                    "wait",
                    "--url",
                    "http://127.0.0.1:8000",
                    "--timeout",
                    str(setup_timeout),
                    timeout=setup_timeout,
                )
                await _setup(_docker, harness, network, payload, config, setup_timeout)
            phase = "execution"
            async with asyncio.timeout(timeout + grace):
                trajectory = await _run(_docker, harness, timeout, grace)
                # Only the host may supply this event, regardless of what a
                # native harness chose to serialize in its own messages.
                trajectory = replace(
                    trajectory,
                    messages=(
                        record,
                        *(
                            event
                            for event in trajectory.messages
                            if event.get("type")
                            not in ("RunConfig", "AppWorldVerifier")
                        ),
                    ),
                )
            if trajectory.status == "finished":
                phase = "evaluation"
                async with asyncio.timeout(evaluation_timeout):
                    # Stop all candidate descendants, then freeze the world.
                    # docker cp reads a consistent, immutable filesystem view.
                    await _docker("stop", "--time", "1", harness, timeout=grace)
                    await _docker(
                        "exec",
                        world,
                        "python",
                        "/world/client.py",
                        "metadata",
                        "--url",
                        "http://127.0.0.1:8000",
                        timeout=evaluation_timeout,
                    )
                    await _docker("pause", world, timeout=grace)
                    state = (
                        await _docker(
                            "cp",
                            f"{world}:/world/experiments/outputs/current/tasks/{task.task_id}/dbs/.",
                            "-",
                            timeout=evaluation_timeout,
                            binary=True,
                        )
                    ).stdout
                    destination = (
                        trusted
                        / "experiments"
                        / "outputs"
                        / "current"
                        / "tasks"
                        / task.task_id
                        / "dbs"
                    )
                    _save_state(state, destination, apps)
                    await _docker(
                        "create",
                        "--name",
                        grader,
                        "--init",
                        *hardening,
                        "--memory=1g",
                        "--network=none",
                        "--workdir",
                        "/world",
                        "--entrypoint",
                        "/bin/sh",
                        "--",
                        image_id,
                        "-c",
                        "while :; do sleep 3600; done",
                        timeout=evaluation_timeout,
                    )
                    await _docker(
                        "cp",
                        str(trusted) + os.sep + ".",
                        f"{grader}:/world",
                        timeout=evaluation_timeout,
                    )
                    await _docker("start", grader, timeout=evaluation_timeout)
                    verdict = json.loads(
                        (
                            await _docker(
                                "exec",
                                grader,
                                "python",
                                "/world/grade.py",
                                task.task_id,
                                timeout=evaluation_timeout,
                            )
                        ).stdout
                    )
                    if (
                        type(verdict.get("success")) is not bool
                        or verdict.get("appworld_version") != "0.1.3.post1"
                    ):
                        raise ValueError("Invalid official AppWorld evaluator result")
                    event = {
                        "type": "AppWorldVerifier",
                        "task_id": task.task_id,
                        "task_checksum": task.metadata["task_checksum"],
                        "snapshot_id": snapshot.id,
                        "image_id": image_id,
                        "success": verdict["success"],
                        "appworld_version": verdict["appworld_version"],
                        "official_evaluation_performed": True,
                    }
                    trajectory = replace(
                        trajectory, messages=(*trajectory.messages, event)
                    )
        except TimeoutError:
            trajectory = replace(
                trajectory, status="error", error_message=f"AppWorld {phase} timed out"
            )
        except Exception as exc:
            trajectory = replace(
                trajectory, status="error", error_message=str(exc) or type(exc).__name__
            )
        finally:
            cleanup = asyncio.create_task(_cleanup(_docker, containers, network, grace))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await asyncio.gather(cleanup, return_exceptions=True)
                raise
            except Exception as exc:
                prior = (
                    f"{trajectory.error_message}; " if trajectory.error_message else ""
                )
                trajectory = replace(
                    trajectory,
                    status="error",
                    error_message=prior + (str(exc) or type(exc).__name__),
                )
    return replace(
        trajectory,
        output=_redact(trajectory.output, secrets),
        messages=_redact(trajectory.messages, secrets),
        usage=_redact(trajectory.usage, secrets),
        error_message=_redact(trajectory.error_message, secrets),
    )
