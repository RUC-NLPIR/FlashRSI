"""Reading a Worker's reply back, in the shape the prompt asked for.

An algorithm's own prompt decides how the answer is wrapped: OPRO's meta-prompt
asks for the instruction inside ``<INS>`` tags, GEPA's reflection asks for it in
a code fence, AHE's Evolve Agent brackets its manifest. Unwrapping it therefore
belongs beside the prompts that ask for it, not on the Agent that answered --
the harness did not choose the format and cannot know it.

Both take the last *closed* pair: upstream templates show the bracketing in a
worked example of their own, so a reply that quotes the request back would
otherwise be read from that example. The text usually becomes a file's whole
content, so it ends with a newline.
"""

from __future__ import annotations

import re


def tagged(reply: str, tag: str) -> str:
    """Read the value a prompt asked to be bracketed in ``tag``.

    An untagged reply is taken whole, which is what a provider that simply
    answered produces.
    """
    found = re.findall(f"<{tag}>(.*?)</{tag}>", reply, flags=re.DOTALL)
    return _text(found[-1] if found else reply)


def fenced(reply: str) -> str:
    """Read the value a prompt asked to be put in a code fence.

    Closed matters here: the sentence asking for one ends in a lone fence of
    its own. An opening fence may carry a language tag -- one word on its own
    line, which is what tells it apart from prose that began on the fence line.
    """
    blocks = reply.split("```")
    closed = range(1, len(blocks) - 1, 2)
    if not closed:
        return _text(reply)
    body = blocks[closed[-1]]
    tag, newline, rest = body.partition("\n")
    return _text(rest if newline and len(tag.split()) <= 1 else body)


def _text(value: str) -> str:
    stripped = value.strip()
    return stripped + "\n" if stripped else stripped


__all__ = ["fenced", "tagged"]
