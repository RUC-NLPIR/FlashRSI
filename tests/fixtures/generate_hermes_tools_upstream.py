"""Regenerate tool evidence by executing Hermes v0.22.5's original source.

Usage: .venv/bin/python tests/fixtures/generate_hermes_tools_upstream.py CHECKOUT
No FlashRSI runtime code is loaded. Native-read methods are compiled directly
from the original AST, with local I/O hooks and fixed upstream default limits.
"""

from __future__ import annotations

import ast
import base64
import difflib
import hashlib
import importlib
import json
import logging
import os
import shlex
import subprocess
import sys
import tempfile
import types
import unicodedata
from pathlib import Path
from typing import Optional


def generate(checkout: Path) -> dict:
    package = types.ModuleType("tools")
    package.__path__ = [str(checkout / "tools")]
    sys.modules["tools"] = package
    limits = types.ModuleType("tools.tool_output_limits")
    limits.get_max_lines = lambda: 2000
    limits.get_max_line_length = lambda: 2000
    sys.modules[limits.__name__] = limits
    common = importlib.import_module("tools.file_operations_common")
    binary = importlib.import_module("tools.binary_extensions")
    fuzzy = importlib.import_module("tools.fuzzy_match")
    truncate = importlib.import_module("tools.tool_output_truncate")
    namespace = {
        **vars(common),
        "base64": base64,
        "difflib": difflib,
        "hashlib": hashlib,
        "json": json,
        "os": os,
        "unicodedata": unicodedata,
        "Optional": Optional,
        "has_binary_extension": binary.has_binary_extension,
        "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"},
    }
    methods = {
        "_is_likely_binary_bytes",
        "_is_image",
        "_add_line_numbers",
        "_unified_diff",
        "_not_regular_error",
        "_exec_python_snippet",
        "_try_read_utf16",
        "_read_file_native",
        "_image_redirect_result",
        "_read_file_missing",
        "_read_binary_file",
        "_assemble_read_result",
        "_unicode_variant_match",
        "_suggest_similar_files",
        "_no_match_result",
    }
    source = checkout / "tools/file_operations.py"
    original = ast.parse(source.read_text())
    nodes = []
    for node in original.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "identify_binary_bytes",
            "describe_binary_file",
        }:
            nodes.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "_MAGIC_SIGNATURES"
        ):
            nodes.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "ShellFileOperations":
            body = [
                part
                for part in node.body
                if (isinstance(part, ast.FunctionDef) and part.name in methods)
                or (
                    isinstance(part, ast.Assign)
                    and any(
                        getattr(target, "id", "")
                        in {"_CONFUSABLES", "_UTF16_MAX_BYTES", "_UTF16_SAMPLE_BYTES"}
                        for target in part.targets
                    )
                )
            ]
            nodes.append(
                ast.ClassDef(
                    name="OriginalRead",
                    bases=[],
                    keywords=[],
                    body=body,
                    decorator_list=[],
                )
            )
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
            str(source),
            "exec",
        ),
        namespace,
    )

    class Reader(namespace["OriginalRead"]):
        def _exec(self, command):
            result = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True
            )
            return common.ExecuteResult(result.stdout, result.returncode)

        def _escape_shell_arg(self, value):
            return shlex.quote(value)

        def _python_interpreter_cmd(self):
            return shlex.quote(sys.executable)

        def read_file(self, path, offset=1, limit=2000):
            return self._read_file_native(path, offset, limit)

    # Execute the actual TodoStore/todo_tool and registry error encoder, while
    # excluding registry registration and global CLI discovery.
    todo_source = checkout / "tools/todo_tool.py"
    todo_nodes = []
    for node in ast.parse(todo_source.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "TODO_LEGACY_ALIASES"
            for target in node.targets
        ):
            break
        todo_nodes.append(node)
    todo_namespace = {"logger": logging.getLogger("oracle")}
    registry = ast.parse((checkout / "tools/registry.py").read_text())
    error_nodes = [
        node
        for node in registry.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in {"_bound_error_text", "tool_error"}
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                getattr(target, "id", "")
                in {
                    "_MAX_TOOL_ERROR_CHARS",
                    "_TOOL_ERROR_TRUNCATION_MARKER",
                    "_MAX_LOGGED_ERROR_CHARS",
                }
                for target in node.targets
            )
        )
    ]
    exec(
        compile(
            ast.Module(body=todo_nodes + error_nodes, type_ignores=[]),
            str(todo_source),
            "exec",
        ),
        todo_namespace,
    )
    todo_store = todo_namespace["TodoStore"]()
    todo_calls = [
        {},
        {
            "todos": [
                {"id": "1", "content": " first "},
                {"id": "2", "content": "active", "status": "in_progress"},
            ]
        },
        {"todos": [{"id": "2", "status": "completed"}], "merge": True},
        {"todos": [{"id": "bad", "content": ""}]},
        {},
        {"todos": [{"id": "3", "content": "child", "parent": "missing"}]},
    ]
    todo_cases = [
        {
            "args": call,
            "result": json.loads(todo_namespace["todo_tool"](store=todo_store, **call)),
        }
        for call in todo_calls
    ]
    fuzzy_calls = [
        ("alpha beta\n", "alpha", "ALPHA", False),
        ("keep\n    alpha   \nend\n", "alpha", "ALPHA", False),
        ("if ready:\n    old()\n", "if ready:\n  old()", "if ready:\n  new()", False),
        ("a\r\nb\r\n", "a\nb", "A\nB", False),
        ("print(“old”)\n", 'print("old")', 'print("new")', False),
        ("a a\n", "a", "A", False),
        ("a a\n", "a", "A", True),
        ("same", "same", "same", False),
        ("something else entirely\n", "missing text", "new text", False),
        (r'value = "a\\nb"' + "\n", r'value = "a\\nb"', r'value = "c\\nd"', False),
    ]
    fuzzy_cases = []
    for call in fuzzy_calls:
        notes = []
        result = fuzzy.fuzzy_find_and_replace(*call, correction_notes=notes)
        fuzzy_cases.append({"args": call, "result": result, "notes": notes})
    read_inputs = [
        ("plain.txt", b"one\ntwo\n", 1, 2000),
        ("no-newline.txt", b"one\ntwo", 1, 2000),
        ("bom.txt", "\ufeffone\r\ntwo\r\n".encode(), 1, 2000),
        ("empty.txt", b"", 1, 2000),
        ("page.txt", b"one\ntwo\nthree\n", 2, 1),
        ("beyond.txt", b"one\ntwo\n", 9, 2),
        ("long.txt", ("a" * 2200 + "\n").encode(), 1, 2000),
        ("utf16.txt", "hello\nworld\n".encode("utf-16"), 1, 2000),
        ("binary.dat", b"\x00\x01\x02", 1, 2000),
    ]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        reader = Reader()
        read_cases = []
        for filename, content, offset, limit in read_inputs:
            path = root / filename
            path.write_bytes(content)
            result = reader.read_file(str(path), offset, limit).to_dict()
            read_cases.append(
                {
                    "filename": filename,
                    "hex": content.hex(),
                    "offset": offset,
                    "limit": limit,
                    "result": result,
                }
            )
    files = [
        "tools/file_operations.py",
        "tools/file_operations_common.py",
        "tools/fuzzy_match.py",
        "tools/todo_tool.py",
        "tools/tool_output_truncate.py",
    ]
    return {
        "upstream": "https://github.com/NousResearch/hermes-agent",
        "version": "v0.22.5",
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
        ).strip(),
        "source_sha256": {
            name: hashlib.sha256((checkout / name).read_bytes()).hexdigest()
            for name in files
        },
        "method": "Original upstream leaf modules and original AST method bodies executed with fixed default limits; no FlashRSI imports.",
        "fuzzy": fuzzy_cases,
        "reads": read_cases,
        "todo": todo_cases,
        "truncation": [
            {
                "text": value,
                "limit": limit,
                "result": truncate.truncate_head_tail(value, limit),
            }
            for value, limit in [
                ("abcdef", 6),
                ("abcdefghijklmnop", 10),
                ("一二三四五六七八", 5),
            ]
        ],
    }


if __name__ == "__main__":
    evidence = generate(Path(sys.argv[1]).resolve())
    Path(__file__).with_name("hermes_tools_upstream.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
    )
