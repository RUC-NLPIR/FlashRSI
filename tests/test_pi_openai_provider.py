"""Compare full supported OpenAI request bodies with original Pi source output."""

import copy
import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.openai_provider import build_payload

_ORACLE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "pi_openai_provider_upstream.json"
    ).read_text()
)


@pytest.mark.parametrize(
    "case", _ORACLE["cases"], ids=lambda case: case["input"]["name"]
)
def test_openai_provider_payload_matches_original_pi(case):
    source = case["input"]
    context = copy.deepcopy(source["context"])
    actual, _ = build_payload(
        source["config"], context, source["api"], source["reasoning"]
    )
    expected = copy.deepcopy(case["expected"]["payload"])
    # Production deliberately uses complete JSON HTTP responses; per-session
    # prompt cache identity is independent from the semantic request contract.
    for key in ("stream", "stream_options", "prompt_cache_key"):
        expected.pop(key, None)
        actual.pop(key, None)
    assert actual == expected
    assert context == source["context"]


def test_openai_oracle_captured_before_http_dispatch():
    assert _ORACLE["fetchCalls"] == 0
    assert _ORACLE["release"] == {"@earendil-works/pi-ai": "1.4.0"}
