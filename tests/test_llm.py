import asyncio
from types import SimpleNamespace

import pytest

from flashrsi.agents import LLM


@pytest.mark.parametrize("role", [None, "llm", "agent"])
def test_llm_role_is_text_even_when_metadata_is_missing_or_inconsistent(role):
    config = {"llm": {"model_name": "worker"}}
    if role is not None:
        config["type"] = role
    worker = LLM(config)
    assert worker.config.type == "llm"
    assert config.get("type") == role


@pytest.fixture
def client(monkeypatch):
    openai = pytest.importorskip("openai")
    state = SimpleNamespace(
        init=None,
        request=None,
        closed=False,
        failure=None,
        content="answer",
        reason="stop",
    )

    class Client:
        def __init__(self, **kwargs):
            state.init = kwargs
            self.chat = SimpleNamespace(completions=self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state.closed = True

        async def create(self, **kwargs):
            state.request = kwargs
            if state.failure:
                raise state.failure
            return openai.types.chat.ChatCompletion(
                id="test",
                object="chat.completion",
                created=0,
                model="offline",
                choices=[
                    {
                        "index": 0,
                        "finish_reason": state.reason,
                        "message": {"role": "assistant", "content": state.content},
                    }
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            )

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    return state


def test_llm_parameters_usage_and_credentials(client):
    config = {
        "llm": {
            "model_name": "worker",
            "api_key": "private-worker-key",
            "base_url": "https://worker.test/v1",
            "temperature": 0.4,
            "extra_body": {"custom": True},
        },
        "timeout": 7,
        "max_retries": 2,
    }
    worker = LLM(config)
    config["llm"]["model_name"] = "mutated"
    client.content = "answer private-worker-key"
    result = asyncio.run(worker.run("prompt private-worker-key"))
    assert client.request["model"] == "worker"
    assert client.request["temperature"] == 0.4
    assert client.request["extra_body"] == {"custom": True}
    assert client.init == {
        "api_key": "private-worker-key",
        "base_url": "https://worker.test/v1",
        "timeout": 7,
        "max_retries": 2,
    }
    assert result.output == "answer [REDACTED]"
    assert "private-worker-key" not in str(result)
    assert result.usage["total_tokens"] == 12
    assert result.messages[0]["snapshot_id"] is None
    assert client.closed


def test_requires_explicit_config_even_with_ambient_credentials(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    worker = LLM({"llm": {"model_name": "worker"}})
    result = asyncio.run(worker.run("hello"))
    assert client.init is None
    assert result.status == "error"
    assert "llm.api_key" in result.error_message


def test_default_endpoint_ignores_environment_and_errors_are_redacted(
    client, monkeypatch
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.test")
    worker = LLM({"llm": {"model_name": "worker", "api_key": "explicit-key"}})
    client.failure = RuntimeError("failed explicit-key")
    result = asyncio.run(worker.run("hello"))
    assert client.init["base_url"] == "https://api.openai.com/v1"
    assert result.error_message == "failed [REDACTED]"
    assert client.closed


@pytest.mark.parametrize(
    "content,reason", [("", "stop"), ("partial", "length"), (None, "tool_calls")]
)
def test_empty_and_incomplete_response_is_not_success(client, content, reason):
    client.content, client.reason = content, reason
    result = asyncio.run(
        LLM({"llm": {"model_name": "worker", "api_key": "test-key"}}).run("hello")
    )
    assert result.status == "error"
    assert result.usage["total_tokens"] == 12


def test_cancellation_propagates_and_closes_client(client):
    client.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            LLM({"llm": {"model_name": "worker", "api_key": "test-key"}}).run("hello")
        )
    assert client.closed


def test_llm_does_not_claim_file_editing(client, tmp_path):
    with pytest.raises(NotImplementedError, match="generates text"):
        asyncio.run(
            LLM({"llm": {"model_name": "worker"}}).run("edit", working_dir=tmp_path)
        )
    assert client.request is None
