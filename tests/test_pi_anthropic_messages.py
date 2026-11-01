"""Anthropic replay cases from the pinned Pi provider and transform sources."""

import copy

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.anthropic_messages import (
    _anthropic_context_messages,
)


def text(value):
    return {"type": "text", "text": value}


def assistant(content, **extra):
    return {
        "role": "assistant",
        "api": "anthropic-messages",
        "provider": "anthropic",
        "model": "claude-fixture",
        "stopReason": "stop",
        "content": content,
        **extra,
    }


def convert(messages, **options):
    return _anthropic_context_messages(
        messages, "anthropic", "claude-fixture", **options
    )


def call(call_id="call", name="read"):
    return {"type": "toolCall", "id": call_id, "name": name, "arguments": {"path": "x"}}


def tool_result(call_id="call", content=None, **extra):
    return {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": "read",
        "content": [text("read result")] if content is None else content,
        "isError": False,
        **extra,
    }


def test_signed_and_redacted_thinking_replay_without_mutating_session():
    messages = [
        {"role": "system", "content": "already merged by caller"},
        {"role": "user", "content": "question"},
        assistant(
            [
                {
                    "type": "thinking",
                    "thinking": "reason",
                    "thinkingSignature": "signed",
                },
                {
                    "type": "thinking",
                    "thinking": "",
                    "thinkingSignature": "opaque",
                    "redacted": True,
                },
                text("answer"),
            ]
        ),
    ]
    original = copy.deepcopy(messages)
    assert convert(messages) == [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "reason", "signature": "signed"},
                {"type": "redacted_thinking", "data": "opaque"},
                text("answer"),
            ],
        },
    ]
    assert messages == original


@pytest.mark.parametrize("signature", [None, "", "  "])
@pytest.mark.parametrize("allow_empty", [False, True])
def test_unsigned_same_model_thinking_follows_compatibility_option(
    signature, allow_empty
):
    message = assistant(
        [
            {"type": "thinking", "thinking": "reason", "thinkingSignature": signature},
            {"type": "thinking", "thinking": " ", "thinkingSignature": signature},
        ]
    )
    expected = (
        {"type": "thinking", "thinking": "reason", "signature": ""}
        if allow_empty
        else text("reason")
    )
    assert convert([message], allow_empty_signature=allow_empty) == [
        {"role": "assistant", "content": [expected]}
    ]


@pytest.mark.parametrize(
    "changed",
    [{"provider": "another"}, {"api": "openai-responses"}, {"model": "other-model"}],
)
def test_cross_model_thinking_is_dropped_including_encrypted_signatures(changed):
    message = assistant(
        [
            {"type": "thinking", "thinking": "private", "thinkingSignature": "signed"},
            {
                "type": "thinking",
                "thinking": "",
                "thinkingSignature": "encrypted",
                "redacted": True,
            },
            {"type": "text", "text": "visible", "textSignature": "also-private"},
        ],
        **changed,
    )
    assert convert([message]) == [{"role": "assistant", "content": [text("visible")]}]


@pytest.mark.parametrize("reason", ["error", "aborted"])
def test_failed_assistant_cannot_replay_partial_content_or_tool_calls(reason):
    assert convert(
        [
            assistant([text("partial"), call("do-not-replay")], stopReason=reason),
            {"role": "user", "content": "try again"},
        ]
    ) == [{"role": "user", "content": "try again"}]


def test_managed_effort_records_history_and_restores_current_level():
    messages = [
        assistant([text("one")], providerThinkingLevel="low"),
        assistant([call()], providerThinkingLevel="max"),
        tool_result(),
        assistant([text("other")], provider="other", providerThinkingLevel="high"),
        assistant([text("invalid")], providerThinkingLevel="off"),
        assistant([text("empty")], providerThinkingLevel={}),
    ]
    result = convert(messages, managed_effort="medium")
    assert [
        (i, item["output_config"]["effort"])
        for i, item in enumerate(result)
        if item["role"] == "system"
    ] == [
        (0, "low"),
        (2, "max"),
        (8, "medium"),
    ]
    assert result[4] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call",
                "content": "read result",
                "is_error": False,
            }
        ],
    }
    assert not any(item["role"] == "system" for item in convert(messages))


def test_missing_tool_results_are_synthesized_before_next_user_and_at_end():
    result = convert(
        [
            assistant([call("answered"), call("missing")]),
            {"role": "system", "content": "already merged"},
            tool_result("answered"),
            {"role": "user", "content": "continue"},
            assistant([call("last")]),
        ]
    )
    assert result[1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "answered",
                "content": "read result",
                "is_error": False,
            },
            {
                "type": "tool_result",
                "tool_use_id": "missing",
                "content": "No result provided",
                "is_error": True,
            },
        ],
    }
    assert result[-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "last",
                "content": "No result provided",
                "is_error": True,
            }
        ],
    }


def test_cross_model_tool_ids_are_normalized_together_and_length_limited():
    call_id = "responses|call@" + "a" * 70
    normalized = "responses_call_" + "a" * 49
    result = convert(
        [
            assistant(
                [call(call_id)],
                api="openai-responses",
                provider="openai",
                model="other",
            ),
            tool_result(call_id),
        ]
    )
    assert result[0]["content"][0]["id"] == normalized
    assert result[1]["content"][0]["tool_use_id"] == normalized
    assert len(normalized) == 64


def test_user_images_and_tool_images_are_native_content_blocks():
    image = {"type": "image", "mimeType": "image/png", "data": "fixture-base64"}
    api_image = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "fixture-base64",
        },
    }
    result = convert(
        [
            {"role": "user", "content": [text(" "), text("look"), image]},
            assistant([call()]),
            tool_result(content=[image]),
        ]
    )
    assert result[0] == {"role": "user", "content": [text("look"), api_image]}
    assert result[-1]["content"][0]["content"] == [
        text("(see attached image)"),
        api_image,
    ]


def test_error_tool_images_follow_all_results_and_consecutive_images_share_note():
    image = {"type": "image", "mimeType": "image/png", "data": "fixture-base64"}
    result = convert(
        [
            assistant([call("bad"), call("good")]),
            tool_result("bad", content=[text("failed"), image, image], isError=True),
            tool_result("good"),
        ]
    )
    content = result[-1]["content"]
    assert [block["type"] for block in content] == [
        "tool_result",
        "tool_result",
        "text",
        "image",
        "image",
    ]
    assert content[0]["content"] == "failed\n(image attached after the tool results)"
    assert content[2] == text("Images from the error result of tool call bad (read):")


def test_blank_messages_removed_and_unpaired_surrogates_sanitized():
    assert convert(
        [
            {"role": "user", "content": " "},
            {"role": "user", "content": [text(" ")]},
            {"role": "user", "content": "hello\ud800\ud83d\ude00"},
            assistant([text(" ")]),
            assistant([text("reply\udc00😀")]),
        ]
    ) == [
        {"role": "user", "content": "hello😀"},
        {"role": "assistant", "content": [text("reply😀")]},
    ]
