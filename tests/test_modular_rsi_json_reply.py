import json

import pytest

from flashrsi.algorithms.modular_rsi import _json_reply


@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```", "```\n{}\n```"])
@pytest.mark.parametrize(
    "value",
    [
        {
            "accept": False,
            "reason": "Reject rewriting '```python\\n# comment\\nprint(1)\\n```'.",
        },
        [
            {
                "target": "runtime/agent.py",
                "task_ids": ["e0"],
                "rationale": "Preserve ``` inside JSON strings.",
                "change": "Keep interfaces.",
            }
        ],
        [],
    ],
)
def test_json_reply_preserves_backticks_inside_strings(wrapper, value):
    assert _json_reply(wrapper.format(json.dumps(value))) == value


@pytest.mark.parametrize(
    "reply",
    ["", "not JSON", "```json\n{}", "```json\n{}\n```\ntrailing prose", "{} {}"],
)
def test_json_reply_does_not_repair_invalid_json(reply):
    with pytest.raises(json.JSONDecodeError):
        _json_reply(reply)


def test_json_reply_does_not_coerce_object_to_findings_list():
    value = {"target": "runtime/agent.py"}
    assert _json_reply(json.dumps(value)) == value
