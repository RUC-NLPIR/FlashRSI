"""Original provider-routing policy with explicit Snapshot configuration."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.hermes.runtime.hermes_native.upstream_chat.configuration import (
    resolve_provider_preferences,
)

ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures/hermes_routing_configuration_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda row: row["input"]["name"])
def test_snapshot_routing_matches_actual_original_source(case):
    source = case["input"]
    settings, route = copy.deepcopy(source["settings"]), copy.deepcopy(source["route"])
    assert (
        resolve_provider_preferences(settings, route, source["model"])
        == case["expected"]
    )
    assert settings == source["settings"]
    assert route == source["route"]


def test_routing_oracle_is_pinned_and_explicit():
    assert ORACLE["commit"] == "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
    assert "Actual original" in ORACLE["method"]
    assert set(ORACLE["source_sha256"]) == {
        "agent/chat_completion_helpers.py",
        "hermes_constants.py",
    }
