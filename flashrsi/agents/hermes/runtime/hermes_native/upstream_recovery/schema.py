from __future__ import annotations
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


_STRIP_ON_RECOVERY_KEYS = frozenset({"pattern", "format"})


_SCHEMA_MARKERS = frozenset({"type", "anyOf", "oneOf", "allOf"})  # a node with one IS a schema


def _dict_nodes(node: Any):
    """Pre-order walk over every dict node (yielded before its values, so it may be mutated)."""
    if isinstance(node, dict):
        yield node
    children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
    for child in children:
        yield from _dict_nodes(child)


def _reactive_strip(
    tools: list[dict], strip_node: Callable[[dict], int], log_msg: str) -> tuple[list[dict], int]:
    """Apply *strip_node* (-> keywords removed) to every dict node of each tool's parameters, in
    place; OpenAI (``{"function": {"parameters"}}``) and Responses (``{"parameters"}``) formats."""
    stripped = 0
    for tool in tools or ():
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        params = fn.get("parameters") if isinstance(fn, dict) else None
        params = params if isinstance(params, dict) else tool.get("parameters")
        if isinstance(params, dict):
            stripped += sum(strip_node(node) for node in _dict_nodes(params))
    if stripped:
        logger.info(log_msg, stripped)
    return tools, stripped


def strip_pattern_and_format(tools: list[dict]) -> tuple[list[dict], int]:
    """Strip ``pattern``/``format`` in place — reactive, only after llama.cpp's grammar converter
    rejected a schema (its regex engine is a small ECMAScript subset); cloud providers use these as
    prompting hints. Only beside ``type``/combinators, so a property *named* ``pattern`` stays."""
    def _strip(node: dict) -> int:
        is_schema = bool(node.keys() & _SCHEMA_MARKERS)
        hits = [k for k in node if k in _STRIP_ON_RECOVERY_KEYS] if is_schema else []
        for k in hits:
            del node[k]
        return len(hits)
    return _reactive_strip(
        tools, _strip,
        "schema_sanitizer: stripped %d pattern/format keyword(s) from "
        "tool schemas (llama.cpp grammar-parse recovery)")
