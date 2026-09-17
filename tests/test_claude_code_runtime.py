"""Native runtime state stays outside snapshots and supports child continuation."""

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from test_claude_code_native import _config, _message_events
from test_claude_code_native import anthropic_server as anthropic_server

from flashrsi.agents import ClaudeCode

sdk = pytest.importorskip(
    "claude_agent_sdk", reason="Native Claude integration needs the claude-code extra"
)


def test_run_ignores_old_auto_memory_and_cleans_private_runtime(
    anthropic_server, tmp_path, monkeypatch
):
    parent_config = Path(os.environ["CLAUDE_CONFIG_DIR"])
    working = tmp_path / "work"
    working.mkdir()
    memory = (
        parent_config
        / "projects"
        / sdk.project_key_for_directory(working.resolve())
        / "memory"
        / "MEMORY.md"
    )
    memory.parent.mkdir(parents=True)
    memory.write_text("PERSISTED_MEMORY_SHOULD_NOT_ENTER_THIS_RUN\n")
    # The fixture ordinarily disables memory. The product must do this itself,
    # even when the caller explicitly enabled its personal Claude installation.
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")
    monkeypatch.setenv("CLAUDE_CODE_SKIP_PROMPT_HISTORY", "1")
    clients = []
    original = sdk.ClaudeSDKClient

    def client(*, options):
        clients.append(options)
        return original(options=options)

    monkeypatch.setattr(sdk, "ClaudeSDKClient", client)
    agent = ClaudeCode(_config(anthropic_server, tools=[]))
    for _ in range(2):
        trajectory = asyncio.run(agent.run("Answer directly", working_dir=working))
        assert trajectory.status == "finished", trajectory.error_message

    assert "PERSISTED_MEMORY_SHOULD_NOT_ENTER_THIS_RUN" not in json.dumps(
        anthropic_server.requests
    )
    assert len({item.env["CLAUDE_CONFIG_DIR"] for item in clients}) == 2
    for item in clients:
        assert Path(item.env["CLAUDE_CONFIG_DIR"]) != parent_config
        assert not Path(item.env["CLAUDE_CONFIG_DIR"]).exists()
        assert item.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert item.env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] == ""
        assert not Path(item.env["CLAUDE_CODE_TMPDIR"]).exists()
    assert memory.read_text() == "PERSISTED_MEMORY_SHOULD_NOT_ENTER_THIS_RUN\n"
    assert list(parent_config.rglob("*.jsonl")) == []


@pytest.mark.parametrize("credential_source", ["config_dir", "secure_storage"])
def test_private_runtime_preserves_native_credential_location(
    anthropic_server, tmp_path, monkeypatch, credential_source
):
    credentials = tmp_path / "native-auth"
    credentials.mkdir()
    (credentials / ".credentials.json").write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "FAKE_LOCAL_OAUTH_TEST_TOKEN",
                    "expiresAt": int((time.time() + 3600) * 1000),
                    "scopes": ["user:inference", "user:profile"],
                    "subscriptionType": "max",
                }
            }
        )
    )
    if credential_source == "secure_storage":
        monkeypatch.setenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", str(credentials))
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(credentials))
        monkeypatch.delenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", raising=False)
    original = sdk.ClaudeSDKClient
    statuses = []

    def client(*, options):
        # auth status resolves credentials locally; it makes no model call and
        # does not need to authenticate the deliberately fake OAuth token.
        environment = {**os.environ, **options.env}
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
        ):
            environment.pop(key, None)
        cli = Path(sdk.__file__).parent / "_bundled" / "claude"
        checked = subprocess.run(
            [str(cli), "auth", "status", "--json"],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        statuses.append(json.loads(checked.stdout))
        return original(options=options)

    monkeypatch.setattr(sdk, "ClaudeSDKClient", client)
    trajectory = asyncio.run(
        ClaudeCode(_config(anthropic_server, tools=[])).run("Answer directly")
    )
    assert trajectory.status == "finished", trajectory.error_message
    assert statuses[0]["loggedIn"] is True
    assert statuses[0]["authMethod"] == "claude.ai"
    assert Path(statuses[0]["configDirectory"]) != credentials


def test_child_can_be_continued_with_send_message_in_the_same_run(
    anthropic_server, monkeypatch
):
    clients = []
    original = sdk.ClaudeSDKClient

    def client(*, options):
        clients.append(options)
        return original(options=options)

    monkeypatch.setattr(sdk, "ClaudeSDKClient", client)

    def reply(request):
        body = request["body"]
        encoded = json.dumps(body["messages"])
        calls = [
            block
            for message in body["messages"]
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        if "ROOT_CONTINUE_CHILD" in encoded:
            if not calls:
                return _message_events(
                    body,
                    tool=(
                        "Agent",
                        {
                            "description": "Read first evidence",
                            "prompt": "CHILD_ROUND_ONE",
                            "subagent_type": "general-purpose",
                            "run_in_background": False,
                        },
                    ),
                    message_id="msg_delegate",
                )
            if not any(call["name"] == "SendMessage" for call in calls):
                (child_id,) = re.findall(r"agentId: ([a-z0-9]+)", encoded)
                # The native CLI publishes foreground transcripts asynchronously.
                # A zero-latency mock can race that flush even with persistence
                # enabled; wait for publication before emulating the next reply.
                state = Path(clients[0].env["CLAUDE_CONFIG_DIR"])
                deadline = time.monotonic() + 5
                while not any(state.rglob(f"agent-{child_id}.jsonl")):
                    assert time.monotonic() < deadline, "child transcript not saved"
                    time.sleep(0.01)
                return _message_events(
                    body,
                    tool=(
                        "SendMessage",
                        {
                            "to": child_id,
                            "message": "CHILD_ROUND_TWO",
                            "summary": "Check the second piece of evidence",
                        },
                    ),
                    message_id="msg_resume",
                )
            return _message_events(
                body,
                "FINAL_WITH_SECOND_EVIDENCE"
                if "CHILD_TWO_DONE" in encoded
                else "Waiting for second evidence",
                message_id=f"msg_root_{len(anthropic_server.requests)}",
            )
        if "CHILD_ROUND_TWO" in encoded:
            # Ensure the first parent Result precedes the resumed child's end.
            time.sleep(0.8)
            assert "CHILD_ONE_DONE" in encoded
            return _message_events(body, "CHILD_TWO_DONE", message_id="msg_child_two")
        return _message_events(body, "CHILD_ONE_DONE", message_id="msg_child_one")

    anthropic_server.reply = reply
    trajectory = asyncio.run(
        ClaudeCode(
            _config(
                anthropic_server,
                tools=["Agent", "SendMessage"],
                allowed_tools=["Agent", "SendMessage"],
                max_turns=7,
            )
        ).run("ROOT_CONTINUE_CHILD: Delegate, then continue that child")
    )
    trace = json.dumps([dict(message) for message in trajectory.messages])
    assert trajectory.status == "finished", trajectory.error_message
    assert "No transcript found" not in trace
    assert "CHILD_TWO_DONE" in trace
    assert trajectory.output == "FINAL_WITH_SECOND_EVIDENCE"
    assert any(
        "CHILD_TWO_DONE" in json.dumps(dict(message))
        and message.get("parent_tool_use_id")
        for message in trajectory.messages
    )
    output_files = [
        Path(message["output_file"])
        for message in trajectory.messages
        if message["type"] == "TaskNotificationMessage"
    ]
    assert output_files
    assert all(
        path.is_relative_to(clients[0].env["CLAUDE_CODE_TMPDIR"]) and not path.exists()
        for path in output_files
    )
