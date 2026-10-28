"""Run BFCL Base with native harness tools and isolated official replay scoring."""

import asyncio
import copy
import io
import json
import math
import os
import shutil
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

from flashrsi._records import _config_record, _redact, _secrets
from flashrsi.benchmarks import bfcl as _data
from flashrsi.benchmarks.bfcl import _checksum, _records, _source
from flashrsi.core import Trajectory
from flashrsi.integrations._container import _agent_class
from flashrsi.integrations._container_payload import _ROOT, _stage
from flashrsi.integrations._docker import _docker
from flashrsi.integrations._docker_harness import _cleanup, _run, _setup

_HERE = Path(__file__).parent
_IMAGE = "flashrsi-bfcl:6ea57973"
_CLIENT = f"{_ROOT}/venv/bin/python {_ROOT}/bfcl_client.py"
_TOOLS = f"""You are in one BFCL multi-turn conversation. Use your native shell tool:
- Current user turn and available tools: {_CLIENT} current
- Function docs: {_CLIENT} tools [function_name]
- Execute a JSON list of calls, in order:
  {_CLIENT} call <<'JSON'
  [{{"name":"function_name","arguments":{{"parameter":"value"}}}}]
  JSON
- When the current user turn is done: {_CLIENT} finish_turn
finish_turn returns the next user turn or conversation_complete. Continue within
this session until conversation_complete, then give your final response.
Tool responses can contain errors; preserve them as observations. The host grades
the complete conversation. No grading or environment-reset tool is available.
"""


def bind(agent, config):
    agent._check_container()
    cls = type(agent)
    if _agent_class(f"{cls.__module__}:{cls.__qualname__}") is not cls:
        raise ValueError("BFCL execution requires an importable Agent class")
    if shutil.which("docker") is None:
        raise ValueError("BFCL execution requires Docker CLI and a Linux daemon")
    options = copy.deepcopy(dict(config))
    for field, default in (
        ("setup_timeout", 600),
        ("evaluation_timeout", 120),
        ("cleanup_grace", 30),
    ):
        value = options.setdefault(field, default)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"benchmark.{field} must be a positive finite number")
    limit = options.setdefault("max_calls_per_turn", 256)
    if type(limit) is not int or limit < 1:
        raise ValueError("benchmark.max_calls_per_turn must be a positive integer")

    async def run(target, task):
        return await _solve(target, task, options)

    agent._env_runner = run


def _prepare(task, directory, max_calls_per_turn):
    package = Path(task.env).resolve()
    actual, digest = _source(package.parent)
    if package != actual:
        raise ValueError("BFCL Task.env must identify the pinned native package")
    data = package / "bfcl_eval" / "data"
    filename = "BFCL_v4_multi_turn_base.json"
    row = _records(data / filename)[task.task_id]
    answer = _records(data / "possible_answer" / filename)[task.task_id]
    if _checksum(digest, row, answer) != task.metadata["task_checksum"]:
        raise ValueError("BFCL data changed after loading")
    public = directory / "public"
    trusted = directory / "trusted"
    runtime = public / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "__init__.py").write_text("")
    for name in ("_bfcl_native.py", "_bfcl_session.py", "_bfcl_server.py"):
        shutil.copyfile(_HERE / name, runtime / name)
    shutil.copyfile(_HERE / "_bfcl_client.py", public / "client.py")
    native = public / "native" / "bfcl_eval"
    native.mkdir(parents=True)
    # Upstream initializers are empty. Create minimal package boundaries rather
    # than copying any unverified top-level code or model inference handlers.
    (native / "__init__.py").write_text("")
    (native / "eval_checker").mkdir()
    (native / "eval_checker" / "__init__.py").write_text("")
    # Stage immutable Git objects, not whole working directories. Untracked
    # credentials, bytecode and unrelated local files cannot enter containers.
    paths = (
        "constants",
        "eval_checker/multi_turn_eval",
        "data/multi_turn_func_doc",
        "utils.py",
    )
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(package.parent),
            "archive",
            _data._REVISION,
            "--",
            *(f"{package.name}/bfcl_eval/{path}" for path in paths),
        ],
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as files:
        for member in files:
            if member.isdir():
                continue
            relative = PurePosixPath(member.name).relative_to(
                f"{package.name}/bfcl_eval"
            )
            if not member.isfile() or ".." in relative.parts:
                raise ValueError("Unsafe BFCL runtime source")
            if relative.suffix in (".py", ".json"):
                target = native.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(files.extractfile(member).read())
    shutil.copytree(public, trusted)
    shutil.copyfile(_HERE / "_bfcl_grade.py", trusted / "runtime" / "_bfcl_grade.py")
    (public / "request.json").write_text(
        json.dumps(
            {
                "row": {
                    field: row[field]
                    for field in (
                        "id",
                        "question",
                        "initial_config",
                        "involved_classes",
                    )
                },
                "max_calls_per_turn": max_calls_per_turn,
            }
        ),
        encoding="utf-8",
    )
    (trusted / "request.json").write_text(
        json.dumps({"row": row, "reference": answer["ground_truth"]}), encoding="utf-8"
    )
    return public, trusted


def _trace(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        members = archive.getmembers()
        if (
            len(members) != 1
            or not members[0].isfile()
            or PurePosixPath(members[0].name).parts != ("trace.json",)
            or members[0].size > 8 * 1024 * 1024
        ):
            raise ValueError("Unsafe BFCL trace archive")
        value = json.loads(archive.extractfile(members[0]).read())
    if (
        not isinstance(value, dict)
        or value.get("complete") is not True
        or value.get("interrupted") is not None
    ):
        reason = value.get("interrupted") if isinstance(value, dict) else None
        raise ValueError(
            f"BFCL conversation incomplete or interrupted: {reason or 'incomplete'}"
        )
    if type(value.get("protocol_valid")) is not bool or not isinstance(
        value.get("trace"), list
    ):
        raise ValueError("Invalid BFCL conversation evidence")
    return value


async def _solve(agent, task, options):
    config = copy.deepcopy(agent.config)
    snapshot = agent.snapshot
    timeout = config.get("timeout", 300)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("agent.timeout must be a positive finite number")
    setup_timeout, evaluation_timeout, grace = (
        options[field]
        for field in ("setup_timeout", "evaluation_timeout", "cleanup_grace")
    )
    secrets = sorted(
        set(_secrets(config) + _secrets(os.environ)), key=len, reverse=True
    )
    record = {
        "type": "RunConfig",
        "config": _config_record(config),
        "snapshot_id": snapshot.id,
    }
    trajectory = Trajectory(messages=(record,))
    network = f"flashrsi-bfcl-{uuid4().hex}"
    world, harness, grader = (
        f"{network}-{role}" for role in ("world", "agent", "grader")
    )
    phase = "setup"
    with TemporaryDirectory(prefix="flashrsi-bfcl-") as temporary:
        root = Path(temporary)
        try:
            async with asyncio.timeout(setup_timeout):
                public, trusted = _prepare(task, root, options["max_calls_per_turn"])
                payload = root / "agent"
                payload.mkdir(mode=0o700)
                _stage(payload, agent, config, task.question + "\n\n" + _TOOLS)
                shutil.copyfile(_HERE / "_bfcl_client.py", payload / "bfcl_client.py")
                await _docker(
                    "network", "create", "--internal", network, timeout=setup_timeout
                )
                hardening = (
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=512",
                    "--memory=1g",
                )
                await _docker(
                    "create",
                    "--name",
                    world,
                    "--init",
                    *hardening,
                    "--network",
                    network,
                    "--network-alias",
                    "bfcl",
                    "--workdir",
                    "/world",
                    "--entrypoint",
                    "python",
                    "--",
                    options.get("image", _IMAGE),
                    "-m",
                    "runtime._bfcl_server",
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
                trajectory = replace(
                    trajectory,
                    messages=(
                        record,
                        *(
                            event
                            for event in trajectory.messages
                            if event.get("type") not in ("RunConfig", "BFCLVerifier")
                        ),
                    ),
                )
            if trajectory.status == "finished":
                phase = "evaluation"
                async with asyncio.timeout(evaluation_timeout):
                    await _docker("stop", "--time", "1", harness, timeout=grace)
                    await _docker(
                        "exec",
                        world,
                        "python",
                        "/world/client.py",
                        "current",
                        "--url",
                        "http://127.0.0.1:8000",
                        timeout=evaluation_timeout,
                        check=False,
                    )
                    await _docker("pause", world, timeout=grace)
                    raw = (
                        await _docker(
                            "cp",
                            f"{world}:/world/trace.json",
                            "-",
                            timeout=evaluation_timeout,
                            binary=True,
                        )
                    ).stdout
                    evidence = _trace(raw)
                    (trusted / "trace.json").write_text(
                        json.dumps(evidence), encoding="utf-8"
                    )
                    await _docker(
                        "create",
                        "--name",
                        grader,
                        "--init",
                        *hardening,
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
                                "-m",
                                "runtime._bfcl_grade",
                                timeout=evaluation_timeout,
                            )
                        ).stdout
                    )
                    fields = (
                        "state_and_response_valid",
                        "irrelevance_valid",
                        "protocol_valid",
                    )
                    if (
                        any(type(verdict.get(field)) is not bool for field in fields)
                        or verdict["protocol_valid"] != evidence["protocol_valid"]
                    ):
                        raise ValueError("Invalid official BFCL evaluator result")
                    event = {
                        "type": "BFCLVerifier",
                        "task_id": task.task_id,
                        "task_checksum": task.metadata["task_checksum"],
                        "snapshot_id": snapshot.id,
                        "image_id": image_id,
                        "official_evaluation_performed": True,
                        **{field: verdict[field] for field in fields},
                    }
                    trajectory = replace(
                        trajectory, messages=(*trajectory.messages, event)
                    )
        except TimeoutError:
            trajectory = replace(
                trajectory, status="error", error_message=f"BFCL {phase} timed out"
            )
        except Exception as exc:
            trajectory = replace(
                trajectory, status="error", error_message=str(exc) or type(exc).__name__
            )
        finally:
            cleanup = asyncio.create_task(
                _cleanup(_docker, (world, harness, grader), network, grace)
            )
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
