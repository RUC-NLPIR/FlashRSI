import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.chat_transport import (
    chat_headers,
    ingest_chat,
    prepare_chat,
    validate_chat_route,
)

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_chat_upstream.json").read_text()
)


@pytest.mark.parametrize(
    "provider", ["copilot-acp", "anthropic", "bedrock", "solstice"]
)
def test_unported_registered_profiles_fail_explicitly(provider):
    with pytest.raises(ValueError, match="not implemented"):
        validate_chat_route({"provider": provider})


def test_snapshot_routing_reaches_original_profile_wire_body():
    result = prepare_chat(
        {"model": "qwen/qwen3", "messages": [{"role": "user", "content": "task"}]},
        {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
        {"provider_routing": {"only": ["provider-a"], "sort": "latency"}},
    )
    assert result["extra_body"]["provider"] == {
        "only": ["provider-a"],
        "sort": "latency",
    }


def test_custom_defaults_and_role_extra_body_reach_wire_with_explicit_precedence():
    result = prepare_chat(
        {"model": "model", "messages": [{"role": "user", "content": "task"}]},
        {
            "provider": "custom",
            "base_url": "https://proxy.example/v1",
            "extra_body": {"route": 2, "shared": "role"},
            "request_overrides": {"extra_body": {"shared": "request"}},
        },
        {
            "custom_providers": [
                {
                    "base_url": "https://proxy.example/v1/",
                    "extra_body": {"default": 1, "shared": "default"},
                }
            ],
        },
    )
    assert result["extra_body"] == {"default": 1, "route": 2, "shared": "request"}


@pytest.mark.parametrize(
    "case", REFERENCE["headers"], ids=lambda case: case["provider"]
)
def test_original_profile_client_headers(case):
    assert chat_headers({"provider": case["provider"]}) == case["expected"]


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["name"])
def test_request_matches_original_transport_and_real_profile(case):
    original = copy.deepcopy(case["payload"])
    actual = prepare_chat(case["payload"], case["route"], case["settings"])
    assert actual == case["expected"]
    assert case["payload"] == original


@pytest.mark.parametrize("case", REFERENCE["responses"], ids=lambda case: case["name"])
def test_response_matches_actual_original_normalization(case):
    if not case["valid"]:
        with pytest.raises(ValueError, match="router timeout"):
            ingest_chat(case["input"], case["aliases"])
        return
    actual = ingest_chat(case["input"], case["aliases"])
    choice = actual["choices"][0]
    message = choice["message"]
    expected = case["normalized"]
    assert choice["finish_reason"] == expected["finish_reason"]
    assert message["content"] == expected["content"]
    assert message.get("reasoning") == expected["reasoning"]
    for name, value in (expected["provider_data"] or {}).items():
        assert message[name] == value
    for actual_call, expected_call in zip(
        message.get("tool_calls") or [], expected["tool_calls"] or [], strict=True
    ):
        assert actual_call["id"] == expected_call["id"]
        assert actual_call["function"]["name"] == expected_call["name"]
        assert actual_call["function"]["arguments"] == expected_call["arguments"]
        for name, value in (expected_call["provider_data"] or {}).items():
            if name == "thought_signature":
                assert actual_call["function"][name] == value
            else:
                assert actual_call[name] == value
    if case["cache"]:
        details = actual["usage"]["prompt_tokens_details"]
        assert details["cached_tokens"] == case["cache"]["cached_tokens"]
        assert details["cache_write_tokens"] == case["cache"]["creation_tokens"]
