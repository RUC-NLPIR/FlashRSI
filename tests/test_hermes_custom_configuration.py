"""Custom-provider config selection compared with actual pinned source output."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.upstream_chat.custom_configuration import (
    _custom_provider_extra_body_for_agent,
    resolve_extra_body_overrides,
)

ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "hermes_custom_configuration_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["name"])
def test_custom_provider_selection_and_merge_match_original_source(case):
    source = copy.deepcopy(case["input"])
    assert (
        _custom_provider_extra_body_for_agent(
            **{
                key: source[key]
                for key in ("provider", "model", "base_url", "custom_providers")
            }
        )
        == case["selected"]
    )
    # Empty URLs are preserved by the source helper. The public boundary uses
    # the same default URL as prepare_chat for an absent/empty explicit route.
    actual = resolve_extra_body_overrides(
        {
            "custom_providers": source["custom_providers"],
            "request_overrides": source["request_overrides"],
        },
        {"provider": source["provider"], "base_url": source["base_url"]},
        source["model"],
    )
    assert actual == case["expected"]
    assert source == case["input"]


def test_explicit_snapshot_boundary_precedence_and_input_isolation():
    settings = {
        "custom_providers": [
            {
                "base_url": "https://fixture.invalid/v1",
                "extra_body": {
                    "service_tier": "flex",
                    "defaults": True,
                    "nested": {"original": True},
                },
            }
        ],
        "request_overrides": {
            "temperature": 0.1,
            "seed": 1,
            "extra_body": {
                "service_tier": "default",
                "settings": True,
                "nested": {"settings": True},
            },
        },
    }
    route = {
        "provider": "custom",
        "base_url": "https://fixture.invalid/v1",
        "extra_body": {
            "service_tier": "priority",
            "route": True,
            "nested": {"route": True},
        },
        "request_overrides": {
            "temperature": 0.2,
            "extra_body": {"service_tier": "fast", "explicit": True},
        },
    }
    before = copy.deepcopy((settings, route))
    actual = resolve_extra_body_overrides(settings, route, "model-a")
    assert actual == {
        "temperature": 0.2,
        "seed": 1,
        "extra_body": {
            "service_tier": "fast",
            "defaults": True,
            "settings": True,
            "route": True,
            "explicit": True,
            "nested": {"route": True},
        },
    }
    actual["extra_body"]["nested"]["route"] = False
    assert (settings, route) == before


def test_route_explicit_custom_provider_catalog_overrides_saved_catalog():
    settings = {
        "custom_providers": [
            {
                "base_url": "https://fixture.invalid/v1",
                "extra_body": {"service_tier": "flex"},
            }
        ]
    }
    route = {
        "provider": "custom",
        "base_url": "https://fixture.invalid/v1",
        "custom_providers": [
            {
                "base_url": "https://fixture.invalid/v1",
                "extra_body": {"service_tier": "priority"},
            }
        ],
    }
    assert resolve_extra_body_overrides(settings, route, "model-a") == {
        "extra_body": {"service_tier": "priority"}
    }


def test_oracle_is_exact_original_helper_closure_without_ambient_state():
    assert ORACLE["baseline"] == "v0.22.5@bf0203a794a07aac3ff764972ab9087baa4e4f4e"
    assert ORACLE["functions"]["_custom_provider_extra_body_for_agent"]["line"] == 274
    assert ORACLE["functions"]["_merge_custom_provider_extra_body"]["line"] == 308
