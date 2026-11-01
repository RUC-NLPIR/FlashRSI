"""Capture trajectories by executing the pinned original Hermes conversation loop.

Example (run from any directory)::

    python generate_hermes_trajectory_upstream.py \
        --source /path/to/hermes-agent \
        --output /path/to/hermes_trajectory_upstream.json \
        --artifacts-dir /path/to/raw-oracle-artifacts

The checkout must be clean at v0.22.5 commit bf0203a794a07aac3ff764972ab9087baa4e4f4e.
A sparse checkout needs the full Python source tree (including pm/ and plugins/).
Use an isolated Python environment; no Hermes installation or npm is needed.
Tested on CPython 3.12.13 with these Python packages (and their dependencies)::

    pip install openai==2.24.0 ruamel.yaml==0.18.16 python-dotenv fire rich \
        tenacity tomli-w httpx requests jinja2 packaging truststore psutil \
        croniter snowballstemmer

Model I/O, explicit provider-client construction and tool dispatch receive fixed
replies. Discovery, persistence, trajectory saving and cleanup are fixture
boundaries; no original loop/helper is replaced. A virtual wall clock advances
through the original retry delays without changing their policies. --case can
select a subset for diagnosing or checking the generator.
Raw requests, outcomes, environment versions and source hashes are retained.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zlib
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_BASELINE = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"


def call(identifier, name, arguments):
    return {
        "id": identifier,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments
            if isinstance(arguments, str)
            else json.dumps(arguments),
        },
    }


def reply(content="", *, finish="stop", calls=None, reasoning=None, usage=None):
    return {
        "content": content,
        "finish_reason": finish,
        "tool_calls": calls,
        "usage": usage
        or {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        **({"reasoning_content": reasoning} if reasoning is not None else {}),
    }


def tool_reply(*calls):
    return reply(calls=list(calls), finish="tool_calls")


CASES = [
    {"name": "text_stop", "replies": [reply("The final answer is forty-two.")]},
    {
        "name": "text_think_strip",
        "replies": [
            reply("<think>Private reasoning.</think>The final answer is forty-two.")
        ],
    },
    {
        "name": "tools_two_rounds",
        "replies": [
            tool_reply(call("read-1", "read_file", {"path": "note.txt"})),
            tool_reply(
                call(
                    "write-1", "write_file", {"path": "note.txt", "content": "after\n"}
                )
            ),
            reply("I updated the note and verified the result."),
        ],
    },
    {
        "name": "tools_canonical_dedup",
        "replies": [
            tool_reply(
                call("first", "terminal", '{"command":"printf done","timeout":5}'),
                call(
                    "duplicate", "terminal", '{ "timeout":5, "command": "printf done" }'
                ),
            ),
            reply("The command ran once successfully."),
        ],
    },
    {
        "name": "tool_unknown",
        "replies": [
            tool_reply(call("unknown", "zxq_nonexistent_zxq", {})),
            reply("I recovered without calling that unavailable tool."),
        ],
    },
    {
        "name": "tool_disabled",
        "tools": ["read_file"],
        "replies": [
            tool_reply(call("disabled", "terminal", {"command": "printf unavailable"})),
            reply("I recovered without executing the disabled command."),
        ],
    },
    {
        "name": "tool_mixed_invalid",
        "replies": [
            tool_reply(
                call("bad", "zxq_nonexistent_zxq", {}),
                call("good", "read_file", {"path": "note.txt"}),
            ),
            reply("I used the valid file result and skipped the unknown tool."),
        ],
    },
    {
        "name": "budget_summary",
        "max_iterations": 1,
        "replies": [
            tool_reply(call("read", "read_file", {"path": "note.txt"})),
            reply("At the iteration limit, I read the note successfully."),
        ],
    },
    {
        "name": "budget_empty_summary_retry",
        "max_iterations": 1,
        "replies": [
            tool_reply(call("read", "read_file", {"path": "note.txt"})),
            reply(""),
            reply("The retry produced a useful summary of the note."),
        ],
    },
    {
        "name": "length_text_continuation",
        "replies": [
            reply("The first part explains the observed behavior.", finish="length"),
            reply("The second part completes the explanation."),
        ],
    },
    {
        "name": "length_tool_retry",
        "replies": [
            reply(calls=[call("truncated", "read_file", '{"path":')], finish="length"),
            reply("I recovered without executing the truncated call."),
        ],
    },
    {
        "name": "empty_then_text",
        "replies": [
            reply(""),
            reply("The retried response contains the final answer."),
        ],
    },
    {
        "name": "invalid_json_retry",
        "replies": [
            tool_reply(call("bad-1", "read_file", "{oops}")),
            tool_reply(call("bad-2", "read_file", "{oops}")),
            tool_reply(call("bad-3", "read_file", "{oops}")),
            reply("I recovered from the invalid argument encoding."),
        ],
    },
    {
        "name": "incomplete_json_refused",
        "replies": [tool_reply(call("bad", "write_file", '{"path":'))],
    },
    {
        "name": "tool_calls_finish_without_calls",
        "replies": [
            reply("I will read the note now.", finish="tool_calls", calls=[]),
            tool_reply(call("read", "read_file", {"path": "note.txt"})),
            reply("The note has been read successfully."),
        ],
    },
    {
        "name": "tool_name_repairs",
        "replies": [
            tool_reply(call("read", "ReadFile", {"path": "note.txt"})),
            tool_reply(
                call("write", "write-file", {"path": "note.txt", "content": "after\n"})
            ),
            tool_reply(call("shell", 'terminal"', {"command": "printf done"})),
            reply("All repaired tool names were executed successfully."),
        ],
    },
    {
        "name": "duplicate_call_ids",
        "replies": [
            tool_reply(
                call("same", "read_file", {"path": "a.txt"}),
                call("same", "read_file", {"path": "b.txt"}),
            ),
            tool_reply(call("same", "read_file", {"path": "c.txt"})),
            reply("I read all three distinct paths."),
        ],
    },
    {
        "name": "length_text_budget_one",
        "max_iterations": 1,
        "replies": [
            reply("The first part explains the observed behavior.", finish="length"),
            reply("This summarizes the partial work at the iteration limit."),
        ],
    },
    {
        "name": "post_tool_empty_recovery",
        "replies": [
            tool_reply(call("read", "read_file", {"path": "note.txt"})),
            reply(""),
            reply("The note was read, and this is the final answer."),
        ],
    },
    {
        "name": "unknown_tool_strikes_exhausted",
        "replies": [
            tool_reply(call("bad-1", "zxq_nonexistent_zxq", {})),
            tool_reply(call("bad-2", "zxq_nonexistent_zxq", {})),
            tool_reply(call("bad-3", "zxq_nonexistent_zxq", {})),
        ],
    },
    {
        "name": "length_text_exhausted",
        "replies": [
            reply(
                "The first partial fragment has useful information.", finish="length"
            ),
            reply(
                "The second partial fragment adds more information.", finish="length"
            ),
            reply("The third partial fragment adds more information.", finish="length"),
            reply(
                "The fourth partial fragment adds more information.", finish="length"
            ),
        ],
    },
    {
        "name": "length_tool_exhausted",
        "replies": [
            reply(
                calls=[call(f"truncated-{i}", "read_file", '{"path":')], finish="length"
            )
            for i in range(5)
        ],
    },
    {"name": "empty_exhausted", "replies": [reply("") for _ in range(5)]},
    {
        "name": "thinking_then_text",
        "replies": [
            reply("<think>Internal reasoning with no visible answer.</think>"),
            reply("The next response contains the visible final answer."),
        ],
    },
]
CASES.extend(
    [
        {
            "name": "api_retry_budget_independent",
            "max_iterations": 1,
            "replies": [
                {"http_error": 500, "body": {"error": {"message": "upstream error"}}},
                {"http_error": 429, "body": {"error": {"message": "rate limited"}}},
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("The note was read after the provider recovered."),
            ],
        },
        {
            "name": "api_invalid_response_retry_independent",
            "max_iterations": 1,
            "replies": [
                {"invalid_response": True},
                reply("Recovered within the same iteration."),
            ],
        },
        {
            "name": "stall_trailing_intent",
            "replies": [
                reply("Let me now inspect the file."),
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("I inspected the note successfully."),
            ],
        },
        {
            "name": "stall_bounded_two_nudges",
            "replies": [reply("Let me now inspect the file.") for _ in range(3)],
        },
        {
            "name": "stall_disabled",
            "agent_settings": {"stall_guards": False},
            "replies": [reply("Let me now inspect the file.")],
        },
        {
            "name": "intent_ack_opt_in",
            "agent_settings": {"intent_ack_continuation": True},
            "replies": [
                reply("I'll inspect the file now."),
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("The note was inspected successfully."),
            ],
        },
        {
            "name": "intent_ack_chat_default",
            "replies": [reply("I'll inspect the file now.")],
        },
        {
            "name": "degenerate_after_tools",
            "agent_settings": {"intent_ack_continuation": True},
            "replies": [
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("?warming"),
                reply("The note contains the requested result."),
            ],
        },
        {
            "name": "degenerate_chat_default",
            "replies": [
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("?warming"),
            ],
        },
        {
            "name": "stop_runaway_repetition",
            "replies": [reply("Repeated provider collapse. " * 650)],
        },
        {
            "name": "length_runaway_repetition",
            "replies": [reply("Repeated provider collapse. " * 650, finish="length")],
        },
        {
            "name": "length_prompt_window_full",
            "context_length": 20000,
            "replies": [
                reply(
                    "A useful partial answer.",
                    finish="length",
                    usage={
                        "prompt_tokens": 19900,
                        "completion_tokens": 100,
                        "total_tokens": 20000,
                    },
                )
            ],
        },
        {
            "name": "budget_summary_provider_failure",
            "max_iterations": 1,
            "replies": [
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                {
                    "http_error": 503,
                    "body": {"error": {"message": "upstream unavailable"}},
                },
            ],
        },
        {
            "name": "budget_think_only_summary_no_retry",
            "max_iterations": 1,
            "replies": [
                tool_reply(call("read", "read_file", {"path": "note.txt"})),
                reply("<think>Only internal reasoning.</think>"),
            ],
        },
        {
            "name": "structured_thinking_prefill",
            "replies": [
                reply(reasoning="Internal plan to solve the task."),
                reply("The visible final answer."),
            ],
        },
        {
            "name": "deterministic_zero_output_empty",
            "replies": [
                reply(
                    usage={
                        "prompt_tokens": 11,
                        "completion_tokens": 0,
                        "total_tokens": 11,
                    }
                )
                for _ in range(2)
            ],
        },
    ]
)
for status, name in ((429, "rate_limit"), (401, "auth"), (400, "format")):
    CASES.append(
        {
            "name": "fallback_" + name + "_eager",
            "max_iterations": 1,
            "fallback_providers": [
                {
                    "provider": "custom",
                    "model": "backup-model",
                    "base_url": "http://backup.invalid/v1",
                    "api_key": "backup-key",
                    "api_mode": "chat_completions",
                }
            ],
            "replies": [
                {
                    "http_error": status,
                    "body": {
                        "error": {
                            "message": "rate limited"
                            if status == 429
                            else "unauthorized"
                            if status == 401
                            else "bad request"
                        }
                    },
                },
                reply("The backup route completed this task."),
            ],
        }
    )
CASES.extend(
    [
        {
            "name": "api_auto_recovery_ladder",
            "max_iterations": 1,
            "agent_settings": {"api_max_retries": 2, "auto_recovery_cycles": 1},
            "replies": [
                {
                    "http_error": 503,
                    "body": {"error": {"message": "provider overloaded"}},
                },
                {
                    "http_error": 503,
                    "body": {"error": {"message": "provider overloaded"}},
                },
                reply(
                    "The original provider recovered during the bounded recovery cycle."
                ),
            ],
        },
        {
            "name": "api_transport_pool_recovery",
            "max_iterations": 1,
            "replies": [
                *[{"transport_error": "ReadTimeout"} for _ in range(3)],
                reply("The fresh transport completed the request."),
            ],
        },
    ]
)
CASES.extend(
    [
        {
            "name": "content_filter_text",
            "replies": [
                reply("I cannot answer this request.", finish="content_filter")
            ],
        },
        {
            "name": "content_filter_reasoning",
            "replies": [
                reply(
                    "", finish="content_filter", reasoning="This request was blocked."
                )
            ],
        },
        {
            "name": "content_filter_no_explanation",
            "replies": [reply("", finish="content_filter")],
        },
        {
            "name": "housekeeping_empty_reuses_prior",
            "tools": ["skill_manage"],
            "replies": [
                reply(
                    "I finished the requested task.",
                    finish="tool_calls",
                    calls=[call("todo", "skill_manage", {"action": "list"})],
                ),
                reply(""),
            ],
        },
        {
            "name": "housekeeping_stale_marker_not_reused",
            "tools": ["skill_manage"],
            "replies": [
                reply(
                    "[todo_list]",
                    finish="tool_calls",
                    calls=[call("todo", "skill_manage", {"action": "list"})],
                ),
                reply(""),
                reply("I finished the requested task."),
            ],
        },
        {
            "name": "reasoning_trusted_final",
            "custom_providers": [
                {
                    "name": "oracle",
                    "base_url": "http://oracle.invalid/v1",
                    "models": {"parity-model": {"answer_in_reasoning": True}},
                }
            ],
            "replies": [reply("", reasoning="The requested answer is forty-two.")],
        },
        {
            "name": "reasoning_trusted_plan_guard",
            "custom_providers": [
                {
                    "name": "oracle",
                    "base_url": "http://oracle.invalid/v1",
                    "capabilities": {"answer_in_reasoning": True},
                }
            ],
            "replies": [
                reply(
                    "",
                    reasoning="Let me batch the terminal calls to inspect the project.",
                ),
                reply("The requested answer is forty-two."),
            ],
        },
    ]
)


def png_data_url(width=2048, height=1024):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = b"".join(b"\0" + b"\x80\x40\x20" * width for _ in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(data).decode()


def image_history():
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect the attachment."},
                {"type": "image_url", "image_url": {"url": png_data_url()}},
            ],
        },
        {"role": "assistant", "content": "I will inspect the attachment."},
    ]


CASES.extend(
    [
        {
            "name": "recovery_reasoning_effort_drop",
            "reasoning_config": {"enabled": True, "effort": "max"},
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "param": "reasoning.effort",
                            "error_code": "invalid_reasoning_effort",
                            "retryable": False,
                        }
                    },
                },
                reply("Recovered after rejecting the enabled effort."),
            ],
        },
        {
            "name": "recovery_reasoning_disabled_floor",
            "reasoning_config": {"enabled": False, "effort": "none"},
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "Reasoning is mandatory for this endpoint and cannot be disabled."
                        }
                    },
                },
                reply("Recovered after the reasoning floor."),
            ],
        },
        {
            "name": "recovery_reasoning_disabled_drop",
            "reasoning_config": {"enabled": False, "effort": "none"},
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "Unrecognized request argument supplied: reasoning_effort"
                        }
                    },
                },
                reply("Recovered with the route default."),
            ],
        },
        {
            "name": "recovery_affordable_402",
            "llm": {"max_tokens": 8192},
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 402,
                    "body": {
                        "error": {
                            "message": "This request requires more credits. You requested up to 8192 tokens, but can only afford 2048."
                        }
                    },
                },
                reply("Recovered within the available credit budget."),
            ],
        },
        {
            "name": "recovery_llama_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "pattern": "[a-z]+", "format": "uri"}
                },
            },
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "Unable to generate parser for this template. Automatic parser generation failed: error parsing grammar"
                        }
                    },
                },
                reply("Recovered after stripping unsupported schema keywords."),
            ],
        },
        {
            "name": "recovery_replayed_reasoning_key",
            "replies": [
                reply(
                    "Reading.",
                    finish="tool_calls",
                    calls=[call("read", "read_file", {"path": "note.txt"})],
                    reasoning="Inspect the file first.",
                ),
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "Unknown field messages.1.reasoning_content: extra inputs are not permitted"
                        }
                    },
                },
                reply("Recovered without the rejected replay fields."),
            ],
        },
        {
            "name": "recovery_image_unsupported",
            "history": image_history(),
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {"error": {"message": "image_url is not supported"}},
                },
                reply("Recovered using the text attachment description."),
            ],
        },
        {
            "name": "recovery_image_corrupt",
            "history": image_history(),
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "failed to decode image: unsupported format"
                        }
                    },
                },
                reply("Recovered after dropping the corrupted image."),
            ],
        },
        {
            "name": "recovery_image_resize",
            "history": image_history(),
            "max_iterations": 1,
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {
                            "message": "image dimensions exceed max allowed size: 512 pixels"
                        }
                    },
                },
                reply("Recovered after resizing the oversized image."),
            ],
        },
    ]
)


def anthropic_reply(blocks, *, stop="end_turn"):
    return {
        "anthropic": {
            "id": "msg_fixture",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": blocks,
            "stop_reason": stop,
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
    }


_ANTHROPIC_ROUTE = {
    "model_api": "anthropic_messages",
    "provider": "anthropic",
    "model_name": "claude-opus-4-6",
    "base_url": "https://api.anthropic.com",
    "api_key": "sk-ant-api-fixture",
    "stream": False,
}
CASES.extend(
    [
        {
            "name": "anthropic_text",
            "llm": _ANTHROPIC_ROUTE,
            "replies": [
                anthropic_reply(
                    [{"type": "text", "text": "Completed through native Messages."}]
                )
            ],
        },
        {
            "name": "anthropic_interleaved_tools",
            "llm": _ANTHROPIC_ROUTE,
            "replies": [
                anthropic_reply(
                    [
                        {
                            "type": "thinking",
                            "thinking": "Inspect first.",
                            "signature": "signed-one",
                        },
                        {
                            "type": "tool_use",
                            "id": "read",
                            "name": "read_file",
                            "input": {"path": "note.txt"},
                        },
                        {
                            "type": "thinking",
                            "thinking": "Wait for the result.",
                            "signature": "signed-two",
                        },
                    ],
                    stop="tool_use",
                ),
                anthropic_reply([{"type": "text", "text": "Read completed."}]),
            ],
        },
        {
            "name": "anthropic_signature_recovery",
            "llm": _ANTHROPIC_ROUTE,
            "history": [
                {"role": "user", "content": "Original task."},
                {
                    "role": "assistant",
                    "content": "Earlier answer.",
                    "reasoning": "Earlier thought.",
                    "reasoning_details": [
                        {
                            "type": "thinking",
                            "thinking": "Earlier thought.",
                            "signature": "stale-signature",
                        }
                    ],
                },
            ],
            "replies": [
                {
                    "http_error": 400,
                    "body": {
                        "error": {"message": "Invalid signature in thinking block"}
                    },
                },
                anthropic_reply(
                    [
                        {
                            "type": "tool_use",
                            "id": "read",
                            "name": "read_file",
                            "input": {"path": "note.txt"},
                        }
                    ],
                    stop="tool_use",
                ),
                anthropic_reply(
                    [{"type": "text", "text": "Recovered signed replay and finished."}]
                ),
            ],
        },
        {
            "name": "anthropic_refusal",
            "llm": _ANTHROPIC_ROUTE,
            "replies": [
                anthropic_reply(
                    [{"type": "text", "text": "This request was refused."}],
                    stop="refusal",
                )
            ],
        },
    ]
)


for item in CASES:
    item.setdefault(
        "prompt",
        "Complete this task using the available tools, then give a final answer.",
    )
    item.setdefault("tools", ["read_file", "write_file", "terminal"])
    item.setdefault("max_iterations", 10)
    item.setdefault("system_prompt", "You are helpful.")
    # Dispatch is fixed so this oracle measures original loop behavior; actual
    # file/terminal semantics have independent original-source component tests.
    item["tool_result"] = '{"ok":true,"content":"fixture tool result"}'


def ns_response(value):
    if "anthropic" in value:

        def ns(item):
            if isinstance(item, dict):
                return SimpleNamespace(
                    **{
                        key: (value if key == "input" else ns(value))
                        for key, value in item.items()
                    }
                )
            if isinstance(item, list):
                return [ns(value) for value in item]
            return item

        return ns(value["anthropic"])
    if value.get("invalid_response"):
        return SimpleNamespace(choices=[], model="parity-model", usage=None)
    message = SimpleNamespace(
        role="assistant",
        content=value["content"],
        tool_calls=[
            SimpleNamespace(
                id=c["id"],
                type=c.get("type", "function"),
                function=SimpleNamespace(**c["function"]),
            )
            for c in value.get("tool_calls") or []
        ]
        or None,
    )
    if "reasoning_content" in value:
        message.reasoning_content = value["reasoning_content"]
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=message, finish_reason=value["finish_reason"])
        ],
        model="parity-model",
        usage=SimpleNamespace(**value["usage"]),
    )


def serializable(value):
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    if isinstance(value, SimpleNamespace):
        return serializable(vars(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def execute(case, artifacts_dir):
    from run_agent import AIAgent

    requests, dispatches = [], []
    replies = iter(copy.deepcopy(case["replies"]))

    def create(**kwargs):
        requests.append(serializable(copy.deepcopy(kwargs)))
        try:
            value = next(replies)
        except StopIteration as exc:
            raise AssertionError("UPSTREAM_ORACLE_REPLY_EXHAUSTED") from exc
        if value.get("http_error"):
            import httpx
            from openai import APIStatusError

            response = httpx.Response(
                value["http_error"],
                json=value["body"],
                request=httpx.Request(
                    "POST", "http://oracle.invalid/v1/chat/completions"
                ),
            )
            raise APIStatusError(
                str(value["body"]), response=response, body=value["body"]
            )
        if value.get("transport_error"):
            import httpx

            raise getattr(httpx, value["transport_error"])("fixture transport failed")
        return ns_response(value)

    def provider_client(*args, **kwargs):
        client = MagicMock()
        client.base_url = kwargs.get("base_url", "http://oracle.invalid/v1")
        client.api_key = kwargs.get("api_key", "oracle-only-key")
        client.default_headers = client._custom_headers = {}
        client.chat.completions.create.side_effect = create
        client.messages.create.side_effect = create
        return client

    def resolve_provider_client(provider, model, **kwargs):
        return provider_client(
            base_url=kwargs.get("explicit_base_url"),
            api_key=kwargs.get("explicit_api_key"),
        ), model

    def dispatch(name, arguments, *_args, **kwargs):
        dispatches.append(
            {
                "name": name,
                "arguments": serializable(copy.deepcopy(arguments)),
                "id": kwargs.get("tool_call_id"),
            }
        )
        return case["tool_result"]

    definitions = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": copy.deepcopy(
                    case.get("schema", {"type": "object", "properties": {}})
                ),
            },
        }
        for name in case["tools"]
    ]
    with ExitStack() as stack:

        class VirtualTime:
            current = 1700000000.0

            def time(self):
                return self.current

            def sleep(self, seconds):
                self.current += seconds

            def __getattr__(self, name):
                return getattr(time, name)

        virtual_time = VirtualTime()
        # Only wall-clock I/O is virtual. Original retry/guard/loop bodies and
        # their actual policy decisions execute unchanged.
        stack.enter_context(patch("agent.turn_recovery.time", virtual_time))
        stack.enter_context(patch("agent.agent_runtime_helpers.time", virtual_time))
        stack.enter_context(patch("hermes_cli.plugins.discover_plugins", lambda: None))
        stack.enter_context(
            patch("model_tools.get_tool_definitions", return_value=definitions)
        )
        stack.enter_context(
            patch("model_tools.check_toolset_requirements", return_value={})
        )
        stack.enter_context(
            patch("agent.process_bootstrap.OpenAI", side_effect=provider_client)
        )
        stack.enter_context(
            patch(
                "agent.auxiliary_client.resolve_provider_client",
                side_effect=resolve_provider_client,
            )
        )
        agent = AIAgent(
            api_key="oracle-only-key",
            base_url="http://oracle.invalid/v1",
            provider="custom",
            api_mode="chat_completions",
            model="parity-model",
            reasoning_config=case.get("reasoning_config"),
            max_tokens=case.get("llm", {}).get("max_tokens"),
            max_iterations=case["max_iterations"],
            fallback_model=case.get("fallback_providers"),
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            skip_background_review=True,
            cwd=str(artifacts_dir / "upstream-work"),
        )
        if case.get("llm", {}).get("model_api") == "anthropic_messages":
            agent.api_mode = "anthropic_messages"
            agent.provider = case["llm"]["provider"]
            agent.model = case["llm"]["model_name"]
            agent.base_url = agent._anthropic_base_url = case["llm"]["base_url"]
            agent._is_anthropic_oauth = False
            agent._disable_streaming = True
            agent._create_request_anthropic_client = lambda **kwargs: provider_client()
        agent._cached_system_prompt = case["system_prompt"]
        agent._use_prompt_caching = False
        for key, value in case.get("agent_settings", {}).items():
            setattr(agent, "_" + key, value)
        agent._custom_providers = case.get("custom_providers", [])
        if case.get("context_length"):
            agent.context_compressor.context_length = case["context_length"]
        agent.compression_enabled = False
        agent.save_trajectories = False
        agent.client = provider_client()
        stack.enter_context(
            patch("model_tools.handle_function_call", side_effect=dispatch)
        )
        stack.enter_context(patch.object(agent, "_persist_session"))
        stack.enter_context(patch.object(agent, "_save_trajectory"))
        stack.enter_context(patch.object(agent, "_cleanup_task_resources"))
        try:
            result = agent.run_conversation(
                case["prompt"], conversation_history=copy.deepcopy(case.get("history"))
            )
            return {
                "input": case,
                "result": serializable(result),
                "requests": requests,
                "dispatches": dispatches,
            }
        except BaseException as exc:
            return {
                "input": case,
                "exception": repr(exc),
                "traceback": traceback.format_exc(),
                "requests": requests,
                "dispatches": dispatches,
            }
        finally:
            try:
                agent.close()
            except Exception:
                pass


def make_fixture(source, records):
    sources = {}
    for relative in (
        "run_agent.py",
        "agent/conversation_loop.py",
        "agent/turn_context.py",
        "agent/turn_iteration_prep.py",
        "agent/turn_response_intake.py",
        "agent/turn_response_check.py",
        "agent/turn_tool_round.py",
        "agent/turn_tool_validation.py",
        "agent/tool_executor.py",
        "agent/tool_dispatch_helpers.py",
        "agent/turn_final_response.py",
        "agent/turn_finalizer.py",
        "agent/turn_empty_response.py",
        "agent/turn_truncation.py",
        "agent/chat_completion_helpers.py",
        "agent/message_sanitization.py",
        "agent/transports/chat_completions.py",
        "agent/transports/anthropic.py",
        "agent/anthropic_adapter.py",
        "agent/anthropic_message_convert.py",
        "agent/anthropic_thinking_replay.py",
        "agent/turn_recovery_codex.py",
        "agent/turn_retry_state.py",
        "agent/vision_message_prep.py",
        "agent/conversation_compression.py",
        "tools/vision_tools.py",
        "agent/error_classifier.py",
        "agent/retry_utils.py",
        "agent/turn_recovery.py",
        "agent/turn_api_error.py",
        "agent/empty_response_guard.py",
        "agent/repetition_guard.py",
    ):
        sources[relative] = hashlib.sha256((source / relative).read_bytes()).hexdigest()
    fixture = {
        "baseline": {
            "repository": "https://github.com/NousResearch/hermes-agent",
            "version": "v0.22.5",
            "python": platform.python_version(),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip(),
            "sources": sources,
            "method": (
                "Executed original AIAgent.run_conversation and its forwarded conversation_loop modules "
                "unchanged under CPython, following tests/agent/test_run_agent.py fixtures. "
                "Original OpenAI-client I/O receives the fixed SDK-shaped replies in each input. "
                "model_tools definitions and dispatch use explicit fixture schemas and a constant "
                "tool-result string, separating loop behavior from independently verified real tools."
            ),
            "fixture_boundaries": [
                "System prompt fixed to You are helpful.; context files, memory, compression, "
                "background review, prompt caching and trajectory saving disabled.",
                "Tool discovery and dispatcher stubbed; persistence, trajectory-saving and task "
                "cleanup are no-op fixture boundaries. No original loop branch or helper is replaced.",
                "Explicit provider-client creation returns fixture clients; a virtual time object "
                "advances the original retry waits. No real provider or model request is made.",
                "Not a live-model quality test, full CLI/product equivalence test, or real tool-I/O "
                "trajectory test. These raw records include original metadata and diagnostics.",
            ],
            "comparison_scope": [
                "Compare final text, completed/failed/partial, logical API counts and usage, semantic "
                "messages and requests, tool-call IDs/names/arguments and tool results.",
                "Exclude wall time, timestamps, generated session/turn/message IDs, internal "
                "persistence markers, provider call_id/response_item_id sidecars, schema descriptions "
                "and provider/transport default request options.",
                "Concurrent tool start/completion ordering is not deterministic; preserve the raw "
                "dispatch log but compare dispatch identity/arguments in transcript call order.",
            ],
        },
        "cases": records,
    }
    return fixture


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source", type=Path, required=True, help="Clean pinned Hermes source checkout"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_trajectory_upstream.json"),
        help="Frozen raw trajectory JSON",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Raw records and isolated HERMES_HOME; defaults to a new temporary directory",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[case["name"] for case in CASES],
        dest="selected_cases",
        help="Select one or more cases; omitted means all cases",
    )
    args = parser.parse_args(argv)
    source = args.source.expanduser().resolve()
    if not (source / "run_agent.py").is_file():
        parser.error("--source must contain the original run_agent.py")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if commit != _BASELINE:
        parser.error(f"expected source commit {_BASELINE}, found {commit}")
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True
    )
    if dirty.strip():
        parser.error(
            "upstream tracked source has modifications; use a clean pinned checkout"
        )
    destination = args.output.expanduser().resolve()
    artifacts = (
        args.artifacts_dir.expanduser().resolve()
        if args.artifacts_dir
        else Path(tempfile.mkdtemp(prefix="hermes-original-loop-"))
    )
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "upstream-work").mkdir(exist_ok=True)
    # Set this before importing original modules so no host Hermes profile is used.
    os.environ["HERMES_HOME"] = str(artifacts / "upstream-home")
    (artifacts / "upstream-home").mkdir(exist_ok=True)
    (artifacts / "upstream-home/config.yaml").write_text(
        "model:\n  supports_vision: true\n"
    )
    sys.path.insert(0, str(source))
    selected = [
        case
        for case in CASES
        if not args.selected_cases or case["name"] in args.selected_cases
    ]
    (artifacts / "upstream-cases.json").write_text(
        json.dumps(selected, indent=2, ensure_ascii=False) + "\n"
    )
    versions = {
        distribution.metadata["Name"]: distribution.version
        for distribution in importlib.metadata.distributions()
    }
    (artifacts / "upstream-environment.json").write_text(
        json.dumps(
            {"python": sys.version, "packages": versions}, indent=2, sort_keys=True
        )
        + "\n"
    )
    records = []
    for case in selected:
        record = execute(case, artifacts)
        records.append(record)
        (artifacts / f"upstream-{case['name']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        )
        summary = {
            key: record.get("result", {}).get(key)
            for key in (
                "final_response",
                "completed",
                "failed",
                "api_calls",
                "turn_exit_reason",
            )
        }
        print(
            case["name"],
            json.dumps(summary, ensure_ascii=False),
            record.get("exception", ""),
            flush=True,
        )
    (artifacts / "upstream-results.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    )
    fixture = make_fixture(source, records)
    fixture["baseline"]["generator_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    print(
        f"FROZEN {len(records)} original-loop trajectories -> {destination}; raw artifacts -> {artifacts}",
        flush=True,
    )
    return int(any("exception" in record for record in records))


if __name__ == "__main__":
    raise SystemExit(main())
