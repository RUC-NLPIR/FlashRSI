"""Automatic API-documentation retrieval for AppWorld.

After the main agent orients with `print(dir(apis))`, this middleware asks a
small side LLM for one to three short queries that are likely to cover the
APIs needed by the task. It then injects a single read-only `appworld_execute`
call in the same turn. That call prints the AppWorld app descriptions and the
most relevant API docs (app, API name, description, and parameter list) using
the official `apis.api_docs` search API.

This is intentionally narrow:
  * it only fires once, immediately after top-level orientation;
  * it only fires when the orientation output actually contains `api_docs`;
  * it only uses the read-only `api_docs` app, never a task-side-effecting API;
  * it caps the number of search queries and printed parameters;
  * search failures are caught and printed so a bad query cannot create a
    new traceback or a new autodebug injection.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_STATE_KEY = "autodoc"
_MAX_QUERIES = 3
_PAGE_LIMIT = 5

_TOP_LEVEL_DIR_RE = re.compile(r"\bdir\(\s*apis\s*\)")
_TASK_COMPLETED_LINE_RE = re.compile(r"(?im)^\s*TASK_COMPLETED\s*:")
_OUTPUT_RE = re.compile(
    r"^OUTPUT:\n(.*?)(?=^TASK_COMPLETED\s*:|\Z)", re.S | re.M
)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _looks_like_shell_result(result: str) -> bool:
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
        lists.append(members)
    return lists


def _state(ctx: Any) -> dict:
    state = getattr(ctx, "state", None)
    if state is None:
        return {}
    return state.setdefault(_STATE_KEY, {})


def _build_code(queries: list[str]) -> str:
    """Return a read-only snippet that prints compact, relevant API docs."""
    lines: list[str] = [
        "print('APP_DESCRIPTIONS')",
        "print(apis.api_docs.show_app_descriptions())",
    ]

    for query in queries:
        lines.append("print('\\nSEARCH_QUERY:', " + json.dumps(query) + ")")
        lines.append("_query = " + json.dumps(query))
        lines.append("try:")
        lines.append(
            "    _docs = apis.api_docs.search_api_docs("
            "query=_query, page_index=0, page_limit=%d)" % _PAGE_LIMIT
        )
        lines.append("    for _doc in _docs:")
        lines.append(
            "        print('\\n##', _doc.get('app_name'), '|', _doc.get('api_name'))"
        )
        lines.append("        print(_doc.get('description'))")
        lines.append("        for _param in (_doc.get('parameters') or []):")
        lines.append(
            "            print('  -', _param.get('name'), '|', _param.get('type'), "
            "'| required=', _param.get('required'), '|', _param.get('description'))"
        )
        lines.append("        print('---')")
        lines.append("except Exception as _exc:")
        lines.append("    print('API_DOC_SEARCH_ERROR:', type(_exc).__name__, _exc)")

    return "\n".join(lines)


async def after_tool(name: str, args: dict, result: str, ctx):
    """Queue one API-doc lookup after the first `print(dir(apis))`."""
    if name != "appworld_execute":
        return result
    if getattr(ctx, "_in_injected_call", False):
        return result
    if getattr(ctx, "_pending_injections", None):
        return result

    code = (args or {}).get("code", "")
    if not isinstance(code, str) or not _TOP_LEVEL_DIR_RE.search(code):
        return result

    result_text = result or ""
    if not _looks_like_shell_result(result_text):
        return result_text

    state = _state(ctx)
    if state.get("done"):
        return result_text

    # Only fire when we can see `api_docs` in the actual orientation output.
    # This avoids wasting an interaction when `dir(apis)` was only mentioned
    # in a comment/string or its output could not be parsed.
    output = _extract_output(result_text)
    parsed_lists = _string_lists(output)
    has_api_docs = any("api_docs" in members for members in parsed_lists)
    if not has_api_docs:
        return result_text

    available = sorted({member for members in parsed_lists for member in members})
    available_text = ", ".join(available) if available else "the apps from dir(apis)"
    question = getattr(ctx, "question", "") or ""
    prompt = (
        "You are selecting API documentation search queries for an AppWorld "
        "task. The top-level `apis` apps visible in the last output are: "
        f"{available_text}. Based on the task below, propose one to three "
        "short search queries for `apis.api_docs.search_api_docs` that are "
        "most likely to retrieve the exact APIs needed to complete the task. "
        "Use action-oriented terms (for example: 'send email', 'create "
        "playlist', 'pay request', 'file directory'). Do not invent specific "
        "API names; just provide good search strings.\n\n"
        f"TASK:\n{question}\n\n"
        'Return exactly one JSON object with a `queries` array of strings, '
        'for example:\n{"queries": ["send email", "gmail search threads"]}'
    )

    verdict = await ctx.side_text(prompt, purpose="autodoc", max_tokens=300)
    data = _extract_json(verdict or "")

    queries: list[str] = []
    if data:
        raw = data.get("queries", data.get("query", []))
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            queries = [
                str(q).strip()
                for q in raw
                if isinstance(q, str) and q.strip()
            ][:_MAX_QUERIES]

    state["done"] = True
    new_code = _build_code(queries)
    return {
        "result": result_text,
        "inject": [{"name": "appworld_execute", "args": {"code": new_code}}],
    }
