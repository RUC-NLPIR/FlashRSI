"""Original Hermes routing resolver with an explicit, isolated config boundary.

Only load_config_readonly is replaced with the fixture's in-memory settings;
the pinned original model matching, validation and merging execute unchanged.
"""

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

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
FIELDS = {
    "only": "providers_allowed",
    "ignore": "providers_ignored",
    "order": "providers_order",
    "sort": "provider_sort",
    "require_parameters": "provider_require_parameters",
    "data_collection": "provider_data_collection",
}


def generate(source):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        == PIN
    )
    sys.path.insert(0, str(source))
    logging.disable(logging.CRITICAL)

    def deny(*args, **kwargs):
        raise RuntimeError("Offline routing oracle prohibits network")

    socket.create_connection = socket.socket.connect = deny
    from agent.chat_completion_helpers import _provider_preferences_for_agent
    from hermes_cli import config

    cases = [
        {"name": "empty"},
        {
            "name": "all_flat",
            "settings": {
                "provider_routing": {
                    "only": ["a"],
                    "ignore": ["b"],
                    "order": ["c"],
                    "sort": " LATENCY ",
                    "require_parameters": True,
                    "data_collection": "deny",
                }
            },
        },
        {
            "name": "falsy_omitted",
            "settings": {
                "provider_routing": {
                    "only": [],
                    "ignore": None,
                    "sort": "",
                    "require_parameters": False,
                    "data_collection": "",
                }
            },
        },
        *(
            {"name": f"sort_{label}", "settings": {"provider_routing": {"sort": value}}}
            for label, value in (
                ("price", "price"),
                ("throughput", "THROUGHPUT"),
                ("invalid", "quality"),
                ("integer", 2),
                ("mapping", {"by": "price"}),
            )
        ),
        {
            "name": "exact_model_overlay",
            "settings": {
                "provider_routing": {
                    "only": ["base"],
                    "sort": "price",
                    "models": {
                        "openai/gpt-5.4": {
                            "only": ["model"],
                            "require_parameters": True,
                            "unrelated": "ignored",
                        }
                    },
                }
            },
        },
        {
            "name": "dashed_model_overlay",
            "settings": {
                "provider_routing": {"models": {"gpt-5-4": {"order": ["matching"]}}}
            },
        },
        {
            "name": "aggregator_model_overlay",
            "model": "openrouter/anthropic/claude-sonnet-4.6",
            "settings": {
                "provider_routing": {
                    "models": {"anthropic/claude-sonnet-4-6": {"only": ["anthropic"]}}
                }
            },
        },
        {
            "name": "model_false_removes_global",
            "settings": {
                "provider_routing": {
                    "only": ["global"],
                    "require_parameters": True,
                    "models": {"gpt-5.4": {"only": [], "require_parameters": False}},
                }
            },
        },
        {
            "name": "invalid_per_model_sort_removes_global",
            "settings": {
                "provider_routing": {
                    "sort": "latency",
                    "models": {"gpt-5.4": {"sort": "not-valid"}},
                }
            },
        },
        {
            "name": "nonmatching_model_keeps_global",
            "settings": {
                "provider_routing": {
                    "only": ["global"],
                    "models": {"other": {"only": ["other"]}},
                }
            },
        },
        {
            "name": "route_routing_overrides_flat",
            "settings": {"provider_routing": {"only": ["global"]}},
            "route": {"provider_routing": {"only": ["route"], "sort": "price"}},
        },
        {
            "name": "constructor_aliases",
            "settings": {
                "provider_routing": {"only": ["global"]},
                "providers_allowed": ["constructor"],
            },
            "route": {"providers_allowed": ["route-constructor"]},
        },
        {
            "name": "explicit_preferences_win",
            "settings": {
                "provider_routing": {"only": ["global"], "sort": "price"},
                "provider_preferences": {"only": ["settings"]},
            },
            "route": {
                "provider_preferences": {"only": ["route"], "max_price": {"prompt": 1}}
            },
        },
        {
            "name": "malformed_settings_ignored",
            "settings": {"provider_routing": "wrong"},
        },
    ]
    results = []
    original = config.load_config_readonly
    try:
        for case in cases:
            settings, route = (
                copy.deepcopy(case.get("settings", {})),
                copy.deepcopy(case.get("route", {})),
            )
            routing = settings.get("provider_routing") or {}
            routing = dict(routing) if isinstance(routing, dict) else {}
            if isinstance(route.get("provider_routing"), dict):
                routing.update(route["provider_routing"])
            attrs = {
                name: route.get(name, settings.get(name, routing.get(key)))
                for key, name in FIELDS.items()
            }
            agent = SimpleNamespace(model=case.get("model", "openai/gpt-5.4"), **attrs)
            config.load_config_readonly = lambda: {"provider_routing": routing}
            expected = _provider_preferences_for_agent(agent)
            for explicit in (
                settings.get("provider_preferences"),
                route.get("provider_preferences"),
            ):
                if isinstance(explicit, dict):
                    expected.update(explicit)
            results.append(
                {
                    "input": {
                        "name": case["name"],
                        "settings": settings,
                        "route": route,
                        "model": agent.model,
                    },
                    "expected": expected,
                }
            )
    finally:
        config.load_config_readonly = original
    paths = ("agent/chat_completion_helpers.py", "hermes_constants.py")
    return {
        "commit": PIN,
        "method": "Actual original _provider_preferences_for_agent; original validation/model resolution; host config replaced only with explicit fixture settings. No HTTP or model requests.",
        "source_sha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in paths
        },
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hermes-routing-oracle-") as home:
        os.environ["HERMES_HOME"] = home
        print(json.dumps(generate(args.source), indent=2))
