"""Verify an installed wheel on Linux using localhost replay and actual tools.

Run with the acceptance venv's ``python -I`` from outside the source checkout.
Stage the repository's tests separately and pass that directory with --suite.
Only the explicit tests below run; native Rust build tests are never selected.
The native oracle is a separate, pinned installed binary, not a fallback core.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

GROUPS = {
    "file_task_parity": (
        [
            "test_codex_task_parity.py::test_native_and_python_complete_same_file_editing_task"
        ],
        "danger-full-access",
    ),
    "tool_mechanisms_parity": (["test_codex_task_tools_regression.py"], None),
    "interactive_pty_parity": (["test_codex_task_exec_parity.py"], None),
    "code_mode_parity": (
        [
            "test_codex_python_code_mode.py::test_code_mode_native_and_python_match_complete_local_task",
            "test_codex_python_code_mode.py::test_code_mode_native_and_python_match_yield_wait_notify_cancel_and_errors",
            "test_codex_python_lite.py",
        ],
        None,
    ),
    "posix_lifecycle": (
        [
            "test_codex_python_tools.py::test_shell_exit_workdir_environment_and_timeout",
            "test_codex_python_tools.py::test_exec_sessions_poll_and_pipe_stdin_refusal",
            "test_codex_python_tools.py::test_real_pty_and_interactive_stdin",
            "test_codex_python_tools.py::test_cancel_and_close_kill_process_groups",
            "test_codex_python_tools.py::test_restricted_sandbox_never_silently_degrades",
        ],
        None,
    ),
    "snapshot_and_linux_boundary": (["test_codex_linux_acceptance.py"], None),
}


def version(command):
    path = shutil.which(command)
    if path is None:
        return None
    result = subprocess.run(
        [path, "--version"], capture_output=True, text=True, timeout=10
    )
    return {"path": path, "version": result.stdout.strip() or result.stderr.strip()}


def verify_wheel(path, installed):
    """Check wheel bytes against the actual installed package before testing."""
    count = 0
    package_root = installed.parents[2]
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith("flashrsi/"):
                continue
            expected = archive.read(info)
            target = package_root / info.filename
            if not target.is_file() or target.read_bytes() != expected:
                raise ValueError(f"Installed bytes differ from wheel: {info.filename}")
            count += 1
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "files": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--home-dir", type=Path)
    parser.add_argument("--extra-test", action="append", default=[])
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Acceptance requires an actual Linux kernel")
    from flashrsi.agents import Codex

    installed = Path(inspect.getfile(Codex)).resolve().parent
    if "site-packages" not in installed.parts:
        parser.error("Acceptance must import an installed wheel, not checkout code")
    if (installed / "runtime").exists() or (installed / "_bridge").exists():
        parser.error("The installed package unexpectedly contains the Rust runtime")
    if importlib.metadata.version("openai-codex-cli-bin") != "0.147.0":
        parser.error("The native oracle must be exactly 0.147.0")
    suite = args.suite.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    isolated_home = args.home_dir.resolve() if args.home_dir else output / "home"
    isolated_home.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(isolated_home),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "XDG_CACHE_HOME": str(isolated_home / ".cache"),
            "XDG_DATA_HOME": str(isolated_home / ".local/share"),
            "CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        env[name] = "http://127.0.0.1:1"
    for name in (
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    ):
        env.pop(name, None)
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "installed_codex": str(installed),
        "oracle_version": importlib.metadata.version("openai-codex-cli-bin"),
        "installation_scope": "Codex runtime dependencies, pytest and native oracle; unrelated harness and dataset dependencies are not installed",
        "installed_dependencies": {
            distribution.metadata["Name"]: distribution.version
            for distribution in importlib.metadata.distributions()
        },
        "node": version("node"),
        "bash": version("bash"),
        "zsh": version("zsh"),
        "wheel": verify_wheel(args.wheel.resolve(), installed),
        "sandbox": "danger-full-access; unsupported restricted Linux remains explicit",
        "real_model_calls": False,
        "rust_compilation": False,
        "groups": {},
    }
    container_image = os.environ.get("FLASHRSI_ACCEPTANCE_DOCKER_IMAGE")
    if container_image:
        report["container"] = {
            "image_id": container_image,
            "network": "none",
            "read_only_root": True,
            "disposable": True,
            "init": os.environ.get("FLASHRSI_ACCEPTANCE_DOCKER_INIT") == "1",
            "runtime_fixture": "Task-only copied Python, Node, shells and non-glibc shared libraries",
        }
    groups = dict(GROUPS)
    if args.extra_test:
        groups["additional_migrated_mechanisms"] = (args.extra_test, None)
    all_passed = True
    for name, (tests, selection) in groups.items():
        xml = output / f"{name}.xml"
        command = [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-c",
            "/dev/null",
            "--rootdir",
            str(suite),
            "--basetemp",
            str(output / f"tmp-{name}"),
            "--junitxml",
            str(xml),
            "-q",
            *[str(suite / test) for test in tests],
        ]
        if selection:
            command.extend(["-k", selection])
        with (output / f"{name}.txt").open("w") as log:
            result = subprocess.run(
                command, cwd=suite.parent, env=env, stdout=log, stderr=log, timeout=600
            )
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        if xml.exists():
            for node in ET.parse(xml).getroot().iter("testsuite"):
                for key in counts:
                    counts[key] += int(node.get(key, 0))
        passed = (
            result.returncode == 0 and counts["tests"] > 0 and not counts["skipped"]
        )
        all_passed = all_passed and passed
        report["groups"][name] = {
            "returncode": result.returncode,
            "passed": passed,
            **counts,
            "command": command,
        }
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(name, json.dumps(report["groups"][name]), flush=True)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
