import asyncio
import os
import subprocess

import pytest

from flashrsi.integrations import _container_payload
from flashrsi.integrations._docker_harness import _setup


@pytest.mark.parametrize("source", [None, "astral", "github"])
def test_container_setup_uses_selected_pinned_installer(tmp_path, source):
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)

    config = {} if source is None else {"container_uv_install_source": source}
    asyncio.run(_setup(docker, "agent", "network", tmp_path, config, 60))
    script = calls[-1][-1]
    expected = (
        "https://github.com/astral-sh/uv/releases/download/0.11.4/uv-installer.sh"
        if source == "github"
        else "https://astral.sh/uv/0.11.4/install.sh"
    )
    assert expected in script
    assert "--managed-python" in script
    assert "requirements.txt" in script


@pytest.mark.parametrize("source", ["unknown", None, [], True])
def test_invalid_installer_fails_before_creating_container(tmp_path, source):
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)

    with pytest.raises(ValueError, match="container_uv_install_source"):
        asyncio.run(
            _setup(
                docker,
                "agent",
                "network",
                tmp_path,
                {"container_uv_install_source": source},
                60,
            )
        )
    assert not calls


@pytest.mark.skipif(os.name == "nt", reason="container setup executes POSIX shell")
@pytest.mark.parametrize(
    "version,reuse",
    [("0.11.4", True), ("0.11.4 (x86_64-unknown-linux-gnu)", True), ("0.10.0", False)],
)
def test_preinstalled_uv_only_skips_download_when_version_matches(
    tmp_path, monkeypatch, version, reuse
):
    root = tmp_path / "runtime"
    binary = root / "bin" / "uv"
    binary.parent.mkdir(parents=True)
    calls = tmp_path / "calls"
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
        f'  echo "uv {version}"\nelse\n  echo "$*" >> {calls}\nfi\n'
    )
    binary.chmod(0o755)
    commands = tmp_path / "commands"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text("#!/bin/sh\nexit 79\n")
    curl.chmod(0o755)
    monkeypatch.setattr(_container_payload, "_ROOT", str(root))
    result = subprocess.run(
        ["/bin/sh", "-c", _container_payload._setup_script()],
        env={**os.environ, "PATH": str(commands) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    if reuse:
        assert result.returncode == 0, result.stderr
        assert calls.read_text().splitlines() == [
            f"venv --python 3.12 --managed-python {root}/venv",
            f"pip install --python {root}/venv/bin/python -r {root}/requirements.txt",
        ]
    else:
        assert result.returncode == 79
        assert not calls.exists()
