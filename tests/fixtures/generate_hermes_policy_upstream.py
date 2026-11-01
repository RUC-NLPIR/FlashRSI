"""Execute selected original Hermes policy helpers and freeze their outputs.

Only stdlib import globals are supplied. No original function body is rewritten;
the AIAgent static method keeps its original class/decorator context.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path, help="Pinned hermes-agent v0.22.5 checkout")
parser.add_argument(
    "--output",
    type=Path,
    default=Path(__file__).with_name("hermes_policy_upstream.json"),
)
options = parser.parse_args()
SOURCE = options.source
DESTINATION = options.output
SYMBOLS = {
    "agent/think_scrubber.py": ["THINK_TAG_NAMES"],
    "agent/agent_runtime_helpers.py": [
        "_TOOL_CALL_TAG_NAMES",
        "_NS_PREFIX",
        "_REASONING_BLOCK_PATTERNS",
        "_TOOL_CALL_BLOCK_PATTERNS",
        "_NAMED_FUNCTION_BLOCK_PATTERN",
        "_UNTERMINATED_REASONING_BLOCK_PATTERN",
        "_ORPHAN_REASONING_TAG_PATTERN",
        "_STRAY_TOOL_CALL_CLOSER_PATTERN",
        "_UNTERMINATED_TOOL_CALL_PATTERN",
        "_flatten_content_text",
        "_THINK_STRIP_PATTERNS",
        "strip_think_blocks",
        "repair_tool_call",
    ],
    "agent/turn_response_intake.py": ["_coerce_content_text"],
    "agent/conversation_loop.py": [
        "_MIN_CONTINUATION_OVERLAP",
        "_continuation_overlap_length",
        "_join_truncated_parts",
        "_LENGTH_CONTINUATION_NETWORK_STUB",
        "_LENGTH_CONTINUATION_OUTPUT_LIMIT",
        "_LENGTH_CONTINUATION_DROPPED_TOOLS_PREFIX",
        "_get_continuation_prompt",
        "_invalid_tool_name_error_content",
    ],
    "agent/context_compressor.py": ["MAX_ITERATIONS_SUMMARY_REQUEST"],
}


def bound_names(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


namespace = {
    "__name__": "hermes_executed_upstream_policy_oracle",
    "re": re,
    "json": json,
    "Any": Any,
    "Optional": Optional,
    "logger": logging.getLogger("hermes-policy-upstream-oracle"),
}
sources = {}
for relative, wanted in SYMBOLS.items():
    text = (SOURCE / relative).read_text()
    lines = text.splitlines(keepends=True)
    selected = []
    found = set()
    for node in ast.parse(text).body:
        names = bound_names(node) & set(wanted)
        if names:
            snippet = "".join(lines[node.lineno - 1 : node.end_lineno])
            selected.append(snippet)
            found.update(names)
    assert found == set(wanted), (relative, set(wanted) - found)
    code = "\n\n".join(selected)
    exec(
        compile("from __future__ import annotations\n" + code, relative, "exec"),
        namespace,
    )
    sources[relative] = {
        "sha256": digest(text),
        "selected_symbols": wanted,
        "selected_source_sha256": digest(code),
    }

relative = "run_agent.py"
text = (SOURCE / relative).read_text()
lines = text.splitlines(keepends=True)
original_class = next(
    n
    for n in ast.parse(text).body
    if isinstance(n, ast.ClassDef) and n.name == "AIAgent"
)
method = next(
    n
    for n in original_class.body
    if isinstance(n, ast.FunctionDef) and n.name == "_deduplicate_tool_calls"
)
start = min([method.lineno] + [n.lineno for n in method.decorator_list])
snippet = "".join(lines[start - 1 : method.end_lineno])
exec(compile("class AIAgent:\n" + snippet, relative, "exec"), namespace)
namespace["_deduplicate_tool_calls"] = namespace["AIAgent"]._deduplicate_tool_calls
sources[relative] = {
    "sha256": digest(text),
    "selected_symbols": ["AIAgent._deduplicate_tool_calls"],
    "selected_source_sha256": digest(snippet),
}

fixture = {
    "baseline": {
        "repository": "https://github.com/NousResearch/hermes-agent",
        "version": "v0.22.5",
        "commit": "bf0203a794a07aac3ff764972ab9087baa4e4f4e",
        "method": (
            "Executed original AST-selected top-level declarations and the unchanged "
            "AIAgent static dedup method in CPython, with only stdlib globals supplied. "
            "Function bodies, regexes and constants were not translated. Sources and "
            "executed selections are SHA-256 recorded below. This is a component "
            "policy oracle, not a full run_conversation trajectory oracle."
        ),
        "sources": sources,
    },
    "cases": [],
}


def case(name, helper, *args):
    call_args = list(args)
    identity = None
    if helper == "strip_think_blocks":
        result = namespace[helper](None, *call_args)
    elif helper == "repair_tool_call":
        result = namespace[helper](
            SimpleNamespace(valid_tool_names=set(call_args[1])), call_args[0]
        )
    elif helper == "_deduplicate_tool_calls":
        calls = [
            SimpleNamespace(
                id=item["id"],
                function=SimpleNamespace(
                    name=item["name"], arguments=item["arguments"]
                ),
            )
            for item in call_args[0]
        ]
        output = namespace[helper](calls)
        identity = output is calls
        result = [item.id for item in output]
    elif helper == "MAX_ITERATIONS_SUMMARY_REQUEST":
        result = namespace[helper]
    else:
        result = namespace[helper](*call_args)
    entry = {"name": name, "helper": helper, "args": call_args, "expected": result}
    if identity is not None:
        entry["returns_original_list"] = identity
    fixture["cases"].append(entry)


for name, text in [
    ("think_empty", ""),
    ("think_none", None),
    ("think_plain", "Visible answer.\nKeep whitespace.  "),
    ("think_closed_mixed_case", "<ThInK>private\nthought</tHiNk>Visible"),
    ("think_closed_inline", "Before <reasoning>private</reasoning> after"),
    ("think_unterminated_boundary", "Visible\n  <thinking>private tail"),
    ("think_unterminated_inline", "The <think> tag is a label."),
    ("think_orphan_closer", "</THINK>\n Visible"),
    (
        "think_all_tag_names",
        "".join(f"<{n}>hidden</{n}>" for n in namespace["THINK_TAG_NAMES"]) + "Final",
    ),
    (
        "think_multimodal",
        [
            "Before ",
            {"type": "thinking", "text": "hidden"},
            {"type": "redacted_thinking", "text": "hidden"},
            {"type": "TEXT", "text": "visible"},
            {"type": "image", "url": "x"},
            " after",
        ],
    ),
    ("think_dict", {"text": "<think>hidden</think>answer"}),
    ("think_unrecognized_scalar", 42),
    (
        "xml_namespace_tool_block",
        "Before<ns:function_calls><invoke>hidden</invoke></ns:function_calls>After",
    ),
    ("xml_tool_result", "Before<tool_result>private</tool_result>After"),
    (
        "xml_function_boundary",
        'Before. <function name="terminal">hidden</function>After',
    ),
    (
        "xml_function_inline_prose",
        'Mention <function name="f">example</function> inline.',
    ),
    ("xml_function_unnamed", "<function>keep this</function>After"),
    ("xml_unclosed_tool", 'Visible\n<tool_call>{"name": "terminal"'),
    (
        "xml_orphan_arg_lines",
        "Visible\nprocess_manage<arg_key>operation</arg_key>\nwait</arg_value>\nAfter",
    ),
    ("xml_inline_arg_prose", "Use <arg_key> in the documentation.\nAfter"),
]:
    case(name, "strip_think_blocks", text)

for name, raw in [
    ("coerce_plain", "plain"),
    ("coerce_none", None),
    ("coerce_number", 17),
    ("coerce_bool", False),
    ("coerce_dict_text", {"text": "hello", "content": "other"}),
    ("coerce_dict_fallback", {"text": "", "content": "fallback"}),
    ("coerce_dict_json", {"payload": "中文"}),
    (
        "coerce_multimodal",
        [
            "plain",
            {"type": "text", "text": "block"},
            {"type": "image_url", "image_url": {"url": "x"}},
            {"text": 3},
            {"type": "reasoning", "content": "hidden"},
        ],
    ),
    ("coerce_empty_list", []),
]:
    case(name, "_coerce_content_text", raw)


def tc(identifier, name, arguments):
    return {"id": identifier, "name": name, "arguments": arguments}


for name, calls in [
    ("dedup_empty", []),
    (
        "dedup_unique_identity",
        [tc("a", "read_file", '{"path":"a"}'), tc("b", "read_file", '{"path":"b"}')],
    ),
    (
        "dedup_canonical_json",
        [
            tc("first", "read_file", '{"path":"a", "limit": 1}'),
            tc("duplicate", "read_file", '{ "limit":1,"path":"a" }'),
            tc("last", "read_file", '{"path":"b"}'),
        ],
    ),
    (
        "dedup_nested_canonical",
        [
            tc("first", "write_file", '{"meta":{"b":2,"a":1},"path":"a"}'),
            tc("duplicate", "write_file", '{"path":"a","meta":{"a":1,"b":2}}'),
        ],
    ),
    (
        "dedup_different_names",
        [
            tc("read", "read_file", '{"path":"a"}'),
            tc("write", "write_file", '{"path":"a"}'),
        ],
    ),
    (
        "dedup_invalid_json_raw",
        [
            tc("a", "read_file", "{bad"),
            tc("b", "read_file", "{bad"),
            tc("space", "read_file", " {bad"),
        ],
    ),
    (
        "dedup_json_scalar_types",
        [
            tc("boolean", "tool", "true"),
            tc("integer", "tool", "1"),
            tc("string", "tool", '"1"'),
            tc("null", "tool", "null"),
        ],
    ),
    (
        "dedup_array_order",
        [
            tc("a", "tool", "[1,2]"),
            tc("b", "tool", "[2,1]"),
            tc("dup", "tool", "[1, 2]"),
        ],
    ),
]:
    case(name, "_deduplicate_tool_calls", calls)

seam = "A unique continuation seam with 32+ chars."
for name, before, after in [
    ("overlap_below_minimum", "a" * 31, "a" * 31),
    ("overlap_at_minimum", "a" * 32, "a" * 32),
    ("overlap_long_suffix", "prefix " + seam, seam + " and more"),
    ("overlap_full_suffix", "prefix " + seam, seam),
    ("overlap_no_suffix", seam, "Different prefix with more than 32 chars."),
    ("overlap_repeated_prefix", "ab" * 40, "ab" * 20 + "!"),
    ("overlap_unicode", "previous " + "中文" * 20, "中文" * 20 + "后续"),
]:
    case(name, "_continuation_overlap_length", before, after)

for name, parts in [
    ("join_empty", []),
    ("join_plain_seam", [["first", False], ["second", False]]),
    (
        "join_preserves_whitespace",
        [["first ", False], ["second", False], ["\nthird", False]],
    ),
    ("join_interrupted_dedup", [["prefix " + seam, True], [seam + " and more", False]]),
    (
        "join_output_limit_keeps_repeat",
        [["prefix " + seam, False], [seam + " and more", False]],
    ),
    ("join_short_overlap_kept", [["a" * 31, True], ["a" * 31, False]]),
    (
        "join_empty_fragment_resets_seam",
        [["prefix " + seam, True], ["", False], [seam + " and more", False]],
    ),
]:
    case(name, "_join_truncated_parts", parts)

for name, partial, tools in [
    ("prompt_output_limit", False, None),
    ("prompt_network", True, None),
    ("prompt_empty_tools", True, []),
    (
        "prompt_dropped_tools_capped",
        True,
        ["write_file", "patch", "terminal", "read_file"],
    ),
    ("prompt_nonstub_ignores_tools", False, ["write_file"]),
]:
    case(name, "_get_continuation_prompt", partial, tools)

for name, tool_name, tools in [
    ("invalid_blank", "", ["terminal", "read_file"]),
    ("invalid_whitespace", " \t", ["terminal", "read_file"]),
    ("invalid_none", None, ["terminal", "read_file"]),
    ("invalid_named_sorted_catalog", "shell", ["write_file", "terminal", "read_file"]),
    ("invalid_empty_catalog", "shell", []),
]:
    case(name, "_invalid_tool_name_error_content", tool_name, tools)

case("max_iterations_summary_request", "MAX_ITERATIONS_SUMMARY_REQUEST")
for tool_name in (
    "ReadFile",
    "READ_FILE",
    "read-file",
    "read file",
    "ReadFileTool_tool",
    'terminal" parameter="command"',
    "terminal<invoke>",
    "read_flie",
    "nonsense_xyz",
    "",
    None,
):
    case(
        f"repair_name_{tool_name!r}",
        "repair_tool_call",
        tool_name,
        ["terminal", "read_file", "write_file", "todo_list"],
    )
DESTINATION.parent.mkdir(exist_ok=True, parents=True)
DESTINATION.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
print(f"{len(fixture['cases'])} component policy cases -> {DESTINATION}")
