"""Freeze actual pinned ContextCompressor execution, replacing only LLM/clock I/O.

Reproduce with the upstream-only oracle environment:
  /tmp/hermes-loop-oracle-venv/bin/python tests/fixtures/generate_hermes_compression_upstream.py /tmp/hermes-agent-v0.22.5-source

Long strings are compared through their exact SHA-256/length plus readable
head/tail, preserving every message/request field without a multi-MB fixture.
Neither compression, pruning, tail selection nor failure logic is replaced.
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
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SUMMARY = """## Historical Task Snapshot
Continue repairing src/calculation.py and verify the requested result.

## Goal
Keep arithmetic behavior and tests consistent.

## Constraints & Preferences
Pure Python. Preserve file paths and exact diagnostic values.

## Completed Actions
1. Inspected src/calculation.py; the observed result was 42.

## In Progress
Check the remaining boundary case.

## Active State
Workspace src/calculation.py; todo verification pending.

## Open Questions
None.
"""


def canonical(value):
    """Exact compact projection: retain all fields, hash only long text bodies."""
    if isinstance(value, str):
        if len(value) <= 1800:
            return value
        return {
            "chars": len(value),
            "sha256": hashlib.sha256(value.encode()).hexdigest(),
            "head": value[:160],
            "tail": value[-160:],
        }
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, SimpleNamespace):
        return canonical(vars(value))
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def corpus(kind="dialogue"):
    messages = [
        {
            "role": "system",
            "content": "You maintain a Python project. Obey the latest real user request.",
        }
    ]
    if kind == "short":
        return messages + [
            {"role": "user", "content": "What is 6*7?"},
            {"role": "assistant", "content": "42"},
        ]
    for number in range(18):
        messages.append(
            {
                "role": "user",
                "content": f"Task {number}: inspect src/calculation.py and retain diagnostic value {number + 42}.",
            }
        )
        text = (
            f"Analysis for turn {number}: calculation.py status and boundary observations.\n"
            + (
                f"case-{number}: expected={number + 42}; verified arithmetic and noted pending checks.\n"
                * 110
            )
        )
        assistant = {"role": "assistant", "content": text}
        if kind in {"tools", "duplicate_tools", "orphan_tools"}:
            name = (
                "skill_view"
                if number in (2, 4)
                else "todo_list"
                if number == 5
                else "read_file"
            )
            args = (
                {"name": "python-testing"}
                if name == "skill_view"
                else {
                    "todos": [
                        {
                            "id": "verify",
                            "content": "Run boundary checks",
                            "status": "pending",
                        }
                    ]
                }
                if name == "todo_list"
                else {"path": f"src/file-{number}.py"}
            )
            assistant["tool_calls"] = [
                {
                    "id": f"call-{number}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ]
        messages.append(assistant)
        if "tool_calls" in assistant:
            content = (
                "# Skill: python-testing\nUse assertions and rerun relevant checks.\n"
                * 180
                if name == "skill_view"
                else json.dumps(
                    {
                        "todos": [
                            {
                                "id": "verify",
                                "content": "Run boundary checks",
                                "status": "pending",
                            }
                        ]
                    }
                )
                if name == "todo_list"
                else "read result: src/calculation.py exact result 42\n" * 230
                if kind == "duplicate_tools"
                else (
                    f"read result: src/file-{number}.py exact result {number + 42}\n"
                    * 230
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call-{number}",
                    "name": name,
                    "content": content,
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Recorded file-{number}.py; proceed to the next requested check.",
                }
            )
    if kind == "orphan_tools":
        messages.insert(
            7,
            {
                "role": "tool",
                "tool_call_id": "missing-call",
                "content": "orphan result should not survive without its call",
            },
        )
    messages.append(
        {
            "role": "user",
            "content": "Now finish the boundary check in src/calculation.py and report 42; do not restart completed work.",
        }
    )
    return messages


def case_inputs():
    full = {"method": "compress", "kwargs": {"current_tokens": 120000}}
    forced = {"method": "compress", "kwargs": {"current_tokens": 120000, "force": True}}
    cases = [
        {"name": "full_defaults", "operations": [full]},
        {
            "name": "full_manual_focus_memory",
            "operations": [
                {
                    "method": "compress",
                    "kwargs": {
                        "current_tokens": 120000,
                        "force": True,
                        "focus_topic": "src/calculation.py arithmetic",
                        "memory_context": "Operator requirement: preserve exact result 42.",
                    },
                }
            ],
        },
        {"name": "full_tools_skills_todo", "corpus": "tools", "operations": [full]},
        {
            "name": "full_orphan_tool_pairs",
            "corpus": "orphan_tools",
            "operations": [forced],
        },
        {
            "name": "full_repeated_iterative",
            "operations": [
                forced,
                {"method": "append", "corpus": "dialogue"},
                {
                    "method": "usage",
                    "value": {"prompt_tokens": 125000, "completion_tokens": 128},
                },
                forced,
            ],
        },
        {"name": "full_short_noop", "corpus": "short", "operations": [forced]},
        {
            "name": "full_reasoning_summary",
            "replies": ["reasoning"],
            "operations": [forced],
        },
    ]
    for failure in (
        "empty",
        "length",
        "auth",
        "network",
        "refusal",
        "no_provider",
        "generic",
    ):
        cases.append(
            {"name": f"summary_{failure}", "replies": [failure], "operations": [forced]}
        )
    for failure in ("empty", "length", "auth"):
        cases.append(
            {
                "name": f"summary_{failure}_main_fallback",
                "constructor": {"summary_model_override": "oracle-summary"},
                "replies": [failure, "success"],
                "operations": [forced],
            }
        )
    cases.extend(
        [
            {
                "name": "summary_generic_abort",
                "constructor": {"abort_on_summary_failure": True},
                "replies": ["generic"],
                "operations": [forced],
            },
            {
                "name": "summary_empty_cooldown_force_retry",
                "replies": ["empty", "success"],
                "operations": [forced, {"method": "should", "tokens": 120000}, forced],
            },
            {
                "name": "prune_real_tools_and_rearm",
                "corpus": "tools",
                "constructor": {
                    "protect_first_n": 0,
                    "protect_last_n": 3,
                    "proactive_prune_tokens": 1000,
                    "proactive_prune_min_result_chars": 200,
                    "proactive_prune_min_reclaim_tokens": 0,
                },
                "operations": [
                    {"method": "prune", "tokens": 50000},
                    {"method": "prune", "tokens": 50000},
                ],
            },
            {
                "name": "prune_exact_duplicate_results",
                "corpus": "duplicate_tools",
                "constructor": {
                    "protect_first_n": 0,
                    "protect_last_n": 3,
                    "proactive_prune_tokens": 1000,
                    "proactive_prune_min_result_chars": 200,
                    "proactive_prune_min_reclaim_tokens": 0,
                },
                "operations": [{"method": "prune", "tokens": 50000}],
            },
            {
                "name": "prune_below_trigger_noop",
                "corpus": "tools",
                "constructor": {"proactive_prune_tokens": 10000},
                "operations": [{"method": "prune", "tokens": 9999}],
            },
            {
                "name": "micro_two_passes",
                "attributes": {"_micro_compact_enabled": True},
                "operations": [{"method": "micro"}, {"method": "micro"}],
            },
            {
                "name": "micro_tools_pair",
                "corpus": "tools",
                "attributes": {"_micro_compact_enabled": True},
                "operations": [{"method": "micro"}],
            },
            {
                "name": "micro_cadence",
                "attributes": {
                    "_micro_compact_enabled": True,
                    "_micro_compact_every_n_turns": 2,
                },
                "operations": [{"method": "micro"}, {"method": "micro"}],
            },
            {
                "name": "micro_length_failure_skip",
                "attributes": {"_micro_compact_enabled": True},
                "replies": ["length"] * 3,
                "operations": [{"method": "micro"}] * 3,
            },
            {
                "name": "micro_defrag",
                "attributes": {
                    "_micro_compact_enabled": True,
                    "_micro_compact_defrag_threshold_tokens": 10,
                },
                "operations": [{"method": "micro"}, {"method": "micro"}],
            },
            {
                "name": "threshold_usage_and_reservation",
                "constructor": {
                    "config_context_length": 65536,
                    "threshold_percent": 0.5,
                    "max_tokens": 32768,
                    "threshold_tokens_cap": 30000,
                },
                "operations": [
                    {"method": "should", "tokens": 27851},
                    {"method": "should", "tokens": 27852},
                    {"method": "preflight", "tokens": 60000},
                    {
                        "method": "usage",
                        "value": {"prompt_tokens": 60000, "completion_tokens": 2048},
                    },
                    {"method": "preflight", "tokens": 60000},
                ],
            },
            {
                "name": "threshold_model_override",
                "constructor": {
                    "model": "oracle-large-pro",
                    "config_context_length": 1048576,
                    "model_thresholds": {"oracle": 0.6, "large-pro": 0.8},
                },
                "operations": [
                    {"method": "should", "tokens": 800000},
                    {"method": "should", "tokens": 840000},
                ],
            },
            {
                "name": "usage_missing_preflight",
                "operations": [
                    {"method": "preflight", "tokens": 200000},
                    {"method": "usage_less"},
                    {"method": "preflight", "tokens": 200000},
                ],
            },
        ]
    )
    for case in cases:
        case.setdefault("corpus", "dialogue")
    return cases


STATE_NAMES = (
    "context_length",
    "threshold_percent",
    "threshold_tokens",
    "tail_token_budget",
    "max_summary_tokens",
    "compression_count",
    "last_prompt_tokens",
    "last_real_prompt_tokens",
    "awaiting_real_usage_after_compression",
    "last_compression_rough_tokens",
    "summary_model",
    "_previous_summary",
    "_last_compress_aborted",
    "_last_summary_fallback_used",
    "_last_summary_dropped_count",
    "_last_summary_auth_failure",
    "_last_summary_network_failure",
    "_last_summary_empty_content_failure",
    "_last_summary_truncated_failure",
    "_summary_failure_cooldown_until",
    "_ineffective_compression_count",
    "_fallback_compression_streak",
    "_proactive_prune_rearm_tokens",
    "_micro_compact_cursor",
    "_micro_compact_rolling_summary",
    "_micro_compact_consecutive_failures",
    "_micro_compact_turns_since_pass",
)


def execute(cc, case, *, auxiliary_module=None, clock_module=None):
    calls, steps = [], []
    replies = iter(case.get("replies", []))

    def llm(**kwargs):
        # Timing and mutable route observation are transport instrumentation;
        # caps, model, task, runtime and every prompt message remain compared.
        clean = {
            key: copy.deepcopy(value)
            for key, value in kwargs.items()
            if key not in {"route_info", "latency_info"}
        }
        clean.get("main_runtime", {}).pop("api_key", None)
        clean.pop("api_key", None)
        calls.append(canonical(clean))
        mode = next(replies, "success")
        if isinstance(kwargs.get("route_info"), dict):
            kwargs["route_info"].update(
                provider="custom",
                model=kwargs.get("model")
                or kwargs.get("main_runtime", {}).get("model")
                or "oracle-main",
            )
        if mode in {"auth", "network", "no_provider", "generic"}:
            error = {
                "auth": "HTTP 401 Invalid token",
                "network": "Connection error: connection reset by peer",
                "no_provider": "No LLM provider configured",
                "generic": "Synthetic unsupported summary backend",
            }[mode]
            raise RuntimeError(error)
        content = (
            ""
            if mode in {"empty", "reasoning"}
            else "I cannot summarize this conversation."
            if mode == "refusal"
            else SUMMARY
        )
        message = SimpleNamespace(
            content=content, reasoning_content=SUMMARY if mode == "reasoning" else None
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=message,
                    finish_reason="length" if mode == "length" else "stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100, completion_tokens=80, total_tokens=180
            ),
        )

    constructor = {
        "model": "oracle-main",
        "quiet_mode": True,
        "config_context_length": 131072,
        "provider": "custom",
        **case.get("constructor", {}),
    }
    engine = cc.ContextCompressor(**constructor)
    for key, value in case.get("attributes", {}).items():
        setattr(engine, key, value)
    messages = corpus(case["corpus"])
    with ExitStack() as stack:
        stack.enter_context(patch.object(cc, "call_llm", llm))
        if auxiliary_module is not None:
            stack.enter_context(patch.object(auxiliary_module, "call_llm", llm))
        stack.enter_context(patch.object(cc.time, "monotonic", return_value=1000.0))
        stack.enter_context(patch.object(cc.time, "time", return_value=1793491200.0))
        if clock_module is not None:
            stack.enter_context(
                patch.object(
                    clock_module,
                    "now",
                    return_value=datetime(2026, 11, 1, tzinfo=timezone.utc),
                )
            )
        else:
            stack.enter_context(
                patch.object(cc, "_today_for_prompt", return_value="2026-11-01")
            )
        for operation in case["operations"]:
            before = copy.deepcopy(messages)
            method, outcome = operation["method"], None
            if method == "compress":
                candidate = engine.compress(messages, **operation["kwargs"])
                outcome = {
                    "same_object": candidate is messages,
                    "changed": candidate != before,
                }
                messages = candidate
            elif method == "append":
                messages += corpus(operation["corpus"])[1:]
            elif method == "prune":
                candidate, count = engine.prune_tool_results_only(
                    messages, current_tokens=operation["tokens"]
                )
                outcome = {
                    "count": count,
                    "same_object": candidate is messages,
                    "changed": candidate != before,
                }
                messages = candidate
            elif method == "micro":
                candidate = engine._micro_compact(messages)
                outcome = {
                    "same_object": candidate is messages,
                    "changed": candidate != before,
                }
                messages = candidate
            elif method == "usage":
                engine.update_from_response(operation["value"])
            elif method == "usage_less":
                engine.note_usage_less_response()
            elif method == "should":
                outcome = engine.should_compress_info(operation["tokens"])
            elif method == "preflight":
                outcome = engine.should_defer_preflight_to_real_usage(
                    operation["tokens"]
                )
            else:
                raise AssertionError(method)
            steps.append(
                {
                    "operation": operation,
                    "outcome": canonical(outcome),
                    "state": canonical(
                        {key: getattr(engine, key, None) for key in STATE_NAMES}
                    ),
                    "messages": canonical(messages),
                    "summary_calls_so_far": len(calls),
                }
            )
    return {
        "name": case["name"],
        "input": case,
        "steps": steps,
        "summary_requests": calls,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_compression_upstream.json"),
    )
    options = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=options.source, text=True
    ).strip()
    assert commit == "bf0203a794a07aac3ff764972ab9087baa4e4f4e", commit
    with tempfile.TemporaryDirectory(prefix="hermes-compression-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        sys.path.insert(0, str(options.source))
        import hermes_time
        from agent import auxiliary_client, context_compressor

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
            for case in case_inputs():
                record = execute(
                    context_compressor,
                    case,
                    auxiliary_module=auxiliary_client,
                    clock_module=hermes_time,
                )
                records.append(record)
                print(
                    case["name"],
                    "calls",
                    len(record["summary_requests"]),
                    "outcomes",
                    [step["outcome"] for step in record["steps"]],
                    flush=True,
                )
        source_files = [
            "agent/context_compressor.py",
            "agent/context_compressor_prune.py",
            "agent/context_compressor_summary.py",
            "agent/context_compressor_prellm.py",
            "agent/context_compressor_tail.py",
            "agent/context_compressor_telemetry.py",
            "agent/micro_compaction.py",
            "agent/context_engine.py",
            "agent/model_metadata.py",
        ]
        fixture = {
            "baseline": {
                "repository": "https://github.com/NousResearch/hermes-agent",
                "version": "v0.22.5",
                "commit": commit,
                "source_sha256": {
                    relative: hashlib.sha256(
                        (options.source / relative).read_bytes()
                    ).hexdigest()
                    for relative in source_files
                },
            },
            "method": "Imported actual unmodified ContextCompressor and mixins, executed full/prune/micro/threshold/failure paths. Fixed call_llm I/O and clock; no network. Exact compact message/request projection retains every field and hashes long strings.",
            "boundaries": [
                "No session database bound; durable row transactions/session rotations are not exercised.",
                "Tool output corpora and summary replies are synthetic; no real-model quality claim.",
                "Direct engine execution is not a full conversation-loop/overflow/idle integration oracle.",
            ],
            "cases": records,
        }
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            f"FROZEN {len(records)} actual upstream compression cases -> {options.output}"
        )


if __name__ == "__main__":
    main()
