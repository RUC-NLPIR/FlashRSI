"""Exercise the Codex adapter's subprocess contract without model requests."""

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from flashrsi.agents import Codex
from flashrsi.core import Task


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "skills/probe").mkdir(parents=True)
    (root / "components.yaml").write_text(
        "prompt: [AGENTS.md]\nskill: [skills/**]\nagent: [agents/**]\n"
        "hook: [hooks/**]\ntool: [servers/**]\nplugin: [plugins/**]\n"
        "memory: [memories/**]\nconfig: [config.toml, rules/**]\n"
    )
    (root / "AGENTS.md").write_text("VERSIONED_INSTRUCTIONS")
    (root / "skills/probe/SKILL.md").write_text(
        "---\nname: probe\ndescription: Check evidence\n---\nNative procedure.\n"
    )
    (root / "config.toml").write_text('personality = "pragmatic"\n')
    return root


@pytest.fixture
def native_cli(tmp_path):
    binary, record = tmp_path / "codex", tmp_path / "requests.jsonl"
    binary.write_text(
        f"#!{sys.executable}\nRECORD = {str(record)!r}\n"
        + r"""
import json
import os
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

home = Path(os.environ['CODEX_HOME'])
prompt = sys.stdin.read()
args = sys.argv[1:]
overrides = tomllib.loads('\n'.join(
    args[index + 1] for index, arg in enumerate(args) if arg == '-c'
))
resources = {
    str(path.relative_to(home)): path.read_text()
    for path in home.rglob('*') if path.is_file()
}
request = {
    'pid': os.getpid(), 'home': str(home), 'cwd': os.getcwd(),
    'prompt': prompt, 'args': args, 'overrides': overrides,
    'resources': resources,
    'env': {name: value for name, value in os.environ.items()
            if name.startswith(('CODEX_', 'FLASHRSI_CODEX_', 'OPENAI_'))},
}
child = None
if prompt == 'block':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    request['child_pid'] = child.pid
    def stop(signum, frame):
        child.wait(timeout=2)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
elif prompt in {'notify-delayed', 'background-linger'}:
    delay = 0.15 if prompt == 'notify-delayed' else 30
    child = subprocess.Popen([
        sys.executable, '-c',
        "import json,os,time;from pathlib import Path;"
        "Path('notify-child.json').write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgid(0)}));"
        "time.sleep(" + str(delay) + ");"
        "Path('notify-completed.txt').write_text('NATIVE_NOTIFY_COMPLETED')",
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 5
    while not Path('notify-child.json').exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('notification child did not start')
        time.sleep(0.005)
    request['child_pid'] = child.pid
with Path(RECORD).open('a') as stream:
    stream.write(json.dumps(request) + '\n')

def emit(event):
    print(json.dumps(event), flush=True)

emit({'type': 'thread.started', 'thread_id': 'thread-local'})
emit({'type': 'item.completed', 'item': {
    'type': 'command_execution', 'command': 'inspect resources', 'exit_code': 0,
}})
if prompt == 'block':
    time.sleep(30)
elif prompt == 'failed':
    emit({'type': 'turn.failed', 'error': {'message': 'native turn failed'}})
elif prompt == 'process-failure':
    print('native process diagnostic', file=sys.stderr)
    raise SystemExit(7)
elif prompt == 'malformed':
    print('not-json', flush=True)
elif prompt == 'no-terminal':
    pass
elif prompt == 'secret-failure':
    secret = os.environ.get('FLASHRSI_CODEX_API_KEY')
    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': secret}})
    emit({'type': 'turn.failed', 'error': {'message': 'failed with ' + secret}})
    print('stderr with ' + secret, file=sys.stderr)
else:
    if prompt == 'success-warning':
        print('extension warning with ' + os.environ['FLASHRSI_CODEX_API_KEY'], file=sys.stderr)
    answer = resources.get('AGENTS.md', 'native-default')
    if prompt == 'edit':
        Path('edited.md').write_text(answer)
    if prompt == 'mutate-home':
        (home / 'AGENTS.md').write_text('RUN_LOCAL_MUTATION')
        (home / 'session-artifact').write_text('not a versioned resource')
    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': answer}})
    emit({'type': 'turn.completed', 'usage': {
        'input_tokens': 19, 'cached_input_tokens': 5, 'output_tokens': 3,
    }})
"""
    )
    binary.chmod(0o755)
    return binary, record


def _agent(source, native_cli, *, llm=None, **options):
    return Codex(
        {
            "source_dir": source,
            "cli_path": str(native_cli[0]),
            "timeout": 5,
            "llm": {
                "model_name": "test-codex",
                "api_key": "local-test-private-key",
                "base_url": "http://127.0.0.1:1/v1",
                **(llm or {}),
            },
            **options,
        }
    )


def _requests(native_cli):
    return [json.loads(line) for line in native_cli[1].read_text().splitlines()]


def test_native_resources_and_role_config_are_run_local(
    source, native_cli, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ambient-home"))
    monkeypatch.setenv("CODEX_API_KEY", "ambient-private-key")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-openai-key")
    task = tmp_path / "task"
    task.mkdir()
    (task / "AGENTS.md").write_text("TASK_INSTRUCTIONS")
    agent = _agent(source, native_cli, llm={"reasoning_effort": "low"})
    baseline = agent.snapshot

    result = asyncio.run(agent.run("mutate-home", working_dir=task))

    assert result.status == "finished", result.error_message
    assert result.output == "VERSIONED_INSTRUCTIONS"
    request = _requests(native_cli)[0]
    assert request["cwd"] == str(task)
    assert request["resources"]["AGENTS.md"] == "VERSIONED_INSTRUCTIONS"
    assert request["resources"]["skills/probe/SKILL.md"].endswith("Native procedure.\n")
    assert request["resources"]["config.toml"] == 'personality = "pragmatic"\n'
    assert request["args"][request["args"].index("--model") + 1] == "test-codex"
    assert "--ephemeral" in request["args"] and "--json" in request["args"]
    assert "--strict-config" in request["args"]
    assert "--dangerously-bypass-hook-trust" not in request["args"]
    provider = request["overrides"]["model_providers"]["flashrsi"]
    assert provider["base_url"] == "http://127.0.0.1:1/v1"
    assert provider["env_key"] == "FLASHRSI_CODEX_API_KEY"
    assert request["overrides"]["model_reasoning_effort"] == "low"
    assert "project_doc_max_bytes" not in request["overrides"]
    assert request["env"]["FLASHRSI_CODEX_API_KEY"] == "local-test-private-key"
    assert "CODEX_API_KEY" not in request["env"]
    assert "OPENAI_API_KEY" not in request["env"]
    assert not Path(request["home"]).exists()
    assert agent.snapshot is baseline
    assert (source / "AGENTS.md").read_text() == "VERSIONED_INSTRUCTIONS"
    assert baseline.files["AGENTS.md"].content == b"VERSIONED_INSTRUCTIONS"
    assert result.usage["prompt_tokens"] == 19
    assert result.usage["completion_tokens"] == 3
    assert result.usage["prompt_tokens_details"]["cached_tokens"] == 5
    assert result.messages[0]["config"]["llm"]["api_key"] is None


def test_candidate_rollout_uses_candidate_without_selecting_it(source, native_cli):
    agent = _agent(source, native_cli)
    agent.set_scope({"prompt": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        (directory / "AGENTS.md").write_text("CANDIDATE_INSTRUCTIONS")
        candidate = baseline.commit(directory)

    result = asyncio.run(agent.rollout([Task("one", "question")], snapshot=candidate))[
        0
    ]

    assert result.output == "CANDIDATE_INSTRUCTIONS"
    assert result.task.task_id == "one"
    assert result.messages[0]["snapshot_id"] == candidate.id
    assert agent.snapshot is baseline
    assert asyncio.run(agent.run("question")).output == "VERSIONED_INSTRUCTIONS"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group cleanup")
@pytest.mark.parametrize("prompt", ["notify-delayed", "background-linger"])
def test_successful_native_exit_finishes_short_notify_and_bounds_background_cleanup(
    source, native_cli, tmp_path, prompt
):
    task = tmp_path / "notify-task"
    task.mkdir()
    started = time.monotonic()
    try:
        result = asyncio.run(_agent(source, native_cli).run(prompt, task))
        elapsed = time.monotonic() - started
        assert result.status == "finished", result.error_message
        request = _requests(native_cli)[0]
        child = json.loads((task / "notify-child.json").read_text())
        assert child["pid"] == request["child_pid"]
        assert child["pgid"] == request["pid"]
        assert not Path(request["home"]).exists()
        if prompt == "notify-delayed":
            assert (
                task / "notify-completed.txt"
            ).read_text() == "NATIVE_NOTIFY_COMPLETED"
        else:
            assert not (task / "notify-completed.txt").exists()
        assert elapsed < 12
        with pytest.raises(ProcessLookupError):
            os.kill(child["pid"], 0)
    finally:
        marker = task / "notify-child.json"
        if marker.exists():
            with suppress(ProcessLookupError):
                os.kill(json.loads(marker.read_text())["pid"], signal.SIGKILL)


def test_worker_edits_target_using_its_own_resource_version(
    source, native_cli, tmp_path
):
    target = tmp_path / "target"
    target.mkdir()
    (target / "AGENTS.md").write_text("TARGET_INSTRUCTIONS")
    (target / "config.toml").write_text("invalid: [target config must not load")
    worker = _agent(source, native_cli)
    baseline = worker.snapshot

    reply = asyncio.run(worker.edit(target, "edit"))

    assert reply == "VERSIONED_INSTRUCTIONS"
    assert (target / "edited.md").read_text() == "VERSIONED_INSTRUCTIONS"
    assert (target / "AGENTS.md").read_text() == "TARGET_INSTRUCTIONS"
    assert worker.snapshot is baseline
    assert "edited.md" not in worker.snapshot.files


@pytest.mark.parametrize(
    ("prompt", "error"),
    [
        ("failed", "native turn failed"),
        ("process-failure", "exited with 7"),
        ("malformed", "Invalid Codex JSONL"),
        ("no-terminal", "without turn.completed"),
    ],
)
def test_failures_keep_partial_native_trace(source, native_cli, prompt, error):
    result = asyncio.run(_agent(source, native_cli).run(prompt))
    assert result.status == "error"
    assert error in result.error_message
    assert result.output == ""
    assert any(message.get("type") == "thread.started" for message in result.messages)
    assert any(
        message.get("item", {}).get("type") == "command_execution"
        for message in result.messages
    )
    if prompt == "process-failure":
        assert "native process diagnostic" in result.error_message


def test_credentials_are_redacted_from_native_trace_and_errors(source, native_cli):
    result = asyncio.run(_agent(source, native_cli).run("secret-failure"))
    serialized = json.dumps(
        {"messages": list(result.messages), "error": result.error_message},
        default=dict,
    )
    assert result.status == "error"
    assert "local-test-private-key" not in serialized
    assert "[REDACTED]" in result.error_message
    assert "stderr with [REDACTED]" in result.error_message


def test_framework_credentials_do_not_fall_back_to_native_login(
    source, native_cli, tmp_path, monkeypatch
):
    auth_dir = tmp_path / "login"
    auth_dir.mkdir()
    tokens = {
        "access_token": "test-private-login-access",
        "refresh_token": "test-private-login-refresh",
        "id_token": "test-private-login-id",
    }
    auth = json.dumps({"tokens": tokens})
    (auth_dir / "auth.json").write_text(auth)
    monkeypatch.setenv("CODEX_HOME", str(auth_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    result = asyncio.run(_agent(source, native_cli, llm={"api_key": None}).run("q"))
    assert result.status == "error"
    assert "framework role's llm.api_key" in result.error_message
    assert not native_cli[1].exists()
    assert (auth_dir / "auth.json").read_text() == auth


def test_successful_runs_keep_redacted_native_diagnostics(source, native_cli):
    result = asyncio.run(_agent(source, native_cli).run("success-warning"))
    assert result.status == "finished", result.error_message
    diagnostics = [m for m in result.messages if m["type"] == "CodexDiagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["text"] == "extension warning with [REDACTED]"


def test_explicit_hooks_and_native_features_are_preserved(source, native_cli):
    (source / "hooks").mkdir()
    (source / "hooks/session.py").write_text("print('hook')\n")
    (source / "config.toml").write_text(
        "[features]\nplugins = true\nmemories = true\n"
        "[skills.bundled]\nenabled = true\n"
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type = "command"\ncommand = "echo hook"\n'
    )
    result = asyncio.run(_agent(source, native_cli).run("question"))
    assert result.status == "finished", result.error_message
    request = _requests(native_cli)[0]
    assert "hooks/session.py" in request["resources"]
    assert "--dangerously-bypass-hook-trust" in request["args"]
    assert "features" not in request["overrides"]
    assert "bundled" not in request["overrides"].get("skills", {})


def test_mcp_script_paths_follow_the_selected_resource_home(
    source, native_cli, tmp_path
):
    (source / "servers").mkdir()
    (source / "servers/probe.py").write_text("print('MCP')\n")
    native = '[mcp_servers.probe]\ncommand = "python3"\nargs = ["servers/probe.py"]\n'
    (source / "config.toml").write_text(native)
    task = tmp_path / "task"
    task.mkdir()
    result = asyncio.run(_agent(source, native_cli).run("question", working_dir=task))
    assert result.status == "finished", result.error_message
    request = _requests(native_cli)[0]
    expected = str(Path(request["home"]) / "servers/probe.py")
    assert request["overrides"]["mcp_servers"]["probe"]["args"] == [expected]
    assert request["resources"]["config.toml"] == native
    assert request["cwd"] == str(task)


def test_symlinked_ambient_skills_are_disabled_without_following_cycles(
    source, native_cli, tmp_path, monkeypatch
):
    task = tmp_path / "task"
    task.mkdir()
    host = tmp_path / "host-home"
    monkeypatch.setenv("HOME", str(host))
    ambient = host / ".agents/skills"
    ambient.mkdir(parents=True)
    external = tmp_path / "installed-skill"
    external.mkdir()
    skill = external / "SKILL.md"
    skill.write_text("---\nname: ambient\ndescription: Ambient skill\n---\n")
    nested = external / "assets/nested/SKILL.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("---\nname: internal\ndescription: Not a discovered skill\n---\n")
    hidden = ambient / ".hidden/SKILL.md"
    hidden.parent.mkdir()
    hidden.write_text("---\nname: hidden\ndescription: Hidden installation\n---\n")
    (ambient / "external").symlink_to(external, target_is_directory=True)
    (external / "cycle").symlink_to(ambient, target_is_directory=True)

    result = asyncio.run(_agent(source, native_cli).run("question", working_dir=task))

    assert result.status == "finished", result.error_message
    disabled = _requests(native_cli)[0]["overrides"]["skills"]["config"]
    assert {"path": str(skill.resolve()), "enabled": False} in disabled
    assert sum(item["path"] == str(skill.resolve()) for item in disabled) == 1
    assert {"path": str(nested.resolve()), "enabled": False} in disabled
    assert not any(item["path"] == str(hidden.resolve()) for item in disabled)


@pytest.mark.skipif(
    os.name != "posix", reason="Process-group cleanup is POSIX-specific"
)
@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_timeout_and_cancellation_stop_process_group(
    source, native_cli, mode, tmp_path, monkeypatch
):
    # The call budget includes host-skill discovery. This test needs a running
    # child to exercise cleanup, rather than timing out while scanning HOME.
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    agent = _agent(source, native_cli, timeout=1 if mode == "timeout" else 30)

    async def scenario():
        running = asyncio.create_task(agent.run("block"))
        try:
            if mode == "timeout":
                result = await asyncio.wait_for(running, 5)
                assert result.status == "error"
                assert "timed out" in result.error_message
            else:
                async with asyncio.timeout(5):
                    while True:
                        try:
                            recorded = _requests(native_cli)
                        except (FileNotFoundError, json.JSONDecodeError):
                            recorded = []
                        if recorded and "child_pid" in recorded[0]:
                            break
                        await asyncio.sleep(0.01)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running
        finally:
            if not running.done():
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running

    try:
        asyncio.run(scenario())
        request = _requests(native_cli)[0]
        for pid in (request["pid"], request["child_pid"]):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        assert not Path(request["home"]).exists()
        with pytest.raises(RuntimeError, match="only inside"):
            agent.files_dir
    finally:
        if native_cli[1].exists():
            request = _requests(native_cli)[0]
            for key in ("pid", "child_pid"):
                with suppress(ProcessLookupError):
                    os.kill(request[key], signal.SIGKILL)


@pytest.mark.parametrize(
    ("llm", "options", "native", "error"),
    [
        ({"max_tokens": 10}, {}, None, "Unsupported Codex llm fields"),
        ({"api_key": None}, {}, None, "requires the framework role's llm.api_key"),
        ({"auth": "login"}, {}, None, "native login is not supported"),
        ({}, {"auth_dir": "/tmp/native-login"}, None, "auth_dir is unsupported"),
        ({}, {"max_turns": 1}, None, "no max_turns"),
        ({}, {}, 'model = "resource-model"\n', "cannot set runtime fields"),
        ({}, {}, "invalid = [", "Invalid value"),
    ],
)
def test_invalid_runtime_or_native_config_fails_before_launch(
    source, native_cli, llm, options, native, error
):
    if native is not None:
        (source / "config.toml").write_text(native)
    result = asyncio.run(_agent(source, native_cli, llm=llm, **options).run("question"))
    assert result.status == "error"
    assert error in result.error_message
    assert not native_cli[1].exists()


def test_container_rejects_host_cli(source, native_cli):
    with pytest.raises(ValueError, match="omit cli_path"):
        _agent(source, native_cli)._check_container()
