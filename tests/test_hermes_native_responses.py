"""Offline parity against actual pinned Hermes native Responses executions."""

import asyncio
import base64
import copy
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from flashrsi.agents.hermes.runtime.hermes_native import native_compaction as policy
from flashrsi.agents.hermes.runtime.hermes_native import native_responses as bridge
from flashrsi.agents.hermes.runtime.hermes_native.compression import ContextEngine
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction import (
    responses_adapter as adapter,
)
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction.responses_auxiliary import (
    AuxiliaryResponsesTransport,
)
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction.responses_transport import (
    ResponsesApiTransport,
)
from flashrsi.agents.hermes.runtime.hermes_native.upstream_compaction.responses_usage import (
    normalize_usage,
)

ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures/hermes_native_compaction_upstream.json"
    ).read_text()
)
AUX_ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures/hermes_auxiliary_responses_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize("case", ORACLE["functions"], ids=lambda case: case["label"])
def test_native_policy_matches_actual_upstream(case):
    assert (
        getattr(policy, case["name"])(
            *copy.deepcopy(case["args"]), **copy.deepcopy(case["kwargs"])
        )
        == case["result"]
    )


@pytest.mark.parametrize(
    "case", ORACLE["context_management"], ids=lambda case: case["name"]
)
def test_context_management_matches_actual_upstream(case):
    fields = copy.deepcopy(case["agent"])
    if isinstance(fields.get("context_compressor"), dict):
        fields["context_compressor"] = SimpleNamespace(**fields["context_compressor"])
    assert (
        policy.native_compaction_context_management(
            SimpleNamespace(**fields), **case["route"]
        )
        == case["result"]
    )


@pytest.mark.parametrize(
    "case", ORACLE["responses_input"], ids=lambda case: case["name"]
)
def test_checkpoint_wire_conversion_matches_actual_upstream(case):
    original = copy.deepcopy(case["messages"])
    assert (
        adapter._chat_messages_to_responses_input(original, **case["kwargs"])
        == case["result"]
    )
    assert original == case["messages"]


@pytest.mark.parametrize("case", ORACLE["capture"], ids=lambda case: case["name"])
def test_checkpoint_capture_matches_actual_upstream(case):
    assert (
        adapter._capture_encrypted_item(
            bridge._objects(case["item"]),
            case["item"]["type"],
            case["issuer_kind"],
            case["issuer_model"],
        )
        == case["result"]
    )


@pytest.mark.parametrize("case", ORACLE["usage"], ids=lambda case: case["name"])
def test_responses_usage_matches_actual_upstream(case):
    result = normalize_usage(case["usage"], **case["kwargs"])
    assert {
        **asdict(result),
        "prompt_tokens": result.prompt_tokens,
        "total_tokens": result.total_tokens,
    } == case["result"]


@pytest.mark.parametrize("case", ORACLE["request_build"], ids=lambda case: case["name"])
def test_responses_request_builder_matches_actual_upstream(case):
    transport = ResponsesApiTransport()
    result = transport.build_kwargs(
        case["model"],
        copy.deepcopy(case["messages"]),
        copy.deepcopy(case["tools"]),
        **copy.deepcopy(case["params"]),
    )
    assert result == case["result"]
    assert adapter._preflight_codex_api_kwargs(result) == case["preflight"]
    assert {key: getattr(transport, key) for key in case["transport_state"]} == case[
        "transport_state"
    ]


@pytest.mark.parametrize("case", ORACLE["normalize"], ids=lambda case: case["name"])
def test_responses_normalization_matches_actual_upstream(case):
    message, finish = adapter._normalize_codex_response(
        bridge._objects(case["response"]), **case["kwargs"]
    )
    assert {"message": bridge._plain(message), "finish_reason": finish} == case[
        "result"
    ]


def _engine(*, native=True, **compression):
    route = {
        "model_name": "gpt-5.6",
        "model_api": "responses",
        "base_url": "https://api.openai.com/v1",
        "provider": "openai",
    }
    engine = ContextEngine(
        {
            "context_length": 200000,
            "compression": {"codex_responses_native": native, **compression},
        },
        route,
    )
    return engine, route


def _response(*, checkpoint=True):
    output = (
        [{"type": "compaction", "encrypted_content": "opaque-checkpoint"}]
        if checkpoint
        else []
    )
    output.append(
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "done"}],
        }
    )
    return {
        "status": "completed",
        "output": output,
        "usage": {
            "input_tokens": 120000,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 40000},
        },
    }


def test_http_boundary_native_threshold_capture_and_usage_latch():
    engine, route = _engine()
    messages = [{"role": "user", "content": "ask"}]
    endpoint, request = bridge.prepare(
        {"model": "gpt-5.6", "messages": messages, "stream": False}, route, engine
    )
    assert endpoint == "https://api.openai.com/v1/responses"
    assert request["context_management"] == [
        {
            "type": "compaction",
            "compact_threshold": engine.compressor.threshold_tokens - 8192,
        }
    ]
    result = bridge.ingest(_response(), route, engine)
    assert result["usage"]["input_tokens"] == 80000
    assert result["usage"]["prompt_tokens"] == 120000
    engine.after_response(result["usage"], messages)
    assert engine._anchor is None
    assert engine.compressor.awaiting_real_usage_after_compression
    assert engine.compressor.last_compression_rough_tokens == 0
    assistant = {"role": "assistant", **result["choices"][0]["message"]}
    assert bridge.has_replayable_checkpoint(engine, [assistant])
    engine.after_response(
        bridge.ingest(_response(checkpoint=False), route, engine)["usage"],
        messages + [assistant],
    )
    assert engine._anchor is not None
    assert not engine.compressor.awaiting_real_usage_after_compression


def test_summary_disables_checkpoint_replay_and_native_directive():
    engine, route = _engine()
    messages = [
        {"role": "user", "content": "original"},
        {"role": "assistant", "content": "before"},
        {
            "role": "assistant",
            "content": "checkpoint",
            "codex_reasoning_items": [
                {"type": "compaction", "encrypted_content": "opaque"}
            ],
        },
    ]
    _, result = bridge.prepare(
        {
            "model": "gpt-5.6",
            "messages": messages,
            "max_tokens": 123,
            "temperature": 0.1,
        },
        route,
        engine,
        summary=True,
    )
    assert "context_management" not in result
    assert not any(item["type"] == "compaction" for item in result["input"])
    assert any(item.get("content") == "before" for item in result["input"])
    assert "max_output_tokens" not in result
    assert "temperature" not in result
    assert "reasoning" not in result
    assert "include" not in result


def test_native_rejection_disables_only_native_once_and_restores_state():
    engine, route = _engine()
    error = RuntimeError("unknown field context_management")
    assert asyncio.run(engine.recover(error, [], "", None)).retry
    assert bridge.context_management(engine, route) is None
    assert engine.enabled
    assert not asyncio.run(engine.recover(error, [], "", None)).retry
    restored, _ = _engine()
    restored.restore_state(engine.snapshot_state())
    assert bridge.context_management(restored, route) is None


def test_disabled_native_does_not_replay_or_prune_persisted_history():
    engine, route = _engine(native=False)
    messages = [
        {"role": "user", "content": "ask"},
        {"role": "assistant", "content": "before"},
        {
            "role": "assistant",
            "content": "checkpoint",
            "codex_reasoning_items": [
                {"type": "compaction", "encrypted_content": "opaque"}
            ],
        },
    ]
    before = copy.deepcopy(messages)
    _, request = bridge.prepare(
        {"model": "gpt-5.6", "messages": messages}, route, engine
    )
    assert "context_management" not in request
    assert any(item.get("content") == "before" for item in request["input"])
    assert not any(item.get("type") == "compaction" for item in request["input"])
    assert messages == before


def test_official_codex_uses_typed_parts_sse_and_no_output_cap():
    engine, _ = _engine()
    route = {
        "provider": "openai-codex",
        "model": "gpt-5.6",
        "model_api": "codex_responses",
        "base_url": "https://chatgpt.com/backend-api/codex",
    }
    _, request = bridge.prepare(
        {
            "model": "gpt-5.6",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 123,
        },
        route,
        engine,
    )
    assert request["stream"] is True
    assert request["input"][0]["content"] == [{"type": "input_text", "text": "hi"}]
    assert "max_output_tokens" not in request
    raw = _response()
    event = (
        "event: response.completed\ndata: "
        + json.dumps({"type": "response.completed", "response": raw})
        + "\n\n"
    )
    assert bridge.decode_response(event) == raw
    with pytest.raises(RuntimeError, match="ended"):
        bridge.decode_response("data: [DONE]\n\n")


@pytest.mark.parametrize("attempts,expected", [(0, 3), (-1, 3), (999, 10), (2, 2)])
def test_max_attempts_matches_upstream_invalid_fallback(attempts, expected):
    assert _engine(max_attempts=attempts)[0].max_attempts == expected


def test_explicit_auxiliary_protocol_overrides_main_model_api():
    engine, _ = _engine()
    engine._aux_config = {
        "api_mode": "chat_completions",
        "base_url": "https://aux.example/v1",
    }
    route = engine._summary_route({"messages": []})
    assert route["api_mode"] == "chat_completions"
    assert "model_api" not in route
    engine._aux_config = {"base_url": "https://aux.example/v1"}
    assert engine._summary_route({"messages": []})["api_mode"] == "chat_completions"


def test_summary_ingest_never_arms_native_checkpoint_latch():
    engine, route = _engine()
    bridge.ingest(_response(), route, engine, summary=True)
    assert not engine._native_checkpoint_pending
    assert not engine.compressor.awaiting_real_usage_after_compression


def test_captured_blob_is_stamped_with_requested_wire_model():
    engine, route = _engine()
    bridge.prepare(
        {"model": "gpt-5.6", "messages": [{"role": "user", "content": "hi"}]},
        route,
        engine,
    )
    result = bridge.ingest(
        {**_response(), "model": "gpt-5.6-2026-10-01"}, route, engine
    )
    assert (
        result["choices"][0]["message"]["codex_reasoning_items"][0]["_issuer_model"]
        == "gpt-5.6"
    )


def test_explicit_codex_token_supplies_original_account_headers():
    token = (
        "header."
        + base64.urlsafe_b64encode(
            json.dumps(
                {
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "account-test",
                        "chatgpt_data_residency": "eu",
                    }
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
        + ".signature"
    )
    headers = bridge.request_headers(
        {
            "api_key": token,
            "provider": "openai-codex",
            "base_url": "https://chatgpt.com/backend-api/codex",
        }
    )
    assert headers["User-Agent"] == "HermesAgent/0.22.5"
    assert headers["originator"] == "hermes-agent"
    assert headers["ChatGPT-Account-ID"] == "account-test"
    assert headers["x-openai-internal-codex-residency"] == "eu"


def test_unexplained_local_context_rejection_does_not_destroy_small_history():
    route = {"model": "gpt-5.6", "base_url": "http://localhost/v1"}
    engine = ContextEngine({"context_length": 200000}, route)
    messages = [{"role": "user", "content": "small ask"}]
    result = asyncio.run(
        engine.recover(RuntimeError("prompt is too long"), messages, "", None)
    )
    assert not result.retry
    assert result.reason == "unexplained_local_context_rejection"
    assert messages == [{"role": "user", "content": "small ask"}]
    assert engine.attempts == 0


@pytest.mark.parametrize("reason", ["max_output_tokens", "length"])
def test_provider_output_exhaustion_retries_complete_looking_tool_calls(reason):
    engine, route = _engine()
    response = {
        "status": "incomplete",
        "incomplete_details": {"reason": reason},
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": '{"path":"a.py"}',
            }
        ],
    }
    result = bridge.ingest(response, route, engine)
    assert result["choices"][0]["finish_reason"] == "length"
    assert result["responses_status"] == "incomplete"
    assert result["responses_incomplete_reason"] == reason
    response["output"] = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "partial"}],
        }
    ]
    assert (
        bridge.ingest(response, route, engine)["choices"][0]["finish_reason"]
        == "incomplete"
    )


def test_responses_content_filter_preserves_provider_stop_reason():
    engine, route = _engine()
    result = bridge.ingest(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "content_filter"},
            "output": [],
        },
        route,
        engine,
    )
    assert result["choices"][0]["finish_reason"] == "content_filter"


@pytest.mark.parametrize(
    "reason", ["max_output_tokens", "content_filter", "length", "other"]
)
def test_auxiliary_incomplete_response_is_rejected_as_partial_summary(reason):
    engine, route = _engine()
    response = {
        **_response(checkpoint=False),
        "status": "incomplete",
        "incomplete_details": {"reason": reason},
    }
    result = bridge.ingest(response, route, engine, summary=True)
    assert result["choices"][0]["finish_reason"] == "length"
    assert result["choices"][0]["message"]["content"] == "done"
    assert not engine._native_checkpoint_pending


def test_auxiliary_empty_completed_result_is_preserved_for_empty_content_gate():
    engine, route = _engine()
    result = bridge.ingest(
        {"status": "completed", "output": []}, route, engine, summary=True
    )
    assert result["choices"][0]["message"]["content"] == ""
    assert result["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("case", AUX_ORACLE["build"], ids=lambda case: case["name"])
def test_auxiliary_request_matches_actual_upstream(case):
    transport = AuxiliaryResponsesTransport("gpt-5.6", case["base_url"], "")
    result, model, timeout = transport._build_responses_kwargs(
        copy.deepcopy(case["payload"])
    )
    assert result == case["result"]
    assert model == case["model"]
    assert timeout == case["timeout"]
    route = {
        "base_url": case["base_url"],
        "model_api": "responses",
        "extra_body": case["payload"].get("extra_body"),
    }
    _, body = bridge.prepare(case["payload"], route, summary=True)
    expected = {key: value for key, value in result.items() if not key.startswith("_")}
    expected = adapter._preflight_codex_api_kwargs(expected)
    if "chatgpt.com" in case["base_url"]:
        expected["stream"] = True
    assert body == expected


@pytest.mark.parametrize("case", AUX_ORACLE["normalize"], ids=lambda case: case["name"])
def test_auxiliary_response_matches_actual_upstream(case):
    result = bridge.ingest(
        case["response"],
        {
            "model_api": "responses",
            "model": "gpt-5.6",
            "base_url": "https://api.openai.com/v1",
        },
        summary=True,
    )
    message = result["choices"][0]["message"]
    assert ([message["content"]] if message["content"] else []) == case["result"][0]
    assert message["tool_calls"] == case["result"][1]
    assert result["choices"][0]["finish_reason"] == case["result"][3]
