"""Pure Python ports of Pi's JSON repair and ``partial-json`` stream parser.

The source and development oracle are pinned in UPSTREAM.md. No JavaScript
runtime is used by these helpers.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any


def repair_json(value: str) -> str:
    result, inside, index = [], False, 0
    while index < len(value):
        char = value[index]
        if not inside:
            result.append(char)
            if char == '"':
                inside = True
        elif char == '"':
            result.append(char)
            inside = False
        elif char == "\\":
            following = value[index + 1 : index + 2]
            if following == "u" and re.fullmatch(
                r"[a-fA-F0-9]{4}", value[index + 2 : index + 6]
            ):
                result.append(value[index : index + 6])
                index += 5
            elif following and following in '"\\/bfnrt':
                result.append(char + following)
                index += 1
            else:
                result.append("\\\\")
        else:
            result.append(json.dumps(char)[1:-1] if ord(char) < 32 else char)
        index += 1
    return "".join(result)


def _units(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _syntax_error(value: str, error: json.JSONDecodeError) -> str:
    """Retain V8's provider-facing diagnostics for the usual JSON failures."""
    position, message = error.pos, error.msg
    suffix = (
        f" at position {_units(value[:position])} "
        f"(line {error.lineno} column {_units(value[value.rfind(chr(10), 0, position) + 1 : position]) + 1})"
    )
    if message == "Unterminated string starting at":
        position = len(value)
        line = value.count("\n") + 1
        column = _units(value[value.rfind("\n") + 1 :]) + 1
        return f"Unterminated string in JSON at position {_units(value)} (line {line} column {column})"
    if message == "Expecting property name enclosed in double quotes":
        previous = value[:position].rstrip()
        expected = (
            "Expected double-quoted property name"
            if previous.endswith(",")
            else "Expected property name or '}'"
        )
        return expected + " in JSON" + suffix
    if message == "Expecting ':' delimiter":
        return "Expected ':' after property name in JSON" + suffix
    if message == "Expecting ',' delimiter":
        if value[position : position + 1] in {"e", "E"}:
            position += 1
            if value[position : position + 1] in {"+", "-"}:
                position += 1
            return (
                "Exponent part is missing a number in JSON"
                f" at position {_units(value[:position])} "
                f"(line {value[:position].count(chr(10)) + 1} "
                f"column {_units(value[value.rfind(chr(10), 0, position) + 1 : position]) + 1})"
            )
        # Python reports the same diagnostic for both containers. Recover the
        # innermost open container, ignoring delimiters inside string literals.
        stack, inside, escaped = [], False, False
        for char in value[:position]:
            if inside:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    inside = False
            elif char == '"':
                inside = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}" and stack:
                stack.pop()
        return (
            "Expected ',' or ']' after array element in JSON"
            if stack and stack[-1] == "["
            else "Expected ',' or '}' after property value in JSON"
        ) + suffix
    if message == "Extra data":
        return "Unexpected non-whitespace character after JSON" + suffix
    if message.startswith("Invalid control character"):
        return "Bad control character in string literal in JSON" + suffix
    if message.startswith("Invalid \\escape"):
        position += 1
        suffix = (
            f" at position {_units(value[:position])} "
            f"(line {value[:position].count(chr(10)) + 1} "
            f"column {_units(value[value.rfind(chr(10), 0, position) + 1 : position]) + 1})"
        )
        return "Bad escaped character in JSON" + suffix
    if message.startswith("Invalid \\u"):
        return "Bad Unicode escape in JSON" + suffix
    if position >= len(value):
        return "Unexpected end of JSON input"
    remaining = value[position:]
    if message == "Expecting value" and any(
        token.startswith(remaining) for token in ("null", "true", "false")
    ):
        return "Unexpected end of JSON input"
    # JSON.parse formats short malformed values verbatim and uses a centred
    # excerpt for longer values. Tool-call diagnostics include the full input
    # separately, so this excerpt is only the provider's leading explanation.
    if value[position : position + 1] == "-":
        position += 1
        return (
            f"No number after minus sign in JSON at position {_units(value[:position])} "
            f"(line 1 column {_units(value[:position]) + 1})"
        )
    token = value[position]
    if len(value) <= 20:
        excerpt = value
    else:
        begin, end = max(0, position - 10), min(len(value), position + 10)
        excerpt = (
            ("..." if begin else "")
            + value[begin:end]
            + ("..." if end < len(value) else "")
        )
    return f"Unexpected token '{token}', \"{excerpt}\" is not valid JSON"


def _loads(value: str) -> Any:
    def invalid_constant(token):
        position = value.index(token)
        raise json.JSONDecodeError("Expecting value", value, position)

    return json.loads(value, parse_constant=invalid_constant)


def parse_json_with_repair(value: str) -> Any:
    try:
        return _loads(value)
    except json.JSONDecodeError as original:
        repaired = repair_json(value)
        if repaired != value:
            try:
                return _loads(repaired)
            except json.JSONDecodeError as error:
                raise ValueError(_syntax_error(repaired, error)) from None
        raise ValueError(_syntax_error(value, original)) from None


def parse_tool_arguments(value: str | None) -> dict[str, Any]:
    if not value or not value.strip():
        return {"arguments": {}}
    try:
        parsed = parse_json_with_repair(value)
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return {"arguments": parsed}
    except ValueError as error:
        return {
            "arguments": {},
            "argumentsError": f"{error}\n\nReceived arguments:\n{value}",
        }


class _PartialParser:
    """Source port of partial-json 0.1.7 with its default Allow.ALL flags."""

    def __init__(self, value):
        self.value, self.index = value.strip(), 0

    def char(self):
        return self.value[self.index : self.index + 1]

    def blank(self):
        while self.char() and self.char() in " \n\r\t":
            self.index += 1

    def parse(self):
        self.blank()
        if not self.char():
            raise ValueError("Unexpected end of input")
        if self.char() == '"':
            return self.string()
        if self.char() == "{":
            return self.object()
        if self.char() == "[":
            return self.array()
        for spelling, result in (
            ("null", None),
            ("true", True),
            ("false", False),
            ("Infinity", math.inf),
            ("-Infinity", -math.inf),
            ("NaN", math.nan),
        ):
            remaining = self.value[self.index :]
            if remaining.startswith(spelling) or (
                len(remaining) < len(spelling)
                and spelling.startswith(remaining)
                and (spelling != "-Infinity" or len(remaining) > 1)
            ):
                self.index += len(spelling)
                return result
        return self.number()

    def string(self):
        start, escaped = self.index, False
        self.index += 1
        while self.index < len(self.value) and (
            self.char() != '"' or (escaped and self.value[self.index - 1] == "\\")
        ):
            escaped = not escaped if self.char() == "\\" else False
            self.index += 1
        if self.char() == '"':
            self.index += 1
            return _loads(self.value[start : self.index - int(escaped)])
        try:
            return _loads(self.value[start : self.index - int(escaped)] + '"')
        except ValueError:
            return _loads(self.value[start : self.value.rfind("\\")] + '"')

    def object(self):
        self.index += 1
        self.blank()
        result = {}
        try:
            while self.char() != "}":
                self.blank()
                if self.index >= len(self.value):
                    return result
                key = self.string()
                self.blank()
                self.index += 1
                try:
                    result[key] = self.parse()
                except ValueError:
                    return result
                self.blank()
                if self.char() == ",":
                    self.index += 1
        except ValueError:
            return result
        self.index += 1
        return result

    def array(self):
        self.index += 1
        result = []
        try:
            while self.char() != "]":
                result.append(self.parse())
                self.blank()
                if self.char() == ",":
                    self.index += 1
        except ValueError:
            return result
        self.index += 1
        return result

    def number(self):
        if self.index == 0:
            if self.value == "-":
                raise ValueError("Not sure what '-' is")
            try:
                return _loads(self.value)
            except ValueError:
                exponent = self.value.rfind("e")
                if exponent < 0:
                    raise
                return _loads(self.value[:exponent])
        start = self.index
        if self.char() == "-":
            self.index += 1
        while self.char() and self.char() not in ",]}":
            self.index += 1
        try:
            return _loads(self.value[start : self.index])
        except ValueError:
            if self.value[start : self.index] == "-":
                raise
            exponent = self.value.rfind("e")
            if exponent < start:
                raise
            return _loads(self.value[start:exponent])


def parse_streaming_json(value: str | None) -> Any:
    if not value or not value.strip():
        return {}
    try:
        return parse_json_with_repair(value)
    except ValueError:
        for candidate in (value, repair_json(value)):
            try:
                result = _PartialParser(candidate).parse()
                return {} if result is None else result
            except ValueError:
                continue
        return {}
