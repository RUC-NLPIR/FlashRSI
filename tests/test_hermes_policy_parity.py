"""Compare native helpers with executed original Hermes v0.22.5 policy code.

The frozen oracle was generated from AST-selected original declarations with
stdlib globals, without rewriting function bodies. It covers individual policy
decisions, not the entire upstream run_conversation loop or provider behavior.
Source files and executed selections are SHA-256 recorded in the fixture.
"""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "hermes_policy_upstream.json").read_text()
)


@pytest.fixture(scope="module")
def policy():
    # Load the pure policy module directly so this component oracle does not
    # depend on optional adapter, transport, or tool initialization.
    path = (
        Path(__file__).parents[1]
        / "flashrsi/agents/hermes/runtime/hermes_native/policy.py"
    )
    spec = importlib.util.spec_from_file_location("hermes_policy_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case", _ORACLE["cases"], ids=lambda case: case["name"])
def test_hermes_policy_matches_executed_upstream(case, policy):
    args = copy.deepcopy(case["args"])
    helper = case["helper"]
    if helper == "strip_think_blocks":
        actual = policy.strip_think_blocks(None, *args)
    elif helper == "repair_tool_call":
        actual = policy.repair_tool_call(
            SimpleNamespace(valid_tool_names=set(args[1])), args[0]
        )
    elif helper == "_deduplicate_tool_calls":
        calls = [
            SimpleNamespace(
                id=item["id"],
                function=SimpleNamespace(
                    name=item["name"], arguments=item["arguments"]
                ),
            )
            for item in args[0]
        ]
        result = policy._deduplicate_tool_calls(calls)
        assert (result is calls) == case["returns_original_list"]
        actual = [item.id for item in result]
    elif helper == "MAX_ITERATIONS_SUMMARY_REQUEST":
        actual = policy.MAX_ITERATIONS_SUMMARY_REQUEST
    else:
        actual = getattr(policy, helper)(*args)
    assert actual == case["expected"]
