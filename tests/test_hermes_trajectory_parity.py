"""Replay fixed responses against the native loop and original AIAgent oracle.

The oracle executes the pinned original conversation loop. Provider I/O, tool
discovery/dispatch, persistence and cleanup are fixture boundaries; default
prompt assembly and actual tool semantics are checked separately. Operational
timestamps, provider metadata and persistence flags are excluded here.
"""

import asyncio
import copy
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

_FIXTURE = Path(__file__).parent / "fixtures/hermes_trajectory_upstream.json"


def replay_native(case, cwd, runtime=None):
    runtime = runtime or (
        Path(__file__).parents[1] / "flashrsi/agents/hermes/runtime/hermes_native"
    )
    name = "flashrsi_hermes_parity_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(
        name, runtime / "__init__.py", submodule_search_locations=[str(runtime)]
    )
    assert spec and spec.loader
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    requests, dispatches = [], []
    replies = iter(copy.deepcopy(case["replies"]))

    class FixedTools:
        def __init__(self, workdir, snapshot_root, enabled_tools=None):
            self.cwd = workdir
            self.schemas = [
                {
                    "type": "function",
                    "function": {
                        "name": tool,
                        "description": f"{tool} tool",
                        "parameters": copy.deepcopy(case.get("schema", {"type":"object", "properties":{}})),
                    },
                }
                for tool in case["tools"]
            ]

        def execute(self, tool, arguments):
            return case["tool_result"]

        def close(self):
            pass

    def respond(request):
        requests.append(json.loads(request.content))
        try:
            value = next(replies)
        except StopIteration as exc:
            raise AssertionError("NATIVE_ORACLE_REPLY_EXHAUSTED") from exc
        if value.get("http_error"):
            return httpx.Response(value["http_error"], json=value["body"])
        if "anthropic" in value:
            return httpx.Response(200, json=value["anthropic"])
        if value.get("invalid_response"):
            return httpx.Response(200, json={"choices": []})
        if value.get("transport_error"):
            raise getattr(httpx, value["transport_error"])("fixture transport failed")
        message = {"role": "assistant", "content": value["content"]}
        if "reasoning_content" in value:
            message["reasoning_content"] = value["reasoning_content"]
        if value.get("tool_calls") is not None:
            message["tool_calls"] = value["tool_calls"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": message, "finish_reason": value["finish_reason"]}
                ],
                "usage": value["usage"],
            },
        )

    client_class = httpx.AsyncClient

    def client(*args, **kwargs):
        return client_class(
            *args,
            **kwargs,
            transport=httpx.MockTransport(respond),
            trust_env=False,
        )

    try:
        if case.get("history"):
            (cwd / "history.json").write_text(json.dumps({"format":"hermes-native-v1", "messages":case["history"]}))
        spec.loader.exec_module(package)
        loop = sys.modules[name + ".loop"]
        with (
            patch.object(loop, "HermesTools", FixedTools),
            patch.object(
                loop,
                "load_resources",
                return_value=SimpleNamespace(
                    system_prompt=case["system_prompt"],
                    enabled_tools=case["tools"],
                    diagnostics=[],
                ),
            ),
            patch.object(httpx, "AsyncClient", client),
            patch.object(sys.modules[name + ".retry"], "sleep", AsyncMock()),
        ):
            result = asyncio.run(
                package.run(
                    {
                        "llm": {
                            "model_name": "parity-model",
                            "api_key": "fixture-key",
                            "base_url": "http://oracle.invalid/v1",
                            **case.get("llm", {}),
                        },
                        "max_iterations": case["max_iterations"],
                        "compression": {"enabled": False},
                        "timeout": 10,
                        "agent": case.get("agent_settings", {}),
                        "custom_providers": case.get("custom_providers", []),
                        **({"reasoning_config":case["reasoning_config"]} if "reasoning_config" in case else {}),
                        **({"session_file":"history.json"} if case.get("history") else {}),
                        **(
                            {"fallback_providers": case["fallback_providers"]}
                            if case.get("fallback_providers")
                            else {}
                        ),
                        **(
                            {"context_length": case["context_length"]}
                            if case.get("context_length")
                            else {}
                        ),
                    },
                    case["prompt"],
                    cwd,
                    runtime.parents[1],
                )
            )
        dispatches = [
            {
                "name": event["name"],
                "arguments": event["arguments"],
                "id": event["id"],
            }
            for event in result.events
            if event["type"] == "tool_execution_start"
        ]
        return {
            "input": case,
            "result": vars(result),
            "requests": requests,
            "dispatches": dispatches,
        }
    finally:
        for imported in list(sys.modules):
            if imported == name or imported.startswith(name + "."):
                sys.modules.pop(imported, None)


def normalize_messages(messages):
    fields = (
        "role",
        "content",
        "name",
        "tool_call_id",
        "tool_calls",
        "finish_reason",
        "reasoning_content",
        "reasoning_details",
        "api_content",
        "_anthropic_content_blocks",
        "anthropic_content_blocks",
        "stop_details",
    )
    result = []
    for message in messages:
        item = {key: copy.deepcopy(message[key]) for key in fields if key in message}
        if message.get("reasoning"):
            item["reasoning"] = message["reasoning"]
        if "tool_calls" in item:
            for call in item["tool_calls"]:
                call.pop("call_id", None)
                call.pop("response_item_id", None)
                arguments = call["function"].get("arguments")
                try:
                    call["function"]["arguments"] = json.loads(arguments)
                except (ValueError, TypeError):
                    pass
        result.append(item)
    return result


def normalize_record(record, native=False):
    result = record["result"]
    if native:
        settled = next(
            event
            for event in reversed(result["events"])
            if event["type"] == "hermes_result"
        )
        final_response = result["output"]
        completed = settled["completed"]
        failed = settled["failed"]
        api_calls = settled["api_calls"]
        partial = settled.get("partial", False)
    else:
        final_response = result.get("final_response", "")
        completed = result.get("completed", False)
        failed = result.get("failed", bool(result.get("error")))
        api_calls = result["api_calls"]
        partial = result.get("partial", False)
    source_order = {
        call["id"]: index
        for index, call in enumerate(
            call
            for message in result["messages"]
            for call in message.get("tool_calls", [])
        )
    }
    usage = (
        result.get("usage", {})
        if native
        else {
            "input": result.get("input_tokens", 0),
            "output": result.get("output_tokens", 0),
        }
    )
    return {
        "final_response": final_response,
        "completed": completed,
        "failed": failed,
        "api_calls": api_calls,
        # Original early partial returns omit usage entirely; they cannot
        # establish token-accounting parity on those paths.
        "usage": None
        if partial
        else {key: usage.get(key, 0) for key in ("input", "output")},
        "partial": partial,
        "messages": normalize_messages(result["messages"]),
        "requests": [
            {
                "model": request["model"],
                "messages": normalize_messages(request["messages"]),
                "tools": [
                    tool.get("function", {}).get("name", tool.get("name")) for tool in request.get("tools", [])
                ],
                "output_cap": request.get(
                    "max_completion_tokens", request.get("max_tokens")
                ),
                "reasoning_effort": request.get("reasoning_effort"),
                "reasoning_config": request.get("reasoning", (request.get("extra_body") or {}).get("reasoning")),
                **({"system":request.get("system"),"thinking":request.get("thinking"),"output_config":request.get("output_config")} if record["input"].get("llm",{}).get("model_api")=="anthropic_messages" else {}),
                **({"schema": [tool["function"]["parameters"] for tool in request.get("tools", [])]} if "schema" in record["input"] else {}),
            }
            for request in record["requests"]
        ],
        # Calls from one parallel batch may start in either thread order.
        # Compare pairing and execution count in source order; raw timing/order
        # remains available in the original records.
        "dispatches": sorted(
            record["dispatches"], key=lambda call: source_order.get(call["id"], -1)
        ),
    }


def _cases():
    return json.loads(_FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["input"]["name"])
def test_native_hermes_matches_original_conversation_loop(case, tmp_path):
    actual = replay_native(case["input"], tmp_path)
    assert normalize_record(actual, native=True) == normalize_record(case)
