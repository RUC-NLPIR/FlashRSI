"""Prepare selected dependencies and data, then run a configured FlashRSI experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "examples" / "searchqa_skillopt.yaml"


def _cache_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "FlashRSI"


def _environment(cache):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    # Explicit user cache locations take precedence; defaults stay outside the repo.
    env.setdefault("HF_HOME", str(cache / "huggingface"))
    env.setdefault("PIP_CACHE_DIR", str(cache / "pip"))
    return env


def _bootstrap(cache, env):
    directory = (
        cache / "envs" / f"bootstrap-py{sys.version_info.major}{sys.version_info.minor}"
    )
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = directory / "yaml-ready"
    if not python.is_file():
        print("Preparing configuration reader...", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    if not marker.is_file():
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "PyYAML>=6,<7",
            ],
            env=env,
            check=True,
        )
        marker.touch()
    return python


def _runtime(cache, env, extras=("llm", "miniagent"), requirements=()):
    project_id = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    profile = json.dumps([sorted(extras), sorted(requirements)])
    # Keep using the existing quick-start environment for the same dependency set.
    name = (
        "searchqa"
        if set(extras) == {"llm", "miniagent"} and not requirements
        else hashlib.sha256(profile.encode()).hexdigest()[:12]
    )
    directory = (
        cache
        / "envs"
        / f"{name}-{project_id}-py{sys.version_info.major}{sys.version_info.minor}"
    )
    python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = directory / "flashrsi-source.sha256"
    digest = hashlib.sha256()
    digest.update(profile.encode())
    sources = [ROOT / "pyproject.toml"] + sorted(
        p
        for p in (ROOT / "flashrsi").rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix not in {".pyc", ".pyo"}
    )
    for path in sources:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    fingerprint = digest.hexdigest()
    if not python.is_file():
        print(f"[1/3] Creating Python environment: {directory}", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    if not marker.is_file() or marker.read_text() != fingerprint:
        print(
            "[1/3] Installing selected dependencies: " + ", ".join(extras), flush=True
        )
        # Build from a temporary copy so setuptools leaves no build/egg-info in ROOT.
        staging_root = tempfile.gettempdir()
        if os.name == "nt":
            # Keep the extended path for both copying and TemporaryDirectory cleanup.
            staging_root = "\\\\?\\" + str(Path(staging_root).resolve())
        with tempfile.TemporaryDirectory(
            prefix="flashrsi-install-", dir=staging_root
        ) as temporary:
            package = Path(temporary)
            shutil.copy2(ROOT / "pyproject.toml", package / "pyproject.toml")
            shutil.copytree(
                ROOT / "flashrsi",
                package / "flashrsi",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    str(package) + "[" + ",".join(extras) + "]",
                    *requirements,
                ],
                env=env,
                check=True,
            )
        subprocess.run([str(python), "-m", "pip", "check"], env=env, check=True)
        marker.write_text(fingerprint)
    else:
        print(f"[1/3] Reusing Python environment: {directory}", flush=True)
    return python


def _run(config_path, check_only, cache=None):
    from flashrsi._launch import _run as execute

    return execute(config_path, check_only, cache or _cache_root())


def main(argv=None, *, default_config="experiment.local.yaml"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / default_config,
        help=f"Experiment YAML (default: {default_config} in the project)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_cache_root(),
        help="Dependency environments and default download caches",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Install dependencies and prepare data without calling models",
    )
    parser.add_argument("--_run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_launch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Show selected dependencies and prerequisites without preparing experiment resources",
    )
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    config = args.config.expanduser().resolve()
    if not config.is_file():
        if config == ROOT / default_config:
            shutil.copy2(TEMPLATE, config)
            print(
                f"Created configuration: {config}\nFill in both roles' model_name, api_key "
                "and base_url, then rerun this command."
            )
            return 2
        parser.error(f"Configuration file does not exist: {config}")
    cache = args.cache_dir.expanduser().resolve()
    env = _environment(cache)
    if args._run:
        return _run(config, args.check_only, cache)
    try:
        stage = "--_launch"
        if args._launch:
            # Plan with the current source and PyYAML; execute the installed wheel.
            sys.path.insert(0, str(ROOT))
            from flashrsi._launch import _load, _plan, _validate_host, _validate_roles

            resolved = _load(config)
            plan = _plan(resolved)
            if args.plan:
                print(json.dumps(plan, indent=2, ensure_ascii=False))
                return 0
            _validate_roles(resolved)
            _validate_host(resolved)
            print(
                f"Selected: {resolved.algorithm.name} + {resolved.agent.name} + {resolved.benchmark.name}",
                flush=True,
            )
            python = _runtime(cache, env, plan["extras"], plan["requirements"])
            stage = "--_run"
        else:
            python = _bootstrap(cache, env)
        # Native tools may spawn python or installed console scripts by name.
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(python.parent.parent)
        command = [
            str(python),
            "-I",
            "-B",
            "-X",
            "utf8",
            str(Path(__file__).resolve()),
            stage,
            "--config",
            str(config),
            "--cache-dir",
            str(cache),
        ]
        if args.check_only:
            command.append("--check-only")
        if args.plan:
            command.append("--plan")
        return subprocess.run(command, env=env).returncode
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        # Do not echo environment variables or pip index credentials.
        print(
            f"Dependency setup failed ({type(exc).__name__}). "
            "Check the installer output above and rerun the same command.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(
            "Interrupted; cached dependencies and downloads can be reused.",
            file=sys.stderr,
        )
        sys.exit(130)
