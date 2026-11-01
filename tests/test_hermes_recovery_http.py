"""Exercise recovery at the real HTTP serializer and persisted session boundary."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from flashrsi.agents.hermes.runtime.hermes_native import loop
from flashrsi.agents.hermes.runtime.hermes_native.recovery import RecoveryHost


def _configure(monkeypatch, respond):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: client(
            *args, **kwargs, transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    monkeypatch.setattr(
        loop,
        "load_resources",
        lambda *args: SimpleNamespace(
            system_prompt="你是 helpful.", enabled_tools=["read_file"], diagnostics=[]
        ),
    )


def _run(tmp_path, llm, prompt="处理 café 中文", **options):
    return asyncio.run(
        loop.run(
            {
                "llm": {
                    "provider": "custom",
                    "model_name": "model-a",
                    "base_url": "https://fixture.invalid/v1",
                    "api_key": "fixed-key",
                    **llm,
                },
                "compression": {"enabled": False},
                "max_iterations": 3,
                **options,
            },
            prompt,
            tmp_path,
            Path(loop.__file__).parents[1],
        )
    )


def _chat(text):
    return {
        "choices": [
            {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }


def test_real_http_header_encoding_repair_preserves_unicode(monkeypatch, tmp_path):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=_chat("已完成"))

    _configure(monkeypatch, respond)
    result = _run(
        tmp_path, {"api_key": "fixed—key", "extra_headers": {"x-fixture": "résumé"}}
    )
    assert result.output == "已完成"
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer fixedkey"
    assert requests[0].headers["x-fixture"] == "rsum"
    payload = json.loads(requests[0].content)
    assert payload["messages"][0]["content"] == "你是 helpful."
    assert payload["messages"][-1]["content"] == "处理 café 中文"
    assert any("non-ASCII" in event.get("message", "") for event in result.events)


def test_anthropic_signature_suppression_survives_session_resume(monkeypatch, tmp_path):
    signature = {
        "type": "thinking",
        "thinking": "Earlier thought.",
        "signature": "fixed-stale-signature",
    }
    durable = [
        {"role": "user", "content": "Earlier question."},
        {
            "role": "assistant",
            "content": "Earlier answer.",
            "reasoning": "Earlier thought.",
            "reasoning_details": [signature],
        },
    ]
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"format": "hermes-native-v1", "messages": durable}))
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                400, json={"error": {"message": "Invalid signature in thinking block"}}
            )
        return httpx.Response(
            200,
            json={
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    _configure(monkeypatch, respond)
    route = {
        "provider": "anthropic",
        "model_api": "anthropic_messages",
        "model_name": "claude-opus-4-6",
        "base_url": "https://api.anthropic.com",
        "api_key": "sk-ant-api-fixture",
        "stream": False,
    }
    result = _run(tmp_path, route, session_file="state.json")
    assert result.status == "finished"
    assert "fixed-stale-signature" in json.dumps(requests[0])
    assert "fixed-stale-signature" not in json.dumps(requests[1])
    saved = json.loads(state.read_text())
    assert saved["messages"][1]["reasoning_details"] == [signature]
    assert saved["context_state"]["recovery"]["anthropic_rejected_thinking"]
    resumed = _run(tmp_path, route, prompt="Next turn.", session_file="state.json")
    assert resumed.status == "finished"
    assert "fixed-stale-signature" not in json.dumps(requests[2])


def test_multimodal_tool_envelope_is_native_content(monkeypatch, tmp_path):
    envelope = {
        "_multimodal": True,
        "content": [
            {"type": "text", "text": "Screenshot"},
            {
                "type": "image_url",
                "image_url": {"url": "https://fixture.invalid/image.png"},
            },
        ],
        "text_summary": "Screenshot summary",
    }

    class Tools:
        cwd = tmp_path

        def execute(self, *args):
            return copy.deepcopy(envelope)

    engine = SimpleNamespace(
        settings={},
        config={},
        _native_disabled=False,
        _anchor=None,
        compressor=SimpleNamespace(),
    )
    host = RecoveryHost(
        {
            "provider": "custom",
            "model_name": "model-a",
            "model_api": "chat_completions",
            "base_url": "https://fixture.invalid/v1",
            "supports_vision": True,
        },
        engine,
        lambda event: None,
    )
    call = SimpleNamespace(
        id="shot",
        function=SimpleNamespace(name="read_file", arguments='{"path":"shot.png"}'),
    )
    messages = []
    asyncio.run(
        loop._execute_batch([call], Tools(), tmp_path, [], messages.append, host)
    )
    assert messages[0]["content"] == envelope["content"]
    host._no_list_tool_content_models.add(("custom", "model-a"))
    messages = []
    asyncio.run(
        loop._execute_batch([call], Tools(), tmp_path, [], messages.append, host)
    )
    assert messages[0]["content"] == "Screenshot summary"


def test_responses_repeated_own_blob_rejection_disables_replay_and_persists(
    monkeypatch, tmp_path
):
    own = {
        "type": "reasoning",
        "id": "rs_old",
        "encrypted_content": "old-owned-blob",
        "_issuer_kind": "other:https://api.openai.com/v1",
        "_issuer_model": "gpt-5.4",
    }
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "format": "hermes-native-v1",
                "messages": [
                    {"role": "user", "content": "Earlier question."},
                    {
                        "role": "assistant",
                        "content": "Earlier answer.",
                        "codex_reasoning_items": [own],
                    },
                ],
            }
        )
    )
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) in (1, 3):
            return httpx.Response(
                400, json={"error": {"message": "invalid_encrypted_content"}}
            )
        output = [
            {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Done."}],
            }
        ]
        if len(requests) == 2:
            output.insert(
                0,
                {
                    "type": "reasoning",
                    "id": "rs_new",
                    "encrypted_content": "new-owned-blob",
                    "summary": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "status": "completed",
                "output": output,
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    _configure(monkeypatch, respond)
    route = {
        "provider": "openai",
        "model_api": "responses",
        "model_name": "gpt-5.4",
        "base_url": "https://api.openai.com/v1",
    }
    first = _run(tmp_path, route, session_file="state.json")
    assert first.status == "finished"
    assert "old-owned-blob" in json.dumps(requests[0])
    assert "old-owned-blob" not in json.dumps(requests[1])
    second = _run(tmp_path, route, prompt="Next turn.", session_file="state.json")
    assert second.status == "finished"
    assert "new-owned-blob" in json.dumps(requests[2])
    assert "new-owned-blob" not in json.dumps(requests[3])
    saved = json.loads(state.read_text())
    flags = saved["context_state"]["recovery"]["routes"][0][3]
    assert flags["_codex_reasoning_replay_enabled"] is False
    third = _run(tmp_path, route, prompt="Another turn.", session_file="state.json")
    assert third.status == "finished"
    assert not any(item.get("type") == "reasoning" for item in requests[4]["input"])
