"""API-surface guard for AppWorld calls.

This middleware prevents the most common AppWorld failure mode: the agent
invents a top-level `apis.<service>` name before inspecting `apis`. It keeps a
small deterministic registry of top-level API names parsed from the output of
`print(dir(apis))` calls. If the agent tries to use an unobserved top-level
service, the call is skipped and the model is told to orient first.

The guard is deliberately narrow:
  * it only blocks direct `apis.<name>` attribute access, not `apis` itself,
    `dir(apis)`, `help(apis)`, `getattr(apis, ...)`, or variables;
  * once `print(dir(apis))` has been observed but its output could not be
    parsed, the guard switches to permissive mode instead of blocking forever.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_STATE_KEY = "api_guard"
_MARKER = "[api_guard]"
_MAX_SHOWN = 40


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _dotted_path(node: ast.AST) -> str:
    """Return a dotted path string for simple Name/Attribute chains."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_path(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _dir_targets(code: str) -> list[str]:
    """Return paths passed to `dir(...)` in source order."""
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
            if path == "apis" or path.startswith("apis."):
                targets.append(path)
    return targets


def _direct_apis_attrs(code: str) -> set[str]:
    """Return top-level attribute names accessed directly on `apis`."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "apis":
                attrs.add(node.attr)
    return attrs


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def _looks_like_shell_result(result: str) -> bool:
    """True only for real AppWorld shell replies, not middleware skip text."""
    if not result:
        return False
    if "OUTPUT:" in result or re.search(r"^TASK_COMPLETED\s*:", result, re.M):
        return True
    try:
        data = json.loads(result)
        return isinstance(data, dict) and "task_completed" in data
    except Exception:
        return False


def _extract_output(result: str) -> str:
    """Return the shell stdout block emitted by appworld_execute."""
    if not result:
        return ""
    match = re.search(r"^OUTPUT:\n(.*?)(?=^TASK_COMPLETED\s*:|\Z)", result, re.S | re.M)
    if not match:
        # Raw fallback: the original compact JSON had an `output` field.
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
        lists.append(members)
    return lists


def _state(ctx: Any) -> dict:
    state = getattr(ctx, "state", None)
    if state is None:
        return {}
    return state.setdefault(_STATE_KEY, {})


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


async def after_tool(name: str, args: dict, result: str, ctx) -> str:
    """Learn the top-level API surface from `dir(apis...)` output."""
    if name != "appworld_execute":
        return result

    result_text = result or ""
    if not _looks_like_shell_result(result_text):
        return result_text

    code = (args or {}).get("code", "")
    if not isinstance(code, str) or not code.strip():
        return result_text

    targets = _dir_targets(code)
    if not targets:
        return result_text

    state = _state(ctx)
    state.setdefault("orientation_seen", False)
    state["orientation_seen"] = True
    observed = state.setdefault("observed", {})

    output = _extract_output(result_text)
    lists = _string_lists(output)

    # Match `dir(...)` calls to the list representations they printed. Most
    # snippets print exactly one dir() result; when the number of printed lists
    # is ambiguous we leave the observed member set unknown (permissive) rather
    # than risk learning a wrong API inventory.
    if len(targets) == 1:
        path = targets[0]
        if len(lists) == 1:
            observed[path] = lists[0]
        else:
            observed.setdefault(path, None)
    elif len(lists) == len(targets):
        for path, members in zip(targets, lists):
            observed[path] = members
    else:
        for path in targets:
            observed.setdefault(path, None)

    return result_text


async def before_tool(name: str, args: dict, ctx) -> dict | None:
    """Block direct `apis.<unknown>` calls until orientation has happened."""
    if name != "appworld_execute":
        return None

    code = (args or {}).get("code", "")
    if not isinstance(code, str) or not code.strip():
        return None

    attrs = _direct_apis_attrs(code)
    if not attrs:
        return None

    state = _state(ctx)
    if not state:
        # No state means this middleware has not seen any appworld call yet.
        return _block(
            "Before calling `apis.<name>`, inspect the API surface first. "
            "Run exactly:\nprint(dir(apis))\n"
            "Then use only names printed in OUTPUT."
        )

    if not state.get("orientation_seen"):
        return _block(
            "Before calling `apis.<name>`, inspect the API surface first. "
            "Run exactly:\nprint(dir(apis))\n"
            "Then use only names printed in OUTPUT."
        )

    observed = state.get("observed") or {}
    apis_members = observed.get("apis")
    if apis_members is None:
        # Orientation happened but we could not parse the member list.
        # Permissive mode: do not risk blocking valid work forever.
        return None

    unknown = sorted(attr for attr in attrs if attr not in apis_members)
    if not unknown:
        return None

    known = sorted(apis_members)
    known_text = ", ".join(known[:_MAX_SHOWN])
    if len(known) > _MAX_SHOWN:
        known_text += ", ..."
    return _block(
        "Blocked `apis." + "`, `apis.".join(unknown) + "` because "
        "I have not observed that top-level API in `print(dir(apis))` output. "
        "Use only observed top-level names. "
        f"Observed top-level APIs ({len(known)}): {known_text}"
    )


def _block(message: str) -> dict:
    return {"action": "skip", "result": f"{_MARKER} {message}"}
