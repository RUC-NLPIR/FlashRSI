"""Execute the pinned original custom-provider helper AST closure offline."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
NAMES = {
    "_normalized_custom_base_url",
    "_custom_provider_model_matches",
    "_custom_provider_extra_body_for_agent",
    "_merge_custom_provider_extra_body",
}


def generate(root):
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        == PIN
    )
    path = root / "agent" / "agent_init.py"
    source = path.read_text()
    functions = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in NAMES
    ]
    assert {node.name for node in functions} == NAMES
    namespace = {"Any": Any, "Optional": Optional}
    closure = ast.Module(body=functions, type_ignores=[])
    exec(compile(closure, str(path), "exec"), namespace)
    base = {
        "base_url": "https://fixture.invalid/v1",
        "extra_body": {"service_tier": "flex", "provider": {"order": ["a"]}},
    }
    cases = []

    def add(name, entries=None, **updates):
        values = {
            "provider": "custom",
            "model": "model-a",
            "base_url": base["base_url"],
            "custom_providers": [copy.deepcopy(base)] if entries is None else entries,
            "request_overrides": {},
            **updates,
        }
        before = copy.deepcopy(values)
        selected = namespace["_custom_provider_extra_body_for_agent"](
            **{
                key: values[key]
                for key in ("provider", "model", "base_url", "custom_providers")
            }
        )
        agent = SimpleNamespace(
            **{
                key: copy.deepcopy(values[key])
                for key in ("provider", "model", "base_url", "request_overrides")
            }
        )
        namespace["_merge_custom_provider_extra_body"](
            agent, values["custom_providers"]
        )
        assert values == before
        cases.append(
            {
                "name": name,
                "input": values,
                "selected": selected,
                "expected": agent.request_overrides,
            }
        )

    add("unnamed_custom_default")
    add("non_custom_ignores_matching_endpoint", provider="openai")
    add(
        "named_custom_matches_name",
        entries=[{**base, "name": "FOO"}],
        provider=" custom:foo ",
    )
    add(
        "named_custom_matches_key",
        entries=[{**base, "provider_key": " FOO "}],
        provider="custom:foo",
    )
    add(
        "named_custom_rejects_other",
        entries=[{**base, "provider_key": "bar"}],
        provider="custom:foo",
    )
    add(
        "url_trims_whitespace_and_slashes",
        base_url=" https://fixture.invalid/v1/// ",
        entries=[{**base, "base_url": " https://fixture.invalid/v1/ "}],
    )
    add("url_case_is_preserved", base_url="https://FIXTURE.invalid/v1")
    add("url_path_mismatch", base_url="https://fixture.invalid/v2")
    add("missing_target_url", base_url="")
    add(
        "invalid_entries_ignored",
        entries=[
            None,
            "entry",
            {},
            {**base, "extra_body": []},
            {**base, "extra_body": {}},
            base,
        ],
    )
    add("empty_entries", entries=[])
    add("specific_model_matches", entries=[{**base, "model": " MODEL-A "}])
    add("specific_model_mismatch", entries=[{**base, "model": "model-b"}])
    add(
        "first_fallback_retained",
        entries=[
            {**base, "extra_body": {"first": True}},
            {**base, "extra_body": {"second": True}},
        ],
    )
    add(
        "specific_model_beats_prior_fallback",
        entries=[base, {**base, "model": "model-a", "extra_body": {"specific": True}}],
    )
    add(
        "first_specific_model_wins",
        entries=[
            {**base, "model": "model-a", "extra_body": {"first": True}},
            {**base, "model": "model-a", "extra_body": {"second": True}},
        ],
    )
    for models in (["model-a"], {"model-a": {}}, ("model-a",)):
        add(
            "catalog_match_" + type(models).__name__,
            entries=[{**base, "model": "model-b", "models": models}],
        )
    add(
        "models_only_remains_fallback_per_source",
        entries=[{**base, "models": ["different"]}],
    )
    add(
        "explicit_extra_body_wins_shallow",
        request_overrides={
            "temperature": 0.2,
            "extra_body": {
                "service_tier": "priority",
                "provider": {"only": ["b"]},
                "seed": 42,
            },
        },
    )
    add("empty_explicit_body_keeps_defaults", request_overrides={"extra_body": {}})
    add(
        "non_mapping_explicit_body_replaced_with_defaults",
        request_overrides={"extra_body": None},
    )
    add(
        "explicit_only_without_defaults",
        entries=[],
        request_overrides={"extra_body": {"service_tier": "priority"}, "seed": 1},
    )
    return {
        "baseline": "v0.22.5@" + PIN,
        "method": "Unmodified four-function AST closure from original agent/agent_init.py; explicit arguments only, no imports/config/network/model calls.",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "functions": {
            node.name: {"line": node.lineno, "end_line": node.end_lineno}
            for node in functions
        },
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    print(json.dumps(generate(parser.parse_args().source), indent=2))
