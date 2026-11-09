"""Method-level API documentation injection for AppWorld.

After the main agent orients and then inspects a concrete top-level app with
`print(dir(apis.<app>))`, this middleware queues one read-only
`apis.api_docs.search_api_docs` call for that exact app. The main model sees the
app's method names, descriptions, and parameter names/types at the start of its
next turn, before it is tempted to guess a method or argument name.

This is intentionally narrow and low-risk:
  * it only fires after a *successful* `dir(apis.<app>)` call (a real shell
    result whose OUTPUT contains a parsed list of identifiers and no traceback);
  * it only fires for direct `apis.<app>` attributes, never `apis` itself;
  * it never documents the same app twice, and caps total injections;
  * the injected code is read-only and catches search errors;
  * it respects the runtime's one-injection-per-turn rule, so it cannot collide
    with autodoc/autodebug or recursively trigger itself.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_STATE_KEY = "method_docs"
_MAX_INJECTIONS = 4
_PAGE_LIMIT = 10

_OUTPUT_RE = re.compile(
    r"^OUTPUT:\n(.*?)(?=^TASK_COMPLETED\s*:|\Z)", re.S | re.M
)
_TASK_COMPLETED_LINE_RE = re.compile(r"(?im)^\s*TASK_COMPLETED\s*:")
_TRACEBACK_RE = re.compile(r"Traceback\s*\(most recent call last\):", re.I)

# Apps whose method inventory is known/irrelevant; documenting them wastes a
# read-only call and context. `api_docs` documents itself, and the supervisor's
# `complete_task` contract is already described in the skill/tool prompt.
_SKIP_APPS = {"api_docs", "supervisor"}


def _dotted_path(node: ast.AST) -> str:
    """Return a dotted path string for simple Name/Attribute chains."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_path(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _dir_app_targets(code: str) -> list[str]:
    """Return direct top-level app names passed to `dir(apis.<app>)`."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "dir" and len(node.args) == 1:
            path = _dotted_path(node.args[0])
            if path.startswith("apis.") and path.count(".") == 1:
                app = path.split(".", 1)[1]
                if app.isidentifier() and app not in _SKIP_APPS:
                    targets.append(app)
    return targets


def _looks_like_shell_result(result: str) -> bool:
    """True only for real AppWorld shell replies, not middleware skip text."""
    if not result:
        return False
    if "OUTPUT:" in result or _TASK_COMPLETED_LINE_RE.search(result):
        return True
    try:
        data = json.loads(result)
        return isinstance(data, dict) and "task_completed" in data
    except Exception:
        return False


def _extract_output(result: str) -> str:
    if not result:
        return ""
    match = _OUTPUT_RE.search(result)
    if not match:
        return result
    return match.group(1)


def _string_lists(text: str) -> list[set[str]]:
    """Extract Python lists of string identifiers from printed output."""
    if not text:
        return []
    lists: list[set[str]] = []
    for match in re.finditer(r"\[[^\[\]]*\]", text):
        segment = match.group(0)
        try:
            value = ast.literal_eval(segment)
        except Exception:
            continue
        if not isinstance(value, list):
            continue
        members: set[str] = set()
        for item in value:
            if isinstance(item, str) and item.isidentifier():
                members.add(item)
        if members:
            lists.append(members)
    return lists


def _state(ctx: Any) -> dict:
    state = getattr(ctx, "state", None)
    if state is None:
        return {}
    return state.setdefault(_STATE_KEY, {})


def _build_code(app: str) -> str:
    """Return a read-only snippet that prints compact docs for one app."""
    return "\n".join(
        [
            "print('APP_DOCS_FOR:', " + json.dumps(app) + ")",
            "try:",
            "    _docs = apis.api_docs.search_api_docs(query="
            + json.dumps(app)
            + ", page_index=0, page_limit=%d)" % _PAGE_LIMIT,
            "    for _doc in _docs:",
            "        print('\\n##', _doc.get('app_name'), '|', _doc.get('api_name'))",
            "        print(_doc.get('description'))",
            "        for _param in (_doc.get('parameters') or []):",
            "            print('  -', _param.get('name'), '|', _param.get('type'), "
            "'| required=', _param.get('required'), '|', _param.get('description'))",
            "        print('---')",
            "except Exception as _exc:",
            "    print('APP_DOCS_ERROR:', type(_exc).__name__, _exc)",
        ]
    )


async def after_tool(name: str, args: dict, result: str, ctx):
    """Queue targeted app docs after the first successful dir of that app."""
    if name != "appworld_execute":
        return result
    if getattr(ctx, "_in_injected_call", False):
        return result
    if getattr(ctx, "_pending_injections", None):
        return result

    code = (args or {}).get("code", "")
    if not isinstance(code, str) or not code.strip():
        return result

    targets = _dir_app_targets(code)
    if not targets:
        return result

    result_text = result or ""
    if not _looks_like_shell_result(result_text):
        return result_text

    # A failed dir call belongs to autodebug, not to method-doc injection.
    # Do not consume the single per-turn injection slot with docs when the
    # model should first see a diagnostic for the traceback.
    if _TRACEBACK_RE.search(result_text):
        return result_text

    # Only fire if the dir output actually parsed as a non-empty list of
    # identifiers. If we cannot see the app's method inventory, a bad doc query
    # would be no better than the current uncertainty and could waste a turn.
    output = _extract_output(result_text)
    if not _string_lists(output):
        return result_text

    state = _state(ctx)
    count = int(state.get("count", 0))
    if count >= _MAX_INJECTIONS:
        return result_text

    covered = state.setdefault("covered", set())
    for app in targets:
        if app in covered:
            continue
        covered.add(app)
        state["count"] = count + 1
        return {
            "result": result_text,
            "inject": [
                {"name": "appworld_execute", "args": {"code": _build_code(app)}}
            ],
        }

    return result_text
