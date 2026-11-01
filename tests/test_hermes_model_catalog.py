"""Original metadata queries against the same captured public catalog bytes."""

import dataclasses
import json
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native import model_catalog
from flashrsi.agents.hermes.runtime.hermes_native.compression import (
    resolve_context_length,
)

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/hermes_catalog_upstream.json").read_text()
)


def plain(value):
    return json.loads(json.dumps(dataclasses.asdict(value))) if value else None


@pytest.mark.parametrize(
    "case", REFERENCE["cases"], ids=lambda case: case["provider"]+"/"+case["model"]
)
def test_capabilities_and_context_match_actual_original(case):
    args = (case["provider"], case["model"], case["settings"])
    assert plain(model_catalog.model_capabilities(*args)) == case["caps"]
    assert plain(model_catalog.model_info(*args)) == case["info"]
    assert model_catalog.context_length(*args) == case["context"]
    expected = case["vision_override"]
    if expected is None:
        expected = case["caps"]["supports_vision"] is True if case["caps"] else False
    assert model_catalog.supports_vision(
        {"provider": case["provider"], "model_name": case["model"]}, case["settings"]
    ) is expected


def test_context_pipeline_uses_override_then_route_then_catalog():
    route = {"provider": "openai", "model_name": "gpt-4o", "base_url": "https://api.openai.com/v1"}
    assert resolve_context_length({}, route) == 128000
    assert resolve_context_length({"context_length": 11111}, route) == 11111
    assert resolve_context_length({"model_overrides": {"openai": {"gpt-4o": {"context_window": 22222}}}}, route) == 22222
    assert resolve_context_length({"custom_providers": [
        {"base_url": "https://other.example/v1", "models": {"gpt-4o": {"context_length": 33333}}},
        {"base_url": "https://api.openai.com/v1/", "models": {"gpt-4o": {"context_length": 44444}}},
    ]}, route) == 44444


def test_explicit_catalog_and_boolean_vision_overrides_are_isolated():
    route = {"provider": "openai", "model_name": "gpt-4o"}
    assert model_catalog.supports_vision(route, {}) is True
    assert model_catalog.supports_vision(route, {"models_dev_catalog": {}}) is False
    assert model_catalog.supports_vision(route, {"model": {"supports_vision": "false"}}) is False
    assert model_catalog.supports_vision(route, {}) is True
