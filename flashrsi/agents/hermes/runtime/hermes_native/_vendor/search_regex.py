"""Ripgrep-compatible regex boundary backed by the Rust regex Python library.

Only this Python extension dependency supplies the regex engine. No rg/Node/npm
process is invoked, and unsupported Rust syntax is never retried with Python re.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from regex_rs import Regex, RegexError, escape


class SearchRegexError(ValueError):
    pass


@dataclass(frozen=True)
class Match:
    span: tuple[int, int]

    def start(self):
        return self.span[0]

    def end(self):
        return self.span[1]


class SearchRegex:
    def __init__(self, engine):
        self.engine = engine

    def search(self, content: str):
        found = self.engine.find(content)
        return Match(found.span) if found is not None else None

    def finditer(self, content: str):
        return (Match(match.span) for match in self.engine.find_iter(content))


@lru_cache(maxsize=256)
def compile_search(pattern: str, *, ignore_case=False, literal=False, multiline=False):
    if not multiline and (
        "\n" in pattern or (not literal and re.search(r"(?<!\\)(?:\\\\)*\\n", pattern))
    ):
        raise SearchRegexError(
            'rg: the literal "\\n" is not allowed in a regex\n\n'
            "Consider enabling multiline mode with the --multiline flag (or -U for short).\n"
            "When multiline mode is enabled, new line characters can be matched."
        )
    source = escape(pattern) if literal else pattern
    try:
        engine = Regex(
            f"(?:{source})",
            case_insensitive=ignore_case,
            multi_line=True,
            size_limit=10 * 1024 * 1024,
        )
    except RegexError as exc:
        message = "rg: " + str(exc)
        if "look-around" in message or "backreferences are not supported" in message:
            message += (
                "\n\nConsider enabling PCRE2 with the --pcre2 flag, which can handle backreferences\n"
                "and look-around."
            )
        raise SearchRegexError(message) from exc
    return SearchRegex(engine)
