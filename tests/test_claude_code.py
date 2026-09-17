"""Exercise the real Claude SDK with a local CLI protocol fixture.

These tests validate SDK invocation and FlashRSI's version/trajectory contract;
the fixture does not replace an end-to-end run of the real Claude Code CLI.
"""

import asyncio
import inspect
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import pytest

from flashrsi.agents import ClaudeCode, MiniAgent
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Snapshot, Task

pytest.importorskip(
    "claude_agent_sdk", reason="Claude Code integration needs the claude-code extra"
)


@pytest.fixture
def local_cli(tmp_path):
    """Speak the SDK's JSON-lines protocol without network or account access."""
    cli = tmp_path / "claude"
    records = tmp_path / "records"
    records.mkdir()
    cli.write_text(
        f"#!{sys.executable}\n"
        + """import json
import os
import sys
import time
import uuid
from pathlib import Path

if '--version' in sys.argv or '-v' in sys.argv:
    print('2.1.252 (Claude Code)')
    raise SystemExit(0)


def emit(message):
    print(json.dumps(message), flush=True)


def values(flag):
    return [sys.argv[i + 1] for i, arg in enumerate(sys.argv[:-1]) if arg == flag]


plugins = values('--plugin-dir')
record = {
    'pid': os.getpid(),
    'cwd': os.getcwd(),
    'argv': sys.argv[1:],
    'plugins': {
        str(root): {
            str(path.relative_to(root)): path.read_text()
            for path in Path(root).rglob('*.md')
        }
        for root in plugins
    },
    'api_key': os.environ.get('ANTHROPIC_API_KEY'),
    'base_url': os.environ.get('ANTHROPIC_BASE_URL'),
    'config_dir': os.environ.get('CLAUDE_CONFIG_DIR'),
}

for line in sys.stdin:
    message = json.loads(line)
    if message['type'] == 'control_request':
        if Path(__file__).with_name('init-error').exists():
            Path(__file__).with_name('records').joinpath('init-error.json').write_text(
                json.dumps(record)
            )
            emit({'type': 'control_response', 'response': {
                'subtype': 'error', 'request_id': message['request_id'],
                'error': 'control initialization failed ' + os.environ.get('ANTHROPIC_API_KEY', ''),
            }})
            continue
        emit({'type': 'control_response', 'response': {
            'subtype': 'success', 'request_id': message['request_id'], 'response': {}
        }})
        continue
    if message['type'] != 'user':
        continue
    prompt = message['message']['content']
    record['prompt'] = prompt
    Path(__file__).with_name('records').joinpath(str(uuid.uuid4()) + '.json').write_text(
        json.dumps(record)
    )
    initialization = {'type': 'system', 'subtype': 'init', 'session_id': 'local-session'}
    if prompt == 'plugin-error':
        initialization['plugin_errors'] = [{
            'type': 'plugin-load-failed', 'source': 'flashrsi@inline',
            'message': 'candidate plugin could not load ' + os.environ.get('ANTHROPIC_API_KEY', ''),
        }]
    elif prompt == 'mcp-error':
        initialization['mcp_servers'] = [{'name': 'candidate-server', 'status': 'failed'}]
    elif prompt == 'mcp-auth':
        initialization['mcp_servers'] = [{'name': 'candidate-server', 'status': 'needs-auth'}]
    elif prompt == 'mcp-disabled':
        initialization['mcp_servers'] = [{'name': 'unused-server', 'status': 'disabled'}]
    emit(initialization)
    answer = 'Paris'
    if prompt == 'probe-skill':
        answer = 'candidate' if 'CANDIDATE_SKILL' in json.dumps(record['plugins']) else 'baseline'
    elif prompt == 'edit-target':
        target = Path.cwd() / 'skills/main.md'
        target.write_text('updated by Claude worker')
        emit({'type': 'assistant', 'message': {'model': 'local-claude', 'content': [{
            'type': 'tool_use', 'id': 'edit-1', 'name': 'Write',
            'input': {'file_path': str(target), 'content': 'updated by Claude worker'}
        }]}})
        emit({'type': 'user', 'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': 'edit-1', 'content': 'File updated'
        }]}})
        answer = 'edited'
    elif prompt.startswith('echo:'):
        answer = prompt
    elif prompt in ('crash', 'noisy-crash'):
        if prompt == 'noisy-crash':
            print('discarded-old-diagnostic\\n' + ('x' * 16000), file=sys.stderr)
        print('local crash ' + os.environ.get('ANTHROPIC_API_KEY', ''), file=sys.stderr)
        raise SystemExit(7)
    emit({'type': 'assistant', 'message': {
        'model': 'local-claude', 'content': [{'type': 'text', 'text': answer}],
        'usage': {'input_tokens': 11, 'output_tokens': 3},
    }})
    if prompt == 'wait':
        time.sleep(30)
    if prompt == 'missing-result':
        raise SystemExit(0)
    failed = prompt in ('error', 'api-error')
    result = {
        'type': 'result', 'subtype': 'error_max_turns' if prompt == 'error' else 'success',
        'duration_ms': 25, 'duration_api_ms': 20, 'is_error': failed,
        'num_turns': 1, 'session_id': 'local-session', 'total_cost_usd': 0.01,
        'usage': {'input_tokens': 11, 'output_tokens': 3},
        'modelUsage': {'local-claude': {'inputTokens': 11, 'outputTokens': 3}},
        'errors': ['turn budget exhausted'] if failed else [],
        'result': answer,
    }
    if prompt == 'deferred-tool':
        result.update(
            result='', stop_reason='tool_deferred', terminal_reason='tool_deferred',
            deferred_tool_use={
                'id': 'read-pending', 'name': 'Read', 'input': {'file_path': 'answer.txt'},
            },
        )
    elif prompt in ('aborted_streaming', 'aborted_tools'):
        result['terminal_reason'] = prompt
    emit(result)
    if prompt == 'slow-exit':
        time.sleep(30)
    break
"""
    )
    cli.chmod(0o755)
    return cli, records


def _config(local_cli, *, llm=None, **overrides):
    cli, _ = local_cli
    return {
        "llm": {
            "model_name": "local-claude",
            "api_key": "local-test-key",
            "base_url": "http://127.0.0.1:1",
            **(llm or {}),
        },
        "cli_path": str(cli),
        "timeout": 10,
        **overrides,
    }


def _records(local_cli):
    return [json.loads(path.read_text()) for path in local_cli[1].glob("*.json")]


def _copy_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(ClaudeCode)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return source


def _write_skill(source):
    skill = source / "skills/probe/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: probe\ndescription: Read the test evidence.\n---\nBASELINE_SKILL\n"
    )
    return skill


def _trace_text(trajectory):
    return json.dumps(
        {
            "output": trajectory.output,
            "error": trajectory.error_message,
            "messages": [dict(message) for message in trajectory.messages],
            "usage": dict(trajectory.usage),
        }
    )


def test_run_uses_sdk_process_and_preserves_native_trace(local_cli):
    config = _config(local_cli, llm={"effort": "high"}, max_turns=7)
    agent = ClaudeCode(config)
    result = asyncio.run(agent.run("Capital of France?"))

    assert result.status == "finished", result.error_message
    assert result.output == "Paris" and result.task is None
    (request,) = _records(local_cli)
    assert request["prompt"] == "Capital of France?"
    assert request["pid"] != os.getpid()
    assert request["api_key"] == "local-test-key"
    assert request["base_url"] == "http://127.0.0.1:1"
    assert request["argv"][request["argv"].index("--model") + 1] == "local-claude"
    assert request["argv"][request["argv"].index("--max-turns") + 1] == "7"
    assert request["argv"][request["argv"].index("--effort") + 1] == "high"
    assert result.messages[0]["type"] == "RunConfig"
    assert result.messages[0]["config"]["llm"] == {
        "model_name": "local-claude",
        "api_key": None,
        "base_url": "http://127.0.0.1:1",
        "effort": "high",
    }
    run_input = next(
        message for message in result.messages if message["type"] == "RunInput"
    )
    assert run_input["system_prompt"] == {
        "type": "preset",
        "preset": "claude_code",
    }
    assert "CLAUDE.md" not in agent.snapshot.files
    assert not any(path.startswith("skills/") for path in agent.snapshot.files)
    assert "Paris" in _trace_text(result)
    assert "input_tokens" in json.dumps(dict(result.usage))
    assert "output_tokens" in json.dumps(dict(result.usage))
    assert "0.01" in json.dumps(dict(result.usage))
    assert result.messages
    assert not Path(request["cwd"]).exists()
    assert "local-test-key" not in _trace_text(result)
    assert all(
        b"local-test-key" not in entry.content
        for entry in agent.snapshot.files.values()
    )


def test_rollout_can_be_graded_by_searchqa(local_cli, tmp_path):
    data = tmp_path / "questions.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": f"question-{index}",
                    "question": "Capital of France?",
                    "context": "Paris is the capital of France.",
                    "answers": ["Paris"],
                }
                for index in range(3)
            ]
        )
    )
    config = load_config(
        overrides={
            "benchmark": {"data_path": data},
            "agent": _config(local_cli, name="claude_code"),
            "algorithm": {"worker": {"llm": {"model_name": "local-claude"}}},
        }
    )
    benchmark = SearchQA(config)
    benchmark.load()
    agent = ClaudeCode(config.agent)
    (result,) = asyncio.run(agent.rollout(benchmark.dev))
    (graded,) = benchmark.grade((result,))

    assert result.task is benchmark.dev[0]
    assert result.metrics == {}
    assert graded.metrics == {"exact_match": 1, "f1": 1}
    assert graded.messages == result.messages
    assert graded.usage == result.usage and result.usage


def test_skill_candidate_reaches_sdk_without_selecting_version(local_cli, tmp_path):
    source = _copy_source(tmp_path)
    _write_skill(source)
    agent = ClaudeCode(_config(local_cli, source_dir=source))
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    skill = next(
        path
        for path, entry in baseline.files.items()
        if entry.component == "skill" and path.endswith("SKILL.md")
    )
    with baseline.check_out() as directory:
        path = directory / skill
        path.write_text(path.read_text() + "\nCANDIDATE_SKILL\n")
        candidate = baseline.commit(directory)
    saved = tmp_path / "candidate.json"
    candidate.save(saved)

    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "probe-skill")], snapshot=Snapshot.load(saved))
    )
    assert trial.output == "candidate", trial.error_message
    assert agent.snapshot is baseline
    assert asyncio.run(agent.run("probe-skill")).output == "baseline"
    agent.update(candidate)
    assert asyncio.run(agent.run("probe-skill")).output == "candidate"
    assert "CANDIDATE_SKILL" not in (source / skill).read_text()


def test_worker_passes_own_configuration_and_edits_target(local_cli, tmp_path):
    source = _copy_source(tmp_path)
    instructions = source / "CLAUDE.md"
    instructions.write_text("WORKER_PRIVATE_INSTRUCTIONS")
    config = load_config(
        overrides={
            "agent": {
                "name": "miniagent",
                "llm": {
                    "model_name": "target-model",
                    "api_key": "target-private-key",
                    "base_url": "http://127.0.0.1:2",
                },
            },
            "algorithm": {
                "worker": _config(
                    local_cli,
                    type="agent",
                    name="claude_code",
                    source_dir=source,
                    llm={"model_name": "worker-model"},
                )
            },
        }
    )
    worker = ClaudeCode(config.algorithm.worker)
    target = MiniAgent(config.agent)
    target.set_scope({"skill": "rw"})
    baseline = target.snapshot

    with baseline.check_out() as directory:
        (directory / "CLAUDE.md").write_text("TARGET_UNRELATED_INSTRUCTIONS")
        (directory / ".claude").mkdir()
        (directory / ".claude/settings.json").write_text("invalid target settings")
        result = asyncio.run(worker.run("edit-target", working_dir=directory))
        assert (directory / "skills/main.md").read_text() == "updated by Claude worker"
        # Only versioned skill files belong to the candidate being committed.
        (directory / "CLAUDE.md").unlink()
        shutil.rmtree(directory / ".claude")
        candidate = baseline.commit(directory)

    assert result.status == "finished", result.error_message
    assert result.output == "edited"
    assert target.snapshot is baseline
    assert candidate.files["skills/main.md"].content == b"updated by Claude worker"
    (request,) = _records(local_cli)
    arguments = json.dumps(request["argv"])
    assert request["argv"][request["argv"].index("--model") + 1] == "worker-model"
    assert request["api_key"] == "local-test-key"
    assert request["base_url"] == "http://127.0.0.1:1"
    assert result.messages[0]["config"]["llm"]["model_name"] == "worker-model"
    assert "WORKER_PRIVATE_INSTRUCTIONS" in arguments
    assert "TARGET_UNRELATED_INSTRUCTIONS" not in arguments
    assert "--setting-sources=" in request["argv"]
    assert request["plugins"]
    assert "Write" in _trace_text(result)
    assert "File updated" in _trace_text(result)


@pytest.mark.parametrize("prompt", ["error", "api-error", "missing-result", "crash"])
def test_failed_runs_return_an_error_trajectory(local_cli, prompt):
    agent = ClaudeCode(_config(local_cli))
    result = asyncio.run(agent.run(prompt))

    assert result.status == "error"
    assert result.output == ""
    assert result.error_message
    assert "local-test-key" not in _trace_text(result)
    if prompt == "error":
        assert "turn budget exhausted" in result.error_message
        assert "error_max_turns" in _trace_text(result)
        assert result.messages and result.usage


def test_timeout_stops_sdk_process_and_preserves_received_messages(local_cli):
    agent = ClaudeCode(_config(local_cli, timeout=1))
    result = asyncio.run(agent.run("wait"))

    assert result.status == "error"
    assert "timed out" in result.error_message.lower()
    assert result.messages
    (request,) = _records(local_cli)
    assert not Path(request["cwd"]).exists()
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(request["pid"], 0)


def test_cancellation_reaps_sdk_process_before_removing_version(local_cli):
    agent = ClaudeCode(_config(local_cli, timeout=30))

    async def cancel():
        task = asyncio.create_task(agent.run("wait"))
        try:
            async with asyncio.timeout(10):
                while not _records(local_cli):
                    await asyncio.sleep(0.02)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(cancel())
    (request,) = _records(local_cli)
    assert all(not Path(root).exists() for root in request["plugins"])
    assert not Path(request["cwd"]).exists()
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(request["pid"], 0)


def test_concurrent_candidates_have_independent_sdk_directories(local_cli, tmp_path):
    source = _copy_source(tmp_path)
    _write_skill(source)
    agent = ClaudeCode(_config(local_cli, source_dir=source))
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        skill = directory / "skills/probe/SKILL.md"
        skill.write_text(skill.read_text() + "\nCANDIDATE_SKILL\n")
        candidate = baseline.commit(directory)

    async def evaluate():
        return await asyncio.gather(
            agent.rollout([Task("baseline", "probe-skill")]),
            agent.rollout([Task("candidate", "probe-skill")], snapshot=candidate),
        )

    (original,), (trial,) = asyncio.run(evaluate())
    assert original.output == "baseline" and trial.output == "candidate"
    assert agent.snapshot is baseline
    requests = _records(local_cli)
    assert len({request["cwd"] for request in requests}) == 2
    assert len({root for request in requests for root in request["plugins"]}) == 2


def test_environment_defaults_and_config_override_do_not_mutate_parent(
    local_cli, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "inherited-test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:2")
    agent = ClaudeCode(_config(local_cli, llm={"api_key": None, "base_url": None}))
    assert asyncio.run(agent.run("Capital?")).status == "finished"
    (request,) = _records(local_cli)
    assert request["api_key"] == "inherited-test-key"
    assert request["base_url"] == "http://127.0.0.1:2"
    agent = ClaudeCode(_config(local_cli))
    assert asyncio.run(agent.run("Capital?")).status == "finished"
    assert os.environ["ANTHROPIC_API_KEY"] == "inherited-test-key"
    assert os.environ["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:2"


def test_next_run_uses_updated_llm_without_changing_snapshot(local_cli):
    agent = ClaudeCode(_config(local_cli))
    baseline = agent.snapshot
    first = asyncio.run(agent.run("Before config change"))
    agent.config.llm.model_name = "updated-model"
    agent.config.llm.api_key = "updated-private-key"
    agent.config.llm.effort = "low"
    second = asyncio.run(agent.run("After config change"))

    assert first.status == second.status == "finished"
    assert agent.snapshot is baseline
    records = {request["prompt"]: request for request in _records(local_cli)}
    assert records["Before config change"]["api_key"] == "local-test-key"
    updated = records["After config change"]
    assert updated["api_key"] == "updated-private-key"
    assert updated["argv"][updated["argv"].index("--model") + 1] == "updated-model"
    assert updated["argv"][updated["argv"].index("--effort") + 1] == "low"
    assert first.messages[0]["config"]["llm"]["model_name"] == "local-claude"
    assert second.messages[0]["config"]["llm"]["model_name"] == "updated-model"
    assert "updated-private-key" not in _trace_text(second)


def test_nested_config_credentials_are_redacted_from_input_and_native_output(local_cli):
    secret = "Bearer nested-private-value"
    agent = ClaudeCode(
        _config(
            local_cli,
            llm={
                "extra_body": {"headers": {"Authorization": secret}},
            },
        )
    )
    result = asyncio.run(agent.run("echo:" + secret))
    assert result.status == "finished", result.error_message
    assert result.output == "echo:[REDACTED]"
    assert secret not in _trace_text(result)
    record = result.messages[0]["config"]
    assert record["llm"]["extra_body"]["headers"]["Authorization"] is None


def test_cli_stderr_is_redacted_before_logging(local_cli, capfd, caplog):
    caplog.set_level(logging.DEBUG, logger="flashrsi.agents.claude_code")
    result = asyncio.run(ClaudeCode(_config(local_cli)).run("crash"))
    captured = capfd.readouterr()
    assert result.status == "error"
    assert "local-test-key" not in captured.out + captured.err + caplog.text
    assert "local crash [REDACTED]" in caplog.text
    assert "local crash [REDACTED]" in result.error_message


@pytest.mark.parametrize(
    ("prompt", "diagnostic"),
    [
        ("plugin-error", "candidate plugin could not load"),
        ("mcp-error", "candidate-server"),
        ("mcp-auth", "candidate-server"),
    ],
)
def test_unloaded_extensions_cannot_produce_a_successful_candidate(
    local_cli, prompt, diagnostic
):
    result = asyncio.run(ClaudeCode(_config(local_cli)).run(prompt))

    assert result.status == "error"
    assert result.output == ""
    assert diagnostic in result.error_message
    assert diagnostic in _trace_text(result)
    assert "local-test-key" not in _trace_text(result)
    assert any(message["type"] == "SystemMessage" for message in result.messages)


def test_intentionally_disabled_mcp_server_does_not_fail_the_run(local_cli):
    result = asyncio.run(ClaudeCode(_config(local_cli)).run("mcp-disabled"))

    assert result.status == "finished", result.error_message
    assert result.output == "Paris"


def test_deferred_tool_is_an_error_with_pending_input_preserved(local_cli):
    result = asyncio.run(ClaudeCode(_config(local_cli)).run("deferred-tool"))

    assert result.status == "error"
    assert result.output == ""
    assert "defer" in result.error_message.lower()
    native_result = next(
        message for message in result.messages if message["type"] == "ResultMessage"
    )
    assert native_result["terminal_reason"] == "tool_deferred"
    assert native_result["deferred_tool_use"] == {
        "type": "DeferredToolUse",
        "id": "read-pending",
        "name": "Read",
        "input": {"file_path": "answer.txt"},
    }
    assert result.usage["input_tokens"] == 11


def test_sdk_control_errors_return_redacted_trace_and_reap_process(local_cli):
    cli, _ = local_cli
    cli.with_name("init-error").touch()
    result = asyncio.run(ClaudeCode(_config(local_cli)).run("question"))

    assert result.status == "error"
    assert result.output == ""
    assert "control initialization failed" in result.error_message
    assert "local-test-key" not in _trace_text(result)
    run_input = next(
        message for message in result.messages if message["type"] == "RunInput"
    )
    assert run_input["prompt"] == "question"
    (request,) = _records(local_cli)
    assert not Path(request["cwd"]).exists()
    assert all(not Path(root).exists() for root in request["plugins"])
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(request["pid"], 0)


@pytest.mark.parametrize("reason", ["aborted_streaming", "aborted_tools"])
def test_aborted_result_retains_partial_trace_without_reporting_success(
    local_cli, reason
):
    trajectory = asyncio.run(ClaudeCode(_config(local_cli)).run(reason))

    assert trajectory.status == "error"
    assert reason in trajectory.error_message
    assert trajectory.output == ""
    assert trajectory.messages[-1]["terminal_reason"] == reason
    assert trajectory.usage["output_tokens"] == 3


def test_stderr_diagnostic_is_bounded_and_redacted(local_cli):
    trajectory = asyncio.run(ClaudeCode(_config(local_cli)).run("noisy-crash"))

    assert trajectory.status == "error"
    assert "local crash [REDACTED]" in trajectory.error_message
    assert "discarded-old-diagnostic" not in trajectory.error_message
    assert "local-test-key" not in _trace_text(trajectory)
    assert len(trajectory.error_message) < 9000


def test_execution_deadline_does_not_interrupt_sdk_shutdown(local_cli):
    result = asyncio.run(ClaudeCode(_config(local_cli, timeout=1)).run("slow-exit"))
    assert result.status == "finished", result.error_message
    (request,) = _records(local_cli)
    assert not Path(request["cwd"]).exists()
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(request["pid"], 0)


@pytest.mark.parametrize("content", [None, "", " \n\t"])
def test_optional_prompt_uses_native_preset_without_changing_baseline(
    local_cli, tmp_path, content
):
    source = _copy_source(tmp_path)
    (source / "CLAUDE.md").write_text("OPTIONAL_PROJECT_INSTRUCTIONS")
    agent = ClaudeCode(_config(local_cli, source_dir=source))
    agent.set_scope({"prompt": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        instructions = directory / "CLAUDE.md"
        if content is None:
            instructions.unlink()
        else:
            instructions.write_text(content)
        candidate = baseline.commit(directory)
    (result,) = asyncio.run(
        agent.rollout([Task("missing-prompt", "question")], snapshot=candidate)
    )
    assert result.status == "finished", result.error_message
    assert result.output == "Paris"
    run_input = next(
        message for message in result.messages if message["type"] == "RunInput"
    )
    assert run_input["system_prompt"] == {
        "type": "preset",
        "preset": "claude_code",
    }
    assert agent.snapshot is baseline
    current = asyncio.run(agent.run("question"))
    assert current.status == "finished", current.error_message
    current_input = next(
        message for message in current.messages if message["type"] == "RunInput"
    )
    assert current_input["system_prompt"]["append"] == "OPTIONAL_PROJECT_INSTRUCTIONS"


def test_invalid_optional_prompt_returns_error_before_starting_sdk(local_cli, tmp_path):
    source = _copy_source(tmp_path)
    (source / "CLAUDE.md").write_bytes(b"\xff")
    agent = ClaudeCode(_config(local_cli, source_dir=source))

    result = asyncio.run(agent.run("question"))

    assert result.status == "error"
    assert "utf-8" in result.error_message
    assert not _records(local_cli)
