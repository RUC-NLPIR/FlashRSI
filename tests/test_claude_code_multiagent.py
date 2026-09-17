"""Exercise delegated-task transcripts through the real SDK JSON protocol."""

import asyncio
import json
import os
import sys
import time

import pytest
from test_claude_code_native import _config, _copy_source, _message_events
from test_claude_code_native import anthropic_server as anthropic_server

from flashrsi.agents import ClaudeCode
from flashrsi.core import Task

pytest.importorskip(
    "claude_agent_sdk", reason="Claude Code integration needs the claude-code extra"
)


@pytest.fixture
def delegated_cli(tmp_path):
    """Emit several turns and child messages, including post-result events."""
    cli = tmp_path / "claude"
    record = tmp_path / "request.json"
    cli.write_text(
        f"#!{sys.executable}\n"
        + """import json
import os
import sys
import time
from pathlib import Path

if '--version' in sys.argv or '-v' in sys.argv:
    print('2.1.252 (Claude Code)')
    raise SystemExit(0)


def emit(message):
    print(json.dumps(message), flush=True)


def system(subtype, **fields):
    emit({
        'type': 'system', 'subtype': subtype, 'session_id': 'session-parent',
        'uuid': subtype + '-uuid', **fields,
    })


def assistant(content, parent=None):
    emit({
        'type': 'assistant', 'parent_tool_use_id': parent,
        'message': {'model': 'local-claude', 'content': content},
    })


def result(text, turns, **fields):
    emit({
        'type': 'result', 'subtype': 'success', 'is_error': False,
        'duration_ms': turns * 10, 'duration_api_ms': turns * 8,
        'num_turns': turns, 'session_id': 'session-parent',
        'result': text, 'total_cost_usd': turns * 0.01,
        'usage': {'input_tokens': turns * 11, 'output_tokens': turns * 3},
        'modelUsage': {'local-claude': {'inputTokens': turns * 11}},
        **fields,
    })


initialize = {}
for line in sys.stdin:
    message = json.loads(line)
    if message['type'] == 'control_request':
        if message['request']['subtype'] == 'initialize':
            initialize = message['request']
        emit({'type': 'control_response', 'response': {
            'subtype': 'success', 'request_id': message['request_id'], 'response': {},
        }})
        continue
    if message['type'] != 'user':
        continue
    prompt = message['message']['content']
    Path(__file__).with_name('request.json').write_text(json.dumps({
        'pid': os.getpid(), 'prompt': prompt, 'initialize': initialize,
    }))
    system('init')
    task_type = 'local_bash' if prompt == 'shell' else 'local_agent'
    assistant([{
        'type': 'tool_use', 'id': 'delegate-1', 'name': 'Agent',
        'input': {'prompt': 'Find supporting evidence', 'run_in_background': True},
    }])
    system('task_started', task_id='child-1', task_type=task_type,
           tool_use_id='delegate-1', description='Research evidence',
           is_backgrounded=prompt != 'background-transition')
    if prompt == 'background-transition':
        system('background_tasks_changed', tasks=[{
            'task_id': 'child-1', 'task_type': 'local_agent',
            'description': 'Research evidence',
        }])
    result('Delegation launched', 1)
    if prompt == 'child-disappeared':
        break
    if prompt in ('unfinished', 'shell'):
        time.sleep(30)
        break
    time.sleep(0.05)
    if initialize.get('forwardSubagentText'):
        assistant([{'type': 'text', 'text': 'Child evidence local-private-key'}],
                  parent='delegate-1')
    assistant([{
        'type': 'tool_use', 'id': 'read-1', 'name': 'Read',
        'input': {'file_path': 'evidence.md'},
    }], parent='delegate-1')
    emit({
        'type': 'user', 'parent_tool_use_id': 'delegate-1',
        'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': 'read-1', 'content': 'Evidence body',
        }]},
    })
    system('task_progress', task_id='child-1', tool_use_id='delegate-1',
           description='Evidence found', last_tool_name='Read',
           usage={'total_tokens': 17, 'tool_uses': 1, 'duration_ms': 5})
    if prompt == 'updated-only':
        system('task_updated', task_id='child-1',
               patch={'status': 'killed', 'end_time': 123})
    else:
        system('task_notification', task_id='child-1', status='completed',
               tool_use_id='delegate-1', output_file='child-output.txt',
               summary='Evidence collected',
               usage={'total_tokens': 19, 'tool_uses': 1, 'duration_ms': 9})
    if prompt == 'background-transition':
        time.sleep(0.75)
    assistant([{'type': 'text', 'text': 'Final synthesis'}])
    result('Final synthesis', 2, origin={'kind': 'task-notification'})
    break
"""
    )
    cli.chmod(0o755)
    return cli, record


def _agent(delegated_cli, **config):
    return ClaudeCode(
        {
            "llm": {
                "model_name": "local-claude",
                "api_key": "local-private-key",
            },
            "cli_path": str(delegated_cli[0]),
            "timeout": 5,
            **config,
        }
    )


@pytest.mark.parametrize(
    "prompt", ["completed", "updated-only", "background-transition"]
)
def test_delegated_work_continues_after_initial_result(delegated_cli, prompt):
    trajectory = asyncio.run(_agent(delegated_cli).run(prompt))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Final synthesis"
    request = json.loads(delegated_cli[1].read_text())
    assert request["initialize"]["forwardSubagentText"] is True
    results = [m for m in trajectory.messages if m["type"] == "ResultMessage"]
    assert [message["result"] for message in results] == [
        "Delegation launched",
        "Final synthesis",
    ]
    assert results[-1]["origin"] == {"kind": "task-notification"}
    run_input = next(
        message for message in trajectory.messages if message["type"] == "RunInput"
    )
    assert run_input["prompt"] == prompt
    assert run_input["system_prompt"]["preset"] == "claude_code"
    assert trajectory.usage["input_tokens"] == 33
    assert trajectory.usage["output_tokens"] == 9
    assert trajectory.usage["num_turns"] == 3
    assert trajectory.usage["duration_ms"] == 30
    assert trajectory.usage["model_usage"]["local-claude"]["inputTokens"] == 22
    assert trajectory.usage["total_cost_usd"] == 0.02
    assert trajectory.usage["duration_api_ms"] == 16
    child_messages = [
        message
        for message in trajectory.messages
        if message.get("parent_tool_use_id") == "delegate-1"
    ]
    trace = json.dumps([dict(message) for message in child_messages])
    assert "Child evidence [REDACTED]" in trace
    assert "local-private-key" not in trace
    assert "ToolUseBlock" in trace and "ToolResultBlock" in trace
    assert "read-1" in trace and "Evidence body" in trace
    progress = next(
        m for m in trajectory.messages if m["type"] == "TaskProgressMessage"
    )
    assert progress["task_id"] == "child-1"
    assert progress["tool_use_id"] == "delegate-1"
    assert progress["usage"]["total_tokens"] == 17
    if prompt == "updated-only":
        assert any(
            m["type"] == "TaskUpdatedMessage" and m["status"] == "killed"
            for m in trajectory.messages
        )


def test_unfinished_child_is_an_error_and_retains_partial_results(delegated_cli):
    trajectory = asyncio.run(_agent(delegated_cli, timeout=1).run("unfinished"))

    assert trajectory.status == "error"
    assert trajectory.output == ""
    assert "timed out" in trajectory.error_message.lower()
    assert any(m["type"] == "TaskStartedMessage" for m in trajectory.messages)
    assert any(m["type"] == "ResultMessage" for m in trajectory.messages)
    assert trajectory.usage
    if os.name == "posix":
        request = json.loads(delegated_cli[1].read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(request["pid"], 0)


def test_background_shell_does_not_delay_completion(delegated_cli):
    trajectory = asyncio.run(_agent(delegated_cli, timeout=1).run("shell"))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Delegation launched"


def test_stream_ending_with_active_child_does_not_report_success(delegated_cli):
    trajectory = asyncio.run(_agent(delegated_cli).run("child-disappeared"))

    assert trajectory.status == "error"
    assert trajectory.output == ""
    assert trajectory.error_message
    assert any(m["type"] == "ResultMessage" for m in trajectory.messages)


@pytest.mark.parametrize("background", [False, True])
def test_real_subagent_text_and_parent_relationships_reach_trajectory(
    anthropic_server, background
):
    """The bundled CLI invokes Agent and forwards its native child transcript."""

    def reply(request):
        body = request["body"]
        messages = body["messages"]
        encoded = json.dumps(messages)
        request_index = len(anthropic_server.requests)
        tool_calls = [
            block
            for message in messages
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        tool = None
        if any(block["name"] == "Agent" for block in tool_calls):
            text = (
                "Parent synthesis"
                if "NATIVE_CHILD_RESPONSE" in encoded
                else "Child launched; waiting for evidence"
            )
        elif "NATIVE_CHILD_REQUEST" in encoded:
            if background:
                time.sleep(0.2)
            text = "NATIVE_CHILD_RESPONSE"
        else:
            text = ""
            tool = (
                "Agent",
                {
                    "subagent_type": "general-purpose",
                    "description": "Find supporting evidence",
                    "prompt": "NATIVE_CHILD_REQUEST",
                    "run_in_background": background,
                },
            )
        return _message_events(
            body,
            text,
            tool=tool,
            message_id=f"msg_{request_index}",
        )

    anthropic_server.reply = reply
    trajectory = asyncio.run(
        ClaudeCode(
            {
                "llm": {
                    "model_name": "claude-sonnet-4-6",
                    "api_key": "local-claude-test-key",
                    "base_url": anthropic_server.base_url,
                },
                "tools": ["Agent"],
                "allowed_tools": ["Agent"],
                "timeout": 30,
            }
        ).run("Delegate evidence collection and synthesize the result")
    )

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Parent synthesis"
    parent_call = next(
        block
        for message in trajectory.messages
        if message["type"] == "AssistantMessage"
        for block in message["content"]
        if block["type"] == "ToolUseBlock" and block["name"] == "Agent"
    )
    child_messages = [
        message
        for message in trajectory.messages
        if message.get("parent_tool_use_id") == parent_call["id"]
    ]
    assert any(
        message["type"] == "AssistantMessage"
        and any(
            block["type"] == "TextBlock" and block["text"] == "NATIVE_CHILD_RESPONSE"
            for block in message["content"]
        )
        for message in child_messages
    )
    assert any(
        message["type"] == "TaskStartedMessage"
        and message["tool_use_id"] == parent_call["id"]
        for message in trajectory.messages
    )


def test_two_background_agents_finish_across_notification_turns(anthropic_server):
    """A second child can finish while the first notification is being answered."""

    def reply(request):
        body = request["body"]
        encoded = json.dumps(body["messages"])
        calls = [
            block
            for message in body["messages"]
            for block in message["content"]
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block["name"] == "Agent"
        ]
        tool = None
        if calls:
            if len(calls) == 1:
                text = ""
                tool = (
                    "Agent",
                    {
                        "subagent_type": "general-purpose",
                        "description": "Collect second source",
                        "prompt": "CHILD_TWO_REQUEST",
                        "run_in_background": True,
                    },
                )
            elif all(
                response in encoded
                for response in ("CHILD_ONE_RESPONSE", "CHILD_TWO_RESPONSE")
            ):
                text = "Full synthesis"
            else:
                text = "Waiting for all evidence"
                if "CHILD_ONE_RESPONSE" in encoded:
                    time.sleep(0.2)
        elif "CHILD_ONE_REQUEST" in encoded:
            time.sleep(0.05)
            text = "CHILD_ONE_RESPONSE"
        elif "CHILD_TWO_REQUEST" in encoded:
            time.sleep(0.1)
            text = "CHILD_TWO_RESPONSE"
        else:
            text = ""
            tool = (
                "Agent",
                {
                    "subagent_type": "general-purpose",
                    "description": "Collect first source",
                    "prompt": "CHILD_ONE_REQUEST",
                    "run_in_background": True,
                },
            )
        return _message_events(
            body,
            text,
            tool=tool,
            message_id=f"msg_{len(anthropic_server.requests)}",
        )

    anthropic_server.reply = reply
    trajectory = asyncio.run(
        ClaudeCode(
            {
                "llm": {
                    "model_name": "claude-sonnet-4-6",
                    "api_key": "local-claude-test-key",
                    "base_url": anthropic_server.base_url,
                },
                "tools": ["Agent"],
                "allowed_tools": ["Agent"],
                "timeout": 30,
            }
        ).run("Delegate two independent evidence tasks and synthesize both results")
    )

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Full synthesis"
    starts = [
        message
        for message in trajectory.messages
        if message["type"] == "TaskStartedMessage"
    ]
    notifications = [
        message
        for message in trajectory.messages
        if message["type"] == "TaskNotificationMessage"
    ]
    assert len(starts) == 2
    assert {message["task_id"] for message in notifications} == {
        message["task_id"] for message in starts
    }
    assert all(message["status"] == "completed" for message in notifications)
    results = [
        message for message in trajectory.messages if message["type"] == "ResultMessage"
    ]
    assert results[-1]["result"] == "Full synthesis"
    assert results[-1]["origin"] == {"kind": "task-notification"}
    assert trajectory.usage["input_tokens"] == sum(
        message["usage"]["input_tokens"] for message in results
    )
    # The CLI reports parent-turn usage separately from session-wide model
    # totals, which additionally include both child model requests.
    model_usage = trajectory.usage["model_usage"]["claude-sonnet-4-6"]
    assert model_usage["inputTokens"] == len(anthropic_server.requests) * 20
    assert model_usage["inputTokens"] == trajectory.usage["input_tokens"] + 40
    assert trajectory.usage["total_cost_usd"] == results[-1]["total_cost_usd"]


def test_custom_agent_candidate_controls_native_child(anthropic_server, tmp_path):
    source = _copy_source(tmp_path)
    definition = source / "agents/evidence.md"
    definition.parent.mkdir(exist_ok=True)
    definition.write_text(
        "---\nname: evidence\ndescription: Check the supplied evidence.\n"
        "tools: Read\n---\nBASELINE_AGENT_INSTRUCTION\n"
    )
    agent = ClaudeCode(
        _config(
            anthropic_server,
            source_dir=source,
            tools=["Agent", "Read"],
            allowed_tools=["Agent", "Read"],
        )
    )
    agent.set_scope({"agent": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        path = directory / "agents/evidence.md"
        path.write_text(path.read_text().replace("BASELINE", "CANDIDATE"))
        candidate = baseline.commit(directory)

    def reply(request):
        body = request["body"]
        system = json.dumps(body["system"])
        messages = json.dumps(body["messages"])
        tool = None
        if "CANDIDATE_AGENT_INSTRUCTION" in system:
            text = "candidate child answer"
        elif "BASELINE_AGENT_INSTRUCTION" in system:
            text = "baseline child answer"
        elif "candidate child answer" in messages:
            text = "candidate verified"
        elif "baseline child answer" in messages:
            text = "baseline verified"
        else:
            text = ""
            tool = (
                "Agent",
                {
                    "subagent_type": "flashrsi:evidence",
                    "description": "Check the supplied evidence",
                    "prompt": "Check this evidence",
                    "run_in_background": False,
                },
            )
        return _message_events(
            body, text, tool=tool, message_id=f"msg_{len(anthropic_server.requests)}"
        )

    anthropic_server.reply = reply
    (trial,) = asyncio.run(
        agent.rollout(
            [Task("candidate-agent", "Delegate the evidence check")], snapshot=candidate
        )
    )
    assert trial.status == "finished", trial.error_message
    assert trial.output == "candidate verified"
    assert agent.snapshot is baseline
    assert (
        asyncio.run(agent.run("Delegate the evidence check")).output
        == "baseline verified"
    )
    assert "CANDIDATE_AGENT_INSTRUCTION" not in definition.read_text()
