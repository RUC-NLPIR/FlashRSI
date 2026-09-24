"""Reading a Worker's reply back in the shape the algorithm's prompt asked for."""

import pytest

from flashrsi.algorithms._replies import fenced, tagged


def test_a_bracketed_value_is_read_out_of_the_reply():
    assert tagged("Sure:\n<INS>Use evidence.</INS>", "INS") == "Use evidence.\n"
    assert tagged("<p>\nLine one\nLine two\n</p>", "p") == "Line one\nLine two\n"
    # An untagged reply is what a provider that simply answered produces.
    assert tagged("no tag at all", "INS") == "no tag at all\n"
    assert tagged("<INS></INS>", "INS") == ""


def test_an_echoed_request_is_not_read_from_its_own_worked_example():
    """Upstream templates show the bracketing in an example of their own."""
    echoed = "1. <INS>the example from the request</INS>\n2. <INS>the real one</INS>"

    assert tagged(echoed, "INS") == "the real one\n"


def test_a_fenced_value_is_read_after_a_provider_preamble():
    assert fenced("Here it is:\n```text\nUse evidence.\n```\n") == "Use evidence.\n"
    assert fenced("```Verify inline.```") == "Verify inline.\n"
    assert fenced("```\nLine one\nLine two\n```") == "Line one\nLine two\n"
    assert fenced("no fence at all") == "no fence at all\n"
    assert fenced("```\n\n```") == ""


def test_a_dangling_fence_in_an_echoed_request_is_not_a_block():
    """The prompt's own closing sentence ends in a lone ``` marker.

    A provider that quotes the request back after answering leaves an odd
    marker trailing the real block; pairing fences from the left keeps the
    answer, while taking the last two markers would return the echoed request.
    """
    reply = (
        "```\nAlways cite the source.\n```\n"
        "Provide the new instructions within ``` blocks."
    )

    assert fenced(reply) == "Always cite the source.\n"


@pytest.mark.parametrize("read", [lambda text: tagged(text, "INS"), fenced])
def test_both_readers_return_plain_text(read):
    """No wrapper type: an algorithm gets a str and writes it to a file."""
    assert type(read("plain answer")) is str
