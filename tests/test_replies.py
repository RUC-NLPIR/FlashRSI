import pytest

from flashrsi.algorithms._replies import tagged


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("plain reply", "plain reply\n"),
        ("<EDITS>first</EDITS> <EDITS>last</EDITS>", "last\n"),
        ("Mention `<EDITS>` first.\n<EDITS>valid</EDITS>", "valid\n"),
        ("<EDITS>valid</EDITS> unfinished <EDITS>", "valid\n"),
        ("<EDITS>valid</EDITS> orphan </EDITS>", "valid\n"),
        ("<EDITS>first</EDITS> mention <EDITS> then <EDITS>last</EDITS>", "last\n"),
        ("<EDITS> \n </EDITS>", ""),
    ],
)
def test_tagged_uses_last_complete_block(reply, expected):
    assert tagged(reply, "EDITS") == expected
