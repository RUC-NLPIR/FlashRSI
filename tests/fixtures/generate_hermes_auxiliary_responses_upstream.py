"""Execute actual pinned Hermes auxiliary Responses helpers, with network disabled.

Reproduce using /tmp/hermes-loop-oracle-venv/bin/python THIS_FILE SOURCE_DIR.
"""

from __future__ import annotations

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


def namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: namespace(item) for key, item in value.items()})
    return [namespace(item) for item in value] if isinstance(value, list) else value


def plain(value):
    if isinstance(value, SimpleNamespace):
        return {key: plain(item) for key, item in vars(value).items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def generate(source):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
    )
    sys.path.insert(0, str(source))

    def denied(*args, **kwargs):
        raise RuntimeError("Auxiliary oracle prohibits network")

    socket.create_connection = denied
    socket.socket.connect = denied
    logging.disable(logging.CRITICAL)
    from agent.auxiliary_client import _CodexCompletionsAdapter
    from agent.auxiliary_codex_response import _parse_codex_final_response

    builds = []
    for name, base, extra in [
        (
            "openai_default_omits_cap_temperature_reasoning",
            "https://api.openai.com/v1",
            {},
        ),
        ("codex_default_uses_typed_parts", "https://chatgpt.com/backend-api/codex", {}),
        (
            "explicit_reasoning_high",
            "https://api.openai.com/v1",
            {"reasoning": {"enabled": True, "effort": "high"}},
        ),
        (
            "explicit_reasoning_none",
            "https://api.openai.com/v1",
            {"reasoning": {"enabled": False, "effort": "none"}},
        ),
        (
            "explicit_priority_tier",
            "https://api.openai.com/v1",
            {"service_tier": "priority"},
        ),
    ]:
        payload = {
            "model": "gpt-5.6",
            "messages": [
                {"role": "system", "content": "Summarize preserved constraints."},
                {"role": "user", "content": "Prior work"},
            ],
            "max_tokens": 1500,
            "temperature": 0.1,
            "extra_body": extra,
        }
        fake = SimpleNamespace(base_url=base)
        result, model, timeout = _CodexCompletionsAdapter(
            fake, "gpt-5.6"
        )._build_responses_kwargs(payload)
        builds.append(
            {
                "name": name,
                "base_url": base,
                "payload": payload,
                "result": result,
                "model": model,
                "timeout": timeout,
            }
        )
    normalizations = []
    for status, reason in [
        ("completed", None),
        ("incomplete", "max_output_tokens"),
        ("incomplete", "content_filter"),
        ("incomplete", "other"),
    ]:
        response = {
            "status": status,
            "incomplete_details": {"reason": reason},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "partial"}],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        }
        result = _parse_codex_final_response(
            namespace(response),
            issuer_kind="other:https://api.openai.com/v1",
            issuer_model="gpt-5.6",
        )
        normalizations.append(
            {
                "name": f"{status}:{reason}",
                "response": response,
                "result": plain(result),
            }
        )
    return {
        "upstream_commit": "bf0203a794a07aac3ff764972ab9087baa4e4f4e",
        "generation": "Actual original module execution, no FlashRSI imports or semantic substitutes; network prohibited.",
        "source_sha256": {
            path: hashlib.sha256((source / path).read_bytes()).hexdigest()
            for path in (
                "agent/auxiliary_client.py",
                "agent/auxiliary_codex_response.py",
            )
        },
        "build": builds,
        "normalize": normalizations,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="hermes-aux-oracle-") as isolated:
        os.environ["HERMES_HOME"] = isolated
        result = generate(Path(sys.argv[1]).resolve())
        Path(__file__).with_name("hermes_auxiliary_responses_upstream.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
