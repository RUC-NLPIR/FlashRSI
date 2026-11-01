import json
from pathlib import Path

import pytest

from flashrsi.agents.pi_agent.runtime.pi_native.ignore import IgnoreRules

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/pi_ignore_upstream.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_ignore_matches_executed_original_dependency(case, tmp_path):
    for name, content in case["files"].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    matcher = IgnoreRules(tmp_path, ignore_case=True, prefix_rules=True)
    assert {
        name: matcher.is_ignored(name, is_dir=False) for name in case["paths"]
    } == case["expected"]
