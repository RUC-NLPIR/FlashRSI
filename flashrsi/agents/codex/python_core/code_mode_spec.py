"""Code Mode spec/TypeScript rendering from Codex be6e8eac.

Sources: code-mode-protocol/src/description.rs, tools/src/code_mode.rs,
core/src/tools/{spec_plan,code_mode/{execute_spec,wait_spec}}.rs.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

_ASSETS = Path(__file__).with_name("code_mode_assets")


def _asset(name):
    return (_ASSETS / name).read_text()


def identifier(name):
    result = "".join(
        c if re.fullmatch(r"[A-Za-z_$]" if i == 0 else r"[A-Za-z0-9_$]", c) else "_"
        for i, c in enumerate(name)
    )
    return result or "_"


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def typescript(value):
    if value is True:
        return "unknown"
    if value is False:
        return "never"
    if not isinstance(value, dict):
        return "unknown"
    if "const" in value:
        return _json(value["const"])
    if value.get("enum"):
        return " | ".join(map(_json, value["enum"]))
    for key, join in (("anyOf", " | "), ("oneOf", " | "), ("allOf", " & ")):
        if value.get(key):
            return join.join(map(typescript, value[key]))

    def keyword(kind):
        if kind == "object":
            return _object(value)
        if kind == "array":
            if "items" in value:
                return "Array<" + typescript(value["items"]) + ">"
            if value.get("prefixItems"):
                return "[" + ", ".join(map(typescript, value["prefixItems"])) + "]"
            return "unknown[]"
        return {
            "string": "string",
            "integer": "number",
            "number": "number",
            "boolean": "boolean",
            "null": "null",
        }.get(kind, "unknown")

    kind = value.get("type")
    if isinstance(kind, list) and kind:
        return " | ".join(keyword(k) for k in kind if isinstance(k, str))
    if isinstance(kind, str):
        return keyword(kind)
    if {"properties", "additionalProperties", "required"} & value.keys():
        return keyword("object")
    if {"items", "prefixItems"} & value.keys():
        return keyword("array")
    return "unknown"


def _object(value):
    properties = value.get("properties") or {}
    multiline = any(
        v.get("description") for v in properties.values() if isinstance(v, dict)
    )
    lines = []
    for name, field in sorted(properties.items()):
        if multiline:
            lines.extend(
                "  // " + line.strip()
                for line in field.get("description", "").splitlines()
                if line.strip()
            )
        key = name if identifier(name) == name else _json(name)
        lines.append(
            ("  " if multiline else "")
            + key
            + ("" if name in value.get("required", []) else "?")
            + ": "
            + typescript(field)
            + ";"
        )
    additional = value.get("additionalProperties", not bool(properties))
    if additional is not False:
        lines.append(
            ("  " if multiline else "")
            + "[key: string]: "
            + typescript(additional)
            + ";"
        )
    if multiline:
        return "{\n" + "\n".join(lines) + "\n}"
    return "{ " + " ".join(lines) + " }" if lines else "{}"


def _mcp_structured(schema):
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties", {})
    if (
        props.get("content", {}).get("type") == "array"
        and props["content"].get("items", {}).get("type") == "object"
        and props.get("isError", {}).get("type") == "boolean"
        and props.get("_meta", {}).get("type") == "object"
    ):
        return props.get("structuredContent", True)
    return None


def declaration(tool):
    custom = tool["kind"] == "freeform"
    input_type = "string" if custom else typescript(tool.get("input_schema", True))
    structured = _mcp_structured(tool.get("output_schema"))
    if structured is not None:
        output_type = typescript(structured)
        output_type = "CallToolResult" + (
            "<" + output_type + ">" if output_type != "unknown" else ""
        )
    else:
        output_type = typescript(tool.get("output_schema", True))
    return (
        tool["description"]
        + "\n\nexec tool declaration:\n```ts\ndeclare const tools: { "
        + identifier(tool["name"])
        + "("
        + ("input" if custom else "args")
        + ": "
        + input_type
        + "): Promise<"
        + output_type
        + ">; };\n```"
    )


def collect_definitions(specs, *, augment=False, settings=None):
    """Flatten tool namespaces, retaining their dispatch identity and schema."""
    definitions = {}
    for spec in specs:
        namespace = spec.get("name") if spec["type"] == "namespace" else None
        for tool in spec["tools"] if namespace is not None else [spec]:
            if tool["type"] not in {"function", "custom"}:
                continue
            short = tool["name"]
            if namespace in {None, "functions"}:
                name = short
            else:
                name = (
                    namespace
                    + ("" if namespace.endswith("_") or short.startswith("_") else "__")
                    + short
                )
            if name in {"exec", "wait"}:
                continue
            description = tool.get("description", "")
            output_schema = tool.get("output_schema")
            if (
                output_schema is None
                and namespace in {None, "functions"}
                and short in {"exec_command", "write_stdin"}
            ):
                output_schema = json.loads(_asset("unified_exec_output_schema.json"))
            if (
                output_schema is None
                and namespace in {None, "functions"}
                and short in {"view_image", "get_context_remaining"}
            ):
                output_schema = json.loads(_asset(short + "_output_schema.json"))
            if output_schema is None and namespace == "memories":
                from .memory import memory_output_schemas

                output_schema = memory_output_schemas()[short]
            if output_schema is None:
                from .subagents import output_schemas
                from .subagents_v2 import configuration

                if namespace == "multi_agent_v1":
                    output_schema = output_schemas().get(short)
                elif namespace in {
                    None,
                    configuration(settings or {})["tool_namespace"],
                }:
                    output_schema = output_schemas("v2", settings or {}).get(short)
            item = {
                "name": name,
                "global_name": identifier(name),
                "tool_name": {"name": short, "namespace": namespace},
                "kind": "freeform" if tool["type"] == "custom" else "function",
                "description": description,
            }
            if namespace is not None:
                item["tool_name"]["namespace"] = namespace
                item["namespace_description"] = spec.get("description", "")
            if tool.get("parameters") is not None:
                item["input_schema"] = copy.deepcopy(tool["parameters"])
            if output_schema is not None:
                item["output_schema"] = copy.deepcopy(output_schema)
            if augment:
                if item.get("namespace_description", "").strip():
                    item["description"] = (
                        item["namespace_description"].strip()
                        + "\n\n"
                        + item["description"]
                    )
                item["description"] = declaration(item)
            definitions.setdefault(name, item)
    return [definitions[name] for name in sorted(definitions)]


def active_definitions(raw_specs, settings, *, augment=False):
    definitions = collect_definitions(raw_specs, augment=augment, settings=settings)
    config = settings.get("features", {}).get("code_mode", {})
    config = config if isinstance(config, dict) else {}
    config = {**config, **settings.get("code_mode", {})}
    excluded = config.get("excluded_tool_namespaces", [])
    direct_namespaces = config.get("direct_only_tool_namespaces", [])
    from .subagents_v2 import configuration

    agents = configuration(settings)
    direct_only = agents["non_code_mode_only"]

    def included(tool):
        identity = tool["tool_name"]
        namespace = identity.get("namespace") or "functions"
        return (
            namespace not in excluded
            and namespace not in direct_namespaces
            and not (
                namespace == "functions"
                and identity["name"] in {"request_user_input", "new_context"}
            )
            and not (
                direct_only and identity.get("namespace") == agents["tool_namespace"]
            )
        )

    return [tool for tool in definitions if included(tool)]


def specs(raw_specs, settings, model, deferred=()):
    mode = model.info.get("tool_mode")
    if mode not in {"code_mode", "code_mode_only"}:
        return copy.deepcopy(raw_specs)
    definitions = active_definitions(raw_specs, settings)
    deferred_specs = (
        [entry["output"] for entry in deferred.values()]
        if isinstance(deferred, dict)
        else list(deferred)
    )
    runtime_definitions = active_definitions([*raw_specs, *deferred_specs], settings)
    names = {tool["name"] for tool in definitions}
    if model.info["use_responses_lite"]:
        settings["_code_mode_tool_names"] = {
            tool["global_name"]: tool["tool_name"] for tool in runtime_definitions
        }
    default_yield = (
        30000 if settings.get("features", {}).get("code_mode_buffered_exec") else 10000
    )
    sections = [
        _asset("exec_description_template.txt").replace(
            "Defaults to 10000 ms.", f"Defaults to {default_yield} ms."
        )
    ]
    if deferred:
        sections.append(_asset("deferred_nested_tools_guidance.txt"))
    if mode == "code_mode_only":
        if any(
            _mcp_structured(t.get("output_schema")) is not None for t in definitions
        ):
            sections.append(
                "Shared MCP Types:\n```ts\n"
                + _asset("mcp_typescript_preamble.txt")
                + "\n```"
            )
        parts, current = [], None
        for tool in sorted(
            definitions,
            key=lambda t: (
                t["tool_name"].get("namespace") or "",
                t["tool_name"]["name"],
                t["name"],
            ),
        ):
            namespace = tool["tool_name"].get("namespace")
            if current != namespace and tool.get("namespace_description", "").strip():
                parts.append(
                    "## " + namespace + "\n" + tool["namespace_description"].strip()
                )
            current = namespace
            heading = "### `" + tool["global_name"] + "`"
            if tool["global_name"] != tool["name"]:
                heading += " (`" + tool["name"] + "`)"
            parts.append(heading + "\n" + declaration(tool).strip())
        if parts:
            sections.append("\n\n".join(parts))
    exec_spec = {
        "type": "custom",
        "name": "exec",
        "description": "\n\n".join(sections),
        "format": {
            "type": "grammar",
            "syntax": "lark",
            "definition": _asset("exec.lark"),
        },
    }
    from .tools import function, schema

    wait_spec = function(
        "wait",
        "Waits on a yielded `exec` cell and returns new output or completion.\n"
        + _asset("wait_description_template.txt").strip(),
        {
            "cell_id": schema("string", "Identifier of the running exec cell."),
            "yield_time_ms": schema(
                "number", "Wait before yielding more output. Defaults to 10000 ms."
            ),
            "max_tokens": schema(
                "number",
                "Output token budget for this wait call. Defaults to 10000 tokens.",
            ),
            "terminate": schema(
                "boolean",
                "True stops the running exec cell; false or omitted waits for output.",
            ),
        },
        ["cell_id"],
    )
    visible = []
    for spec in copy.deepcopy(raw_specs):
        if model.info["use_responses_lite"] and spec["type"] in {
            "web_search",
            "tool_search",
        }:
            continue
        if mode == "code_mode_only":
            if spec["type"] == "namespace":
                spec["tools"] = [
                    t
                    for t in spec["tools"]
                    if not any(
                        d["name"] in names
                        and d["tool_name"].get("namespace") == spec["name"]
                        and d["tool_name"]["name"] == t["name"]
                        for d in definitions
                    )
                ]
                if not spec["tools"]:
                    continue
            elif spec.get("name") in names:
                continue
        elif mode == "code_mode":
            for tool in spec["tools"] if spec["type"] == "namespace" else [spec]:
                namespace = spec["name"] if spec["type"] == "namespace" else None
                definition = next(
                    (
                        d
                        for d in definitions
                        if d["tool_name"]["name"] == tool.get("name")
                        and d["tool_name"].get("namespace") == namespace
                    ),
                    None,
                )
                if definition:
                    tool["description"] = declaration(definition)
        visible.append(spec)
    return [exec_spec, wait_spec, *visible]
