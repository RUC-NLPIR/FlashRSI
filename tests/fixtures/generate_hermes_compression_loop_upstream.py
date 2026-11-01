"""Execute original AIAgent with compression enabled and fixed provider I/O.

This complements the direct ContextCompressor oracle: original conversation,
compression host lifecycle, overflow and output-cap recovery remain active.
Tool dispatch, explicit system prompt, SDK I/O and persistence are boundaries.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import traceback
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from generate_hermes_compression_upstream import SUMMARY, canonical, corpus


def cases():
    return [
        {"name": "loop_high_usage_repeated", "rounds": 10},
        {
            "name": "loop_context_400",
            "history": True,
            "error_status": 400,
            "error_text": "context_length_exceeded: prompt is too long: 140000 tokens > 131072",
        },
        {
            "name": "loop_payload_413",
            "history": True,
            "error_status": 413,
            "error_text": "Request payload too large",
        },
        {
            "name": "loop_output_cap_400",
            "error_status": 400,
            "error_text": "max_tokens: 4096 > context_window: 131072 - input_tokens: 130072 = available_tokens: 1000",
        },
        {"name": "loop_idle", "history": True, "idle": 120},
        {"name": "loop_micro", "history": True, "micro": True},
        {
            "name": "loop_prune",
            "history": True,
            "history_kind": "tools",
            "prune": True,
            "rounds": 1,
            "prompt_tokens": 10000,
        },
        {
            "name": "loop_todo_boundary",
            "history": True,
            "error_status": 400,
            "error_text": "context_length_exceeded: prompt is too long: 140000 tokens > 131072",
            "todos": [
                {
                    "id": "read",
                    "content": "Inspect src/calculation.py",
                    "status": "completed",
                },
                {"id": "verify", "content": "Verify result 42", "status": "pending"},
            ],
        },
    ]


def execute(case, source, home):
    import hermes_time
    import httpx
    from agent import auxiliary_client, context_compressor
    from run_agent import AIAgent

    requests, summaries, dispatches, events = [], [], [], []
    declarations = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read_file tool",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]

    def summary(**kwargs):
        clean = {
            key: copy.deepcopy(value)
            for key, value in kwargs.items()
            if key not in {"route_info", "latency_info"}
        }
        clean.get("main_runtime", {}).pop("api_key", None)
        clean.pop("api_key", None)
        summaries.append(canonical(clean))
        kwargs.get("route_info", {}).update(
            provider="custom", model=kwargs.get("model") or "oracle-main"
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=SUMMARY), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100, completion_tokens=80, total_tokens=180
            ),
        )

    def create(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        number = len(requests)
        if number > 16:
            raise AssertionError("Unexpected extra oracle model request")
        if case.get("error_status") and number == 1:
            request = httpx.Request("POST", "http://oracle.invalid/v1/chat/completions")
            response = httpx.Response(
                case["error_status"],
                request=request,
                json={
                    "error": {
                        "message": case["error_text"],
                        "code": "context_length_exceeded"
                        if case["error_status"] == 400
                        else "payload_too_large",
                    }
                },
            )
            raise httpx.HTTPStatusError(
                case["error_text"], request=request, response=response
            )
        call = None
        if number <= case.get("rounds", 0):
            call = SimpleNamespace(
                id=f"read-{number}",
                type="function",
                function=SimpleNamespace(
                    name="read_file",
                    arguments=json.dumps({"path": f"file-{number}.txt"}),
                ),
            )
        content = (
            (
                f"Round {number} verified src/calculation.py and retained result 42.\n"
                * 150
            )
            if call
            else "Completed the requested check; the result is 42."
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        role="assistant",
                        content=content,
                        tool_calls=[call] if call else None,
                    ),
                    finish_reason="tool_calls" if call else "stop",
                )
            ],
            model="oracle-main",
            usage=SimpleNamespace(
                prompt_tokens=case.get("prompt_tokens", 120000) if call else 1000,
                completion_tokens=128,
                total_tokens=case.get("prompt_tokens", 120000) + 128 if call else 1128,
            ),
        )

    def dispatch(name, arguments, *_args, **kwargs):
        dispatches.append(
            {"name": name, "arguments": arguments, "id": kwargs.get("tool_call_id")}
        )
        return json.dumps({"content": "src/calculation.py result 42\n" * 500})

    with ExitStack() as stack:
        stack.enter_context(patch("hermes_cli.plugins.discover_plugins", lambda: None))
        stack.enter_context(
            patch("model_tools.get_tool_definitions", return_value=declarations)
        )
        stack.enter_context(
            patch("model_tools.check_toolset_requirements", return_value={})
        )
        stack.enter_context(patch("agent.process_bootstrap.OpenAI"))
        stack.enter_context(
            patch.object(
                hermes_time,
                "now",
                return_value=datetime(2026, 11, 1, tzinfo=timezone.utc),
            )
        )
        stack.enter_context(patch.object(context_compressor, "call_llm", summary))
        stack.enter_context(patch.object(auxiliary_client, "call_llm", summary))
        agent = AIAgent(
            api_key="synthetic-unused-key",
            base_url="http://oracle.invalid/v1",
            provider="custom",
            api_mode="chat_completions",
            model="oracle-main",
            max_iterations=20,
            max_tokens=4096,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            skip_background_review=True,
            cwd=home,
        )
        agent._cached_system_prompt = (
            "You maintain a Python project. Obey the latest real user request."
        )
        agent._retain_seeded_system_prompt = True
        agent._use_prompt_caching = False
        agent.compression_enabled = True
        agent.compression_in_place = True
        agent.max_compression_attempts = 3
        agent.compression_idle_compact_after_seconds = 60 if case.get("idle") else 0
        agent._last_activity_ts -= case.get("idle", 0)
        agent.context_compressor = context_compressor.ContextCompressor(
            model="oracle-main",
            provider="custom",
            quiet_mode=True,
            config_context_length=131072,
            max_tokens=4096,
            threshold_tokens_cap=90000,
            proactive_prune_tokens=1000 if case.get("prune") else 0,
            proactive_prune_min_reclaim_tokens=0 if case.get("prune") else 4096,
        )
        agent.context_compressor._micro_compact_enabled = bool(case.get("micro"))
        if case.get("todos"):
            agent._todo_store.restore(case["todos"])
        agent._session_db = None
        agent.save_trajectories = False
        agent.event_callback = lambda kind, data: events.append(
            {"type": kind, "compression_count": data.get("compression_count")}
        )
        agent.client = MagicMock()
        agent.client.chat.completions.create.side_effect = create
        stack.enter_context(
            patch("model_tools.handle_function_call", side_effect=dispatch)
        )
        stack.enter_context(patch.object(agent, "_persist_session"))
        stack.enter_context(patch.object(agent, "_save_trajectory"))
        stack.enter_context(patch.object(agent, "_cleanup_task_resources"))
        try:
            result = agent.run_conversation(
                "Now finish the boundary check in src/calculation.py and report 42; do not restart completed work.",
                conversation_history=corpus(case.get("history_kind", "dialogue"))[1:-1]
                if case.get("history")
                else None,
            )
            # Runtime IDs, timestamps and provider-native transport defaults are
            # outside the semantic comparison. Every actual message/cap is kept.
            fields = {
                "role",
                "content",
                "name",
                "tool_call_id",
                "tool_calls",
                "reasoning",
                "reasoning_content",
                "reasoning_details",
            }

            def clean_messages(values):
                return [
                    {key: value for key, value in message.items() if key in fields}
                    for message in values
                ]

            return {
                "input": case,
                "final_response": result.get("final_response"),
                "completed": result.get("completed"),
                "failed": result.get("failed", False),
                "error": result.get("error"),
                "api_calls": result.get("api_calls"),
                "messages": canonical(clean_messages(result.get("messages", []))),
                "requests": [
                    canonical(
                        {
                            key: clean_messages(value) if key == "messages" else value
                            for key, value in request.items()
                            if key
                            in {
                                "model",
                                "messages",
                                "max_tokens",
                                "max_completion_tokens",
                                "temperature",
                                "top_p",
                                "reasoning_effort",
                                "stream",
                            }
                        }
                    )
                    for request in requests
                ],
                "summary_requests": summaries,
                "dispatches": canonical(dispatches),
                "compression_count": agent.context_compressor.compression_count,
                "events": events,
            }
        except Exception as error:
            return {
                "input": case,
                "exception": str(error),
                "traceback": traceback.format_exc(),
                "request_count": len(requests),
                "summary_requests": summaries,
            }
        finally:
            agent.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_compression_loop_upstream.json"),
    )
    options = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=options.source, text=True
    ).strip()
    assert commit == "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
    with tempfile.TemporaryDirectory(prefix="hermes-compression-loop-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        Path(home, "config.yaml").write_text(
            "model:\n  default: oracle-main\n  context_length: 131072\ncompression:\n  enabled: true\n"
        )
        sys.path.insert(0, str(options.source))
        logging.disable(logging.CRITICAL)
        with (
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("Oracle attempted network"),
            ),
            patch.object(
                socket,
                "getaddrinfo",
                side_effect=AssertionError("Oracle attempted DNS"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("Oracle attempted socket"),
            ),
        ):
            records = []
            for case in cases():
                record = execute(case, options.source, home)
                records.append(record)
                print(
                    case["name"],
                    {
                        key: record.get(key)
                        for key in (
                            "api_calls",
                            "compression_count",
                            "completed",
                            "failed",
                            "error",
                            "exception",
                        )
                    },
                    "summary_calls",
                    len(record.get("summary_requests", [])),
                    flush=True,
                )
        fixture = {
            "baseline": {
                "repository": "https://github.com/NousResearch/hermes-agent",
                "version": "v0.22.5",
                "commit": commit,
                "source_sha256": {
                    name: hashlib.sha256(
                        (options.source / name).read_bytes()
                    ).hexdigest()
                    for name in (
                        "agent/conversation_loop.py",
                        "agent/conversation_compression.py",
                        "agent/turn_overflow.py",
                        "agent/turn_context_compaction.py",
                    )
                },
            },
            "method": "Actual AIAgent.run_conversation with compression enabled and actual original ContextCompressor; SDK/summary I/O and declared tool dispatcher fixed; original overflow/compression logic active. No session DB bound. Seeded explicit system prompt retained through documented flag.",
            "cases": records,
        }
        options.output.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
