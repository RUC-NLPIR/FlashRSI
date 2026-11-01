"""Pi v1.4.0 transcript tool state and OpenAI constrained tool declarations.

Source: utils/transcript.ts, api/constrained-sampling.ts, openai-completions.ts
and openai-responses-shared.ts at the revision recorded in UPSTREAM.md.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .compaction import js_json
from .constrained_sampling import resolve_strict, strict_parameters


def _messages(context: Any) -> list[dict[str, Any]]:
    return context.get("messages", []) if isinstance(context, Mapping) else context


def current_tools(context: Any) -> list[dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for message in _messages(context):
        if message.get("role") != "system":
            continue
        for tool in message.get("toolsRemoved") or []:
            tools.pop(tool["name"], None)
        for tool in message.get("toolsAdded") or []:
            tools[tool["name"]] = tool
    return copy.deepcopy(list(tools.values()))


def declared_tools(context: Any) -> list[dict[str, Any]]:
    """All declared names in first-declaration order, using their latest schema."""
    tools: dict[str, dict[str, Any]] = {}
    for message in _messages(context):
        if message.get("role") == "system":
            for tool in message.get("toolsAdded") or []:
                tools[tool["name"]] = tool
    return copy.deepcopy(list(tools.values()))


def resolve_tools(context: Any, support: str) -> tuple[list[dict[str, Any]], int]:
    """Resolve request tools and the number of folded leading system messages."""
    messages = _messages(context)
    systems = [message for message in messages if message.get("role") == "system"]
    if support == "none":
        return current_tools(systems), len(systems)
    if support == "changes":
        return [], 0
    declared: set[str] = set()
    last_non_additive = -1
    for index, message in enumerate(systems):
        if message.get("toolsRemoved"):
            last_non_additive = index
        for tool in message.get("toolsAdded") or []:
            if tool["name"] in declared:
                last_non_additive = index
            declared.add(tool["name"])
    folded = max(
        1 if messages and messages[0].get("role") == "system" else 0,
        last_non_additive + 1,
    )
    return current_tools(systems[:folded]), folded


def tool_support(compat: Mapping[str, Any], api: str) -> str:
    if api == "openai-responses":
        if compat.get("supportsMidConvoSystemMessages") and compat.get(
            "supportsAdditionalTools"
        ):
            return "changes"
        return "additions" if compat.get("supportsToolSearch") else "none"
    return (
        "additions"
        if compat.get("supportsMidConvoSystemMessages") is True
        and compat.get("supportsMidConvoToolAdditions") is True
        else "none"
    )


def resolve_grammar(tool: Mapping[str, Any], supports: bool) -> dict[str, str] | None:
    config = tool.get("constrainedSampling")
    if (
        not isinstance(config, Mapping)
        or config.get("type") != "grammar"
        or not supports
    ):
        return None
    variants = config.get("variants") or {}
    lark, regex = variants.get("openai_lark"), variants.get("openai_regex")
    has_lark = isinstance(lark, str) and bool(lark.strip())
    has_regex = isinstance(regex, str) and bool(regex.strip())
    if not has_lark and not has_regex:
        raise ValueError(
            f'Tool "{tool["name"]}" cannot use grammar constrained sampling: no supported grammar variant was provided.'
        )
    try:
        schema = tool["parameters"]
        if not isinstance(schema, Mapping) or schema.get("type") != "object":
            raise ValueError(
                "grammar constrained sampling requires an object parameter schema"
            )
        required = schema.get("required")
        if (
            not isinstance(required, list)
            or len(required) != 1
            or not isinstance(required[0], str)
        ):
            raise ValueError(
                "grammar constrained sampling requires exactly one required string property"
            )
        name = required[0]
        properties = schema.get("properties") or {}
        if (
            name not in properties
            or properties[name] is None
            or properties[name] is False
        ):
            raise ValueError(
                f"grammar constrained sampling requires a properties entry for {name}"
            )
        if (
            not isinstance(properties[name], Mapping)
            or properties[name].get("type") != "string"
        ):
            raise ValueError(
                f"grammar constrained sampling property {name} must have type string"
            )
        return {
            "format": "lark" if has_lark else "regex",
            "definition": lark if has_lark else regex,
            "inputProperty": name,
        }
    except ValueError as exc:
        raise ValueError(
            f'Tool "{tool["name"]}" cannot use grammar constrained sampling: {exc}.'
        ) from exc


def grammar_properties(
    tools: list[dict[str, Any]] | None, compat: Mapping[str, Any]
) -> dict[str, str]:
    properties = {}
    for tool in tools or []:
        grammar = resolve_grammar(tool, bool(compat.get("supportsOpenAIGrammarTools")))
        if grammar:
            properties[tool["name"]] = grammar["inputProperty"]
    return properties


def grammar_input(
    tool_name: str, arguments: Mapping[str, Any], input_property: str
) -> str:
    value = arguments.get(input_property)
    if not isinstance(value, str):
        raise ValueError(
            f'Grammar tool call "{tool_name}" requires argument "{input_property}" to be a string.'
        )
    return value


def append_grammar_delta(
    buffer: dict[str, Any], input_property: str, next_input: str, close: bool
) -> str | None:
    """Append escaped, monotonic custom-tool input to Pi's JSON argument buffer."""
    previous = buffer.get("input", "")
    if buffer.get("closed"):
        if close and next_input == previous:
            return None
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed after it was closed'
        )
    if not next_input.startswith(previous):
        raise ValueError(
            f'grammar tool input for property "{input_property}" changed non-monotonically'
        )
    addition = next_input[len(previous) :]
    if not close and not addition:
        return None
    delta = ""
    if not buffer.get("started"):
        delta = "{" + js_json(input_property) + ':"'
        buffer["started"] = True
    delta += js_json(addition)[1:-1]
    buffer["input"] = next_input
    if close:
        delta += '"}'
        buffer["closed"] = True
    return delta


def convert_tools(
    tools: list[dict[str, Any]],
    compat: Mapping[str, Any],
    api: str,
    *,
    tool_search_result: bool = False,
    default_strict: bool | None = False,
) -> list[dict[str, Any]]:
    """Convert JSON-schema or grammar declarations into provider tool fields."""
    result = []
    supports_strict = compat.get("supportsStrictMode") is not False
    for tool in tools:
        grammar = resolve_grammar(tool, bool(compat.get("supportsOpenAIGrammarTools")))
        if grammar:
            if api == "openai-completions":
                result.append(
                    {
                        "type": "custom",
                        "custom": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "format": {
                                "type": "grammar",
                                "grammar": {
                                    "syntax": grammar["format"],
                                    "definition": grammar["definition"],
                                },
                            },
                        },
                    }
                )
            else:
                result.append(
                    {
                        "type": "custom",
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "format": {
                            "type": "grammar",
                            "syntax": grammar["format"],
                            "definition": grammar["definition"],
                        },
                        **({"defer_loading": True} if tool_search_result else {}),
                    }
                )
            continue
        constrained = resolve_strict(tool, supports_strict)
        strict = (
            constrained
            if constrained is not None
            else (False if api == "openai-completions" else default_strict)
        )
        definition = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": strict_parameters(tool, strict is True),
            **({"strict": strict} if supports_strict else {}),
        }
        if api == "openai-completions":
            result.append({"type": "function", "function": definition})
        else:
            result.append(
                {
                    "type": "function",
                    **definition,
                    **({"defer_loading": True} if tool_search_result else {}),
                }
            )
    return result
