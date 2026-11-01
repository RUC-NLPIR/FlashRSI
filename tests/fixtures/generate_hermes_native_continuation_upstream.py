"""Execute pinned original incomplete-continuation logic with explicit host I/O.

  /tmp/hermes-loop-oracle-venv/bin/python tests/fixtures/generate_hermes_native_continuation_upstream.py /tmp/hermes-agent-v0.22.5-source

The real turn_truncation and StreamDeliveryMixin run unmodified. Inputs are
prepared assistant messages (the post-normalization boundary), no fallback is
configured, display/persistence callbacks record in memory, and wall time is fixed.
No FlashRSI code is imported and network connections are prohibited.
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
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
NOW = 1700000000.0


def message(content="", reasoning=None, **sidecars):
    return {
        "role": "assistant",
        "content": content,
        "reasoning": reasoning,
        "finish_reason": "incomplete",
        **sidecars,
    }


def step(assistant, *, status="completed", reason=None, output_tokens=None):
    return {
        "assistant": assistant,
        "response_status": status,
        "incomplete_reason": reason,
        "usage": {"output_tokens": output_tokens}
        if output_tokens is not None
        else None,
    }


def cases():
    def reasoning(text="planning", blob="opaque"):
        return message(
            reasoning=text,
            codex_reasoning_items=[
                {"type": "reasoning", "id": "rs_a", "encrypted_content": blob}
            ],
        )

    checkpoint = {"type": "compaction", "encrypted_content": "checkpoint-old"}

    def commentary(text, phase="commentary"):
        return [
            {
                "type": "message",
                "role": "assistant",
                "phase": phase,
                "content": [{"type": "output_text", "text": text}],
            }
        ]

    user = [
        {"role": "user", "content": "Complete the requested work.", "timestamp": 100.0}
    ]
    result = []

    def add(name, steps, *, cap=2000, initial=None, state=None):
        result.append(
            {
                "name": name,
                "configured_cap": cap,
                "initial_messages": copy.deepcopy(user if initial is None else initial),
                "initial_state": state
                or {"incomplete_retries": 0, "reasoning_only_streak": 0},
                "steps": steps,
            }
        )

    add(
        "three_visible_partials_end_aggregate",
        [
            step(message(text))
            for text in ("First partial.", "Second partial.", "Third partial.")
        ],
    )
    add(
        "empty_responses_preserve_user_alternation", [step(message()) for _ in range(3)]
    )
    add(
        "plaintext_reasoning_nudges_first_retry",
        [step(message(reasoning="Planning internally.")) for _ in range(3)],
    )
    add(
        "opaque_reasoning_bare_then_nudge",
        [step(reasoning(blob=f"opaque-{n}")) for n in range(3)],
    )
    add(
        "mixed_partial_then_three_reasoning_streak",
        [
            step(message("Visible progress.")),
            *[step(reasoning(blob=f"opaque-{n}")) for n in range(3)],
        ],
    )
    add(
        "two_partials_then_streak_exceeds_aggregate",
        [
            step(message("First progress.")),
            step(message("Next progress.")),
            *[step(reasoning(blob=f"opaque-{n}")) for n in range(3)],
        ],
    )
    add(
        "visible_partial_resets_reasoning_streak",
        [
            step(reasoning(blob="one")),
            step(reasoning(blob="two")),
            step(message("Visible progress resets the streak.")),
        ],
    )
    add(
        "duplicate_visible_merges_checkpoint",
        [
            step(
                message("Working.", "private one", codex_reasoning_items=[checkpoint])
            ),
            step(
                message(
                    "Working.",
                    "private two",
                    codex_reasoning_items=[
                        {"type": "reasoning", "encrypted_content": "new reasoning"}
                    ],
                )
            ),
        ],
    )
    add(
        "duplicate_visible_new_checkpoint_wins",
        [
            step(message("Working.", codex_reasoning_items=[checkpoint])),
            step(
                message(
                    "Working.",
                    codex_reasoning_items=[
                        {"type": "compaction", "encrypted_content": "checkpoint-new"}
                    ],
                )
            ),
        ],
    )
    add(
        "structured_commentary_controls_visible_dedup",
        [
            step(
                message(
                    "partial answer A",
                    codex_message_items=commentary("Inspecting now."),
                )
            ),
            step(
                message(
                    "partial answer B",
                    codex_message_items=commentary("Inspecting now."),
                )
            ),
        ],
    )
    add(
        "hidden_analysis_does_not_replace_visible_content",
        [
            step(
                message(
                    "partial A", codex_message_items=commentary("hidden", "analysis")
                )
            ),
            step(
                message(
                    "partial B", codex_message_items=commentary("hidden", "analysis")
                )
            ),
        ],
    )
    add(
        "reasoning_budget_doubles_configured_cap",
        [
            step(
                reasoning(blob=str(n)),
                status="incomplete",
                reason="max_output_tokens",
                output_tokens=2000,
            )
            for n in range(3)
        ],
    )
    add(
        "observed_ceiling_seeds_unconfigured_cap",
        [
            step(
                reasoning(blob=str(n)),
                status="incomplete",
                reason="max_output_tokens",
                output_tokens=6000,
            )
            for n in range(2)
        ],
        cap=None,
    )
    add(
        "missing_ceiling_uses_4096_seed",
        [step(reasoning(), status="incomplete", reason="length")],
        cap=None,
    )
    add(
        "high_cap_boost_is_bounded",
        [
            step(
                reasoning(blob=str(n)),
                status="incomplete",
                reason="max_output_tokens",
                output_tokens=20000,
            )
            for n in range(2)
        ],
        cap=20000,
    )
    add(
        "visible_budget_partial_does_not_disable_reasoning",
        [
            step(
                message("Visible partial."),
                status="incomplete",
                reason="max_output_tokens",
                output_tokens=2000,
            )
        ],
    )
    add(
        "nonbudget_incomplete_does_not_escalate",
        [
            step(
                reasoning(),
                status="incomplete",
                reason="content_filter",
                output_tokens=2000,
            )
        ],
    )
    add(
        "opaque_checkpoint_only_gets_nudge_on_second",
        [step(message(codex_reasoning_items=[checkpoint])) for _ in range(2)],
    )
    return result


def generate(source):
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if actual != PIN:
        raise RuntimeError(f"Wrong source commit: {actual}")
    sys.path.insert(0, str(source))

    def deny_network(*args, **kwargs):
        raise RuntimeError("Original continuation oracle prohibits network")

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    logging.disable(logging.CRITICAL)
    from agent import agent_runtime_helpers, message_metadata, turn_truncation
    from agent.stream_delivery import StreamDeliveryMixin

    class Host(StreamDeliveryMixin):
        api_mode = "codex_responses"
        quiet_mode = True
        show_commentary = True

        def __init__(self, case):
            self._codex_incomplete_retries = case["initial_state"]["incomplete_retries"]
            self._codex_reasoning_only_streak = case["initial_state"][
                "reasoning_only_streak"
            ]
            self.max_tokens = case["configured_cap"]
            self.emitted = []

        def _build_assistant_message(self, assistant, finish_reason):
            prepared = copy.deepcopy(self.prepared)
            prepared["finish_reason"] = finish_reason
            return prepared

        def _strip_think_blocks(self, text):
            return agent_runtime_helpers.strip_think_blocks(None, text)

        def _emit_interim_assistant_message(self, msg):
            self.emitted.append(copy.deepcopy(msg))

        def _try_activate_fallback(self, **kwargs):
            return False

        def _emit_diagnostic_wait(self, text):
            pass

        def _persist_session(self, messages, conversation_history):
            pass

    evidence = []
    with patch.object(message_metadata, "wall_time", return_value=NOW):
        for case in cases():
            host = Host(case)
            messages = copy.deepcopy(case["initial_messages"])
            trace = []
            for index, request in enumerate(case["steps"], 1):
                host.prepared = request["assistant"]
                host.emitted = []
                host._ephemeral_reasoning_off = False
                host._ephemeral_max_output_tokens = None
                result = turn_truncation.continue_codex_incomplete(
                    host,
                    SimpleNamespace(**request["assistant"]),
                    "incomplete",
                    messages=messages,
                    conversation_history=None,
                    api_call_count=index,
                    response=SimpleNamespace(
                        status=request["response_status"],
                        incomplete_details={"reason": request["incomplete_reason"]},
                        usage=request["usage"],
                    ),
                )
                trace.append(
                    {
                        "continue_turn": result is None,
                        "result": copy.deepcopy(result),
                        "max_output_tokens": host._ephemeral_max_output_tokens,
                        "reasoning_off": host._ephemeral_reasoning_off,
                        "emitted": copy.deepcopy(host.emitted),
                        "messages": copy.deepcopy(messages),
                        "state": {
                            "incomplete_retries": host._codex_incomplete_retries,
                            "reasoning_only_streak": host._codex_reasoning_only_streak,
                        },
                    }
                )
            evidence.append({**case, "trace": trace})
    sources = [
        "agent/turn_truncation.py",
        "agent/turn_response_check.py",
        "agent/stream_delivery.py",
        "agent/conversation_loop.py",
        "agent/native_compaction.py",
        "agent/message_metadata.py",
        "agent/agent_runtime_helpers.py",
    ]
    return {
        "upstream_repository": "https://github.com/NousResearch/hermes-agent",
        "upstream_commit": PIN,
        "generation": "Actual original continue_codex_incomplete, budget helper, finish classifier, StreamDeliveryMixin visible selection and checkpoint merge; prepared assistant-message boundary, no fallback, fixed clock, in-memory display/persistence. No FlashRSI code or HTTP.",
        "fixed_wall_time": NOW,
        "source_sha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in sources
        },
        "cases": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_native_continuation_upstream.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-continuation-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        os.environ["HERMES_SKIP_DOTENV"] = "1"
        args.output.write_text(
            json.dumps(generate(args.checkout.resolve()), ensure_ascii=False, indent=2)
            + "\n"
        )
    print(args.output)
