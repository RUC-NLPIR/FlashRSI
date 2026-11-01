"""Execute original Hermes pricing and empty-guard policies with fixed catalogs.

Run using the upstream-only oracle venv. Only external catalog rows and the
wall clock are fixed; all price resolution, usage normalization and retry
policies execute from the pinned source.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
METADATA = {
    "openrouter": {
        "vendor/fixture": {
            "pricing": {
                "prompt": "0.000003",
                "completion": "0.000015",
                "input_cache_read": "0.0000003",
                "cache_creation": "0.00000375",
                "request": "0.001",
            }
        }
    },
    "endpoints": {
        "https://fixture.example/v1": {
            "fixture": {"pricing": {"prompt": "0.000002", "completion": "0.00001"}}
        }
    },
    "models_dev": {
        "deepseek": {
            "future-fixture": {
                "cost": {
                    "input": 3,
                    "output": 15,
                    "cache_read": 0.3,
                    "cache_write": 3.75,
                }
            }
        }
    },
}


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def generate(source):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == PIN
    )
    sys.path.insert(0, str(source))

    def deny(*args, **kwargs):
        raise RuntimeError("offline pricing oracle prohibits network")

    socket.socket.connect = deny
    socket.create_connection = deny
    from agent import empty_response_guard as guard
    from agent import models_dev
    from agent import usage_pricing as pricing

    def model_info(provider, model):
        raw = METADATA["models_dev"].get(provider, {}).get(model)
        return models_dev._parse_model_info(model, raw, provider) if raw else None

    cases, guards = [], []
    with (
        patch.object(
            pricing, "fetch_model_metadata", return_value=METADATA["openrouter"]
        ),
        patch.object(
            pricing,
            "fetch_endpoint_model_metadata",
            side_effect=lambda base, **kw: METADATA["endpoints"].get(
                base.rstrip("/"), {}
            ),
        ),
        patch.object(models_dev, "get_model_info", model_info),
        patch.object(pricing, "_UTC_NOW", lambda: NOW),
    ):

        def add(
            name, model, provider="", base_url="", raw=None, mode="chat_completions"
        ):
            raw = raw or {"prompt_tokens": 50000, "completion_tokens": 1234}
            usage = pricing.normalize_usage(raw, provider=provider, api_mode=mode)
            route = dict(model_name=model, provider=provider, base_url=base_url)
            cases.append(
                dict(
                    name=name,
                    route=route,
                    raw=raw,
                    mode=mode,
                    usage=plain(usage),
                    expected=plain(
                        pricing.estimate_usage_cost(
                            model, usage, provider=provider, base_url=base_url
                        )
                    ),
                )
            )

        for provider, model in sorted(pricing._OFFICIAL_DOCS_PRICING):
            add(provider + "/" + model, model, provider)
        for tokens in (199999, 200000, 200001, 272000, 272001):
            for provider, model in (
                ("google", "gemini-3.1-pro"),
                ("openai", "gpt-6.1-sol"),
            ):
                add(
                    f"tier/{provider}/{tokens}",
                    model,
                    provider,
                    raw={
                        "prompt_tokens": tokens,
                        "completion_tokens": 1000,
                        "prompt_tokens_details": {
                            "cached_tokens": 1000,
                            "cache_write_tokens": 2000,
                        },
                    },
                )
        add(
            "served_ultrafast",
            "gpt-6.1-sol",
            "openai",
            raw={
                "input_tokens": 300000,
                "output_tokens": 1000,
                "service_tier": "ultrafast",
            },
            mode="codex_responses",
        )
        add(
            "served_ultrafast_unknown",
            "gpt-4o",
            "openai",
            raw={
                "input_tokens": 300000,
                "output_tokens": 1000,
                "service_tier": "ultrafast",
            },
            mode="codex_responses",
        )
        add(
            "served_fast",
            "claude-opus-4.8",
            "anthropic",
            raw={
                "input_tokens": 50000,
                "output_tokens": 1000,
                "cache_read_input_tokens": 5000,
                "cache_creation_input_tokens": 5000,
                "speed": "fast",
            },
            mode="anthropic_messages",
        )
        add(
            "openrouter_fixed_catalog",
            "vendor/fixture",
            "openrouter",
            "https://openrouter.ai/api/v1",
            raw={
                "prompt_tokens": 50000,
                "completion_tokens": 1000,
                "prompt_tokens_details": {
                    "cached_tokens": 5000,
                    "cache_write_tokens": 2000,
                },
            },
        )
        add("endpoint_fixed_catalog", "fixture", "custom", "https://fixture.example/v1")
        add(
            "models_dev_direct",
            "future-fixture",
            "deepseek",
            "https://api.deepseek.com/v1",
        )
        add(
            "models_dev_proxy_unknown",
            "future-fixture",
            "deepseek",
            "https://proxy.example/v1",
        )
        add("included", "gpt-6.1-sol", "openai-codex")
        add("custom_unknown", "gpt-6.1-sol", "custom", "http://localhost:8000/v1")
        add("inferred_openai", "openai/gpt-6.1-sol")
        add("invalid_codex_suffix", "gpt-5.5-900k", "openai")
        add("prefixed_valid_codex_suffix", "openai/gpt-6.1-sol-900k", "openai")
        add(
            "missing_cache_rate",
            "gemini-2.5-pro",
            "google",
            raw={
                "prompt_tokens": 1000,
                "completion_tokens": 1,
                "prompt_tokens_details": {"cache_write_tokens": 500},
            },
        )

        for name, model, provider, raw in [
            (
                "expensive",
                "gpt-6-astra",
                "openai",
                {"prompt_tokens": 100000, "completion_tokens": 1000},
            ),
            (
                "cheap",
                "gpt-6-luna",
                "openai",
                {"prompt_tokens": 100, "completion_tokens": 1},
            ),
            (
                "included",
                "gpt-6-astra",
                "openai-codex",
                {"prompt_tokens": 1000000, "completion_tokens": 10000},
            ),
            (
                "unknown",
                "unknown",
                "custom",
                {"prompt_tokens": 1000000, "completion_tokens": 10000},
            ),
        ]:
            host = SimpleNamespace(
                model=model,
                provider=provider,
                base_url="",
                api_mode="chat_completions",
                _empty_content_retries=0,
            )
            response = SimpleNamespace(usage=raw)
            guard.record_empty_attempt(host, finish_reason="stop", response=response)
            guards.append(
                dict(
                    name=name,
                    model=model,
                    provider=provider,
                    raw=raw,
                    budget=guard.empty_retry_budget(host, response),
                    streak=plain(guard.streak_cost_usd(host)),
                )
            )
    return dict(
        commit=PIN,
        metadata=METADATA,
        cases=cases,
        guards=guards,
        sources={
            p: hashlib.sha256((source / p).read_bytes()).hexdigest()
            for p in ("agent/usage_pricing.py", "agent/empty_response_guard.py")
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("hermes_pricing_upstream.json"),
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-pricing-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        args.output.write_text(
            json.dumps(generate(args.source), indent=2, ensure_ascii=False) + "\n"
        )
