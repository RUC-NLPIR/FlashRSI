"""Pi v1.4.0 JSON-schema constrained sampling (MIT, see UPSTREAM.md)."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Mapping

UnsupportedKeyword = Callable[[str, Any], bool]
_UNSUPPORTED = (
    "$ref",
    "$defs",
    "definitions",
    "allOf",
    "oneOf",
    "patternProperties",
    "dependentSchemas",
    "dependencies",
    "unevaluatedProperties",
    "propertyNames",
    "contains",
    "prefixItems",
    "not",
    "if",
    "then",
    "else",
)


class UnsupportedStrictSchema(ValueError):
    pass


def _structured(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]
    elif not isinstance(types, list):
        types = []
    return ("object" in types or "array" in types) or any(
        key in schema for key in ("properties", "items")
    )


def _nullable(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    types = schema.get("type", [])
    return (
        types == "null"
        or isinstance(types, list)
        and "null" in types
        or "const" in schema
        and schema["const"] is None
        or isinstance(schema.get("enum"), list)
        and None in schema["enum"]
        or isinstance(schema.get("anyOf"), list)
        and any(map(_nullable, schema["anyOf"]))
    )


def _make_node(schema: Any, unsupported: UnsupportedKeyword | None) -> None:
    if not isinstance(schema, dict):
        raise UnsupportedStrictSchema("boolean schemas are unsupported")
    for key in _UNSUPPORTED:
        if key in schema:
            raise UnsupportedStrictSchema(f"{key} schemas are unsupported")
    if unsupported:
        for key, value in schema.items():
            if unsupported(key, value):
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                raise UnsupportedStrictSchema(f"{key}: {encoded} is unsupported")
    if "anyOf" in schema:
        variants = schema["anyOf"]
        if not isinstance(variants, list) or not variants:
            raise UnsupportedStrictSchema("anyOf must contain at least one schema")
        for variant in variants:
            if _structured(variant):
                raise UnsupportedStrictSchema("object and array unions are unsupported")
            _make_node(variant, unsupported)
    if "items" in schema:
        if isinstance(schema["items"], list):
            raise UnsupportedStrictSchema("tuple schemas are unsupported")
        _make_node(schema["items"], unsupported)
    is_object = schema.get("type") == "object"
    if "properties" in schema and not is_object:
        raise UnsupportedStrictSchema("properties require type object")
    if not is_object:
        return
    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        raise UnsupportedStrictSchema(
            "schema-valued or true additionalProperties is unsupported"
        )
    if "properties" in schema and not isinstance(schema["properties"], dict):
        raise UnsupportedStrictSchema("object properties must be a schema map")
    if "required" in schema and (
        not isinstance(schema["required"], list)
        or any(not isinstance(key, str) for key in schema["required"])
    ):
        raise UnsupportedStrictSchema("object required must be a string array")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if any(key not in properties for key in required):
        raise UnsupportedStrictSchema("required contains an unknown property")
    for key, value in list(properties.items()):
        _make_node(value, unsupported)
        if key not in required and not _nullable(value):
            properties[key] = {"anyOf": [value, {"type": "null"}]}
    schema["required"] = list(properties)
    schema["additionalProperties"] = False


def make_strict_schema(
    schema: Any, unsupported: UnsupportedKeyword | None = None
) -> dict:
    result = copy.deepcopy(schema)
    if not isinstance(result, dict):
        raise UnsupportedStrictSchema("root schema must have type object")
    _make_node(result, unsupported)
    if result.get("type") != "object":
        raise UnsupportedStrictSchema("root schema must have type object")
    return result


def resolve_strict(
    tool: Mapping[str, Any],
    supports: bool,
    unsupported: UnsupportedKeyword | None = None,
) -> bool | None:
    config = tool.get("constrainedSampling")
    if not isinstance(config, Mapping) or config.get("type") != "json_schema":
        return None
    if supports:
        try:
            make_strict_schema(tool["parameters"], unsupported)
            return True
        except UnsupportedStrictSchema as exc:
            if config.get("strict") != "require":
                return None
            raise ValueError(
                f'Tool "{tool["name"]}" requires JSON-schema constrained sampling, but {exc}.'
            ) from exc
    if config.get("strict") == "require":
        raise ValueError(
            f'Tool "{tool["name"]}" requires JSON-schema constrained sampling, but strict tools are unsupported.'
        )
    return None


def strict_parameters(tool: Mapping[str, Any], strict: bool | None) -> dict:
    return (
        make_strict_schema(tool["parameters"])
        if strict is True
        else copy.deepcopy(tool["parameters"])
    )
