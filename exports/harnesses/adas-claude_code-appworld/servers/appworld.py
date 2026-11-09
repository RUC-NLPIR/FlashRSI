"""Run-local stdio MCP bridge for AppWorld.

The bridge exposes a small set of structured tools on top of the persistent
AppWorld shell.  Every tool except the raw ``execute`` tool reduces a common,
error-prone Python snippet to a single validated call:

* ``appworld_execute``    arbitrary Python in the AppWorld shell
* ``appworld_call``       one ``apis.<app>.<api>(**params)`` call
* ``appworld_task``       active task + supervisor credentials + app catalog
* ``appworld_api_docs``   API names/descriptions or one detailed API doc
* ``appworld_complete``   mark the active task complete (with normalized answer)

The world process only accepts an ``execute`` operation, so the convenience
tools are compiled into a short code string and sent through the same
connection.  They do not bypass the world lifecycle guard or task grading.
"""
import asyncio
import json
from pathlib import Path
import sys


CONNECTION_FILE = "appworld-connection.json"
READ_LIMIT = 8 * 1024 * 1024


async def send_code(code: str) -> dict:
    """Execute *code* in the persistent AppWorld shell and return its JSON line."""
    socket = json.loads(Path(CONNECTION_FILE).read_text())["socket"]
    reader, writer = await asyncio.open_unix_connection(socket, limit=READ_LIMIT)
    try:
        writer.write((json.dumps({"operation": "execute", "code": code}) + "\n").encode())
        await writer.drain()
        raw = (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()

    if not raw:
        return {"error": "AppWorld shell returned an empty response."}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"output": raw}


def format_world_result(data: dict) -> str:
    """Turn a world response dict into a compact, model-friendly string."""
    if not isinstance(data, dict):
        return str(data)

    if data.get("task_terminal"):
        return "TASK TERMINAL: " + json.dumps(data, ensure_ascii=False)

    parts = []
    if data.get("error"):
        parts.append("ERROR: " + str(data["error"]))
        if data.get("error_type"):
            parts.append("ERROR TYPE: " + str(data["error_type"]))
    if data.get("output"):
        parts.append(str(data["output"]).rstrip())
    if "task_completed" in data and data["task_completed"] is not None:
        parts.append("TASK_COMPLETED: " + ("true" if data["task_completed"] else "false"))
    if not parts:
        parts.append(json.dumps(data, ensure_ascii=False))
    return "\n".join(parts)


def _json_literal(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _call_tool_code(app_name: str, api_name: str, params: dict) -> str:
    return (
        "import json\n"
        f"params = json.loads({_json_literal(json.dumps(params, ensure_ascii=False))})\n"
        f"result = apis[{_json_literal(app_name)}][{_json_literal(api_name)}](**params)\n"
        "print(json.dumps(result, ensure_ascii=False, indent=2, default=str))\n"
    )


def _task_tool_code() -> str:
    return (
        "import json\n"
        "print(json.dumps({\n"
        "    'active_task': apis.supervisor.show_active_task(),\n"
        "    'supervisor_profile': apis.supervisor.show_profile(),\n"
        "    'supervisor_addresses': apis.supervisor.show_addresses(),\n"
        "    'supervisor_payment_cards': apis.supervisor.show_payment_cards(),\n"
        "    'account_passwords': apis.supervisor.show_account_passwords(),\n"
        "    'app_catalog': apis.api_docs.show_app_descriptions(),\n"
        "}, ensure_ascii=False, indent=2, default=str))\n"
    )


def _api_docs_tool_code(app_name: str, api_name=None) -> str:
    app_json = _json_literal(app_name)
    if api_name:
        api_json = _json_literal(api_name)
        return (
            "import json\n"
            f"result = apis.api_docs.show_api_doc(app_name={app_json}, api_name={api_json})\n"
            "print(json.dumps(result, ensure_ascii=False, indent=2, default=str))\n"
        )
    return (
        "import json\n"
        f"result = apis.api_docs.show_api_descriptions(app_name={app_json})\n"
        "print(json.dumps(result, ensure_ascii=False, indent=2, default=str))\n"
    )


def _complete_tool_code(answer, status: str) -> str:
    """Compile a completion call that converts only non-scalar answers for AppWorld.

    AppWorld's ``complete_task`` accepts only ``None | float | int | str``.  Its
    evaluator normalizes accepted scalar answers itself with ``answer_to_text``
    (stripping/lowercasing strings and rounding numbers), so those are passed
    through untouched to avoid double-normalization.  We only convert what the
    world would otherwise reject: JSON booleans become ``yes``/``no`` (or
    ``true``/``false`` when the instruction asks for true/false), and lists are
    sorted then joined with ``" | "`` exactly like the grader joins list answers.
    """
    answer_value_json = json.dumps(answer, ensure_ascii=False)
    status_value_json = json.dumps(status, ensure_ascii=False)
    code = (
        "import json\n"
        "\n"
        "def _answer_to_text(value):\n"
        "    if value is None:\n"
        "        return 'null'\n"
        "    if isinstance(value, (list, tuple)):\n"
        "        return ' | '.join(sorted([_answer_to_text(v) for v in value]))\n"
        "    if isinstance(value, str):\n"
        "        value = value.strip()\n"
        "    if isinstance(value, str) and (\n"
        "        (value.startswith('\"') and value.endswith('\"'))\n"
        "        or (value.startswith(\"'\") and value.endswith(\"'\"))\n"
        "    ):\n"
        "        value = value[1:-1]\n"
        "    try:\n"
        "        number = float(value)\n"
        "        if number.is_integer():\n"
        "            value = int(number)\n"
        "        else:\n"
        "            value = round(number, 2)\n"
        "    except (TypeError, ValueError):\n"
        "        pass\n"
        "    return str(value).strip().lower()\n"
        "\n"
        "def _normalize_answer(value, instruction):\n"
        "    if value is None:\n"
        "        return None\n"
        "    if isinstance(value, bool):\n"
        "        low = instruction.lower()\n"
        "        if ('true or false' in low) or ('true/false' in low):\n"
        "            return 'true' if value else 'false'\n"
        "        return 'yes' if value else 'no'\n"
        "    if isinstance(value, (list, tuple)):\n"
        "        return _answer_to_text(value)\n"
        "    if isinstance(value, dict):\n"
        "        return json.dumps(value, ensure_ascii=False, sort_keys=True)\n"
        "    return value\n"
        "\n"
        f"answer = json.loads({_json_literal(answer_value_json)})\n"
        f"status = json.loads({_json_literal(status_value_json)})\n"
        "instruction = ''\n"
        "try:\n"
        "    active_task = apis.supervisor.show_active_task()\n"
        "    instruction = active_task.get('instruction', '') or ''\n"
        "except Exception as exc:\n"
        "    instruction = '<unavailable: ' + str(exc) + '>'\n"
        "final_answer = _normalize_answer(answer, instruction)\n"
        "result = apis.supervisor.complete_task(answer=final_answer, status=status)\n"
        "print(json.dumps({'complete_result': result, 'instruction': instruction, "
        "'submitted_answer': final_answer}, ensure_ascii=False, indent=2, default=str))\n"
    )
    return code

TOOLS = [
    {
        "name": "appworld_execute",
        "description": (
            "Execute arbitrary Python code in the persistent AppWorld shell. "
            "Use this for multi-step or loop-based API work; use appworld_call "
            "for a single simple API call. The shell already exposes apis and "
            "requester, and variables persist between calls. Print results with "
            "print(json.dumps(result, indent=2)) when they are nested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "appworld_call",
        "description": (
            "Call one AppWorld API directly: apis[app_name][api_name](**params). "
            "Prefer appworld_execute when you need several calls, loops, or "
            "computed parameters in one interaction."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "api_name": {"type": "string"},
                "params": {
                    "type": "object",
                    "description": "Keyword arguments for the API, e.g. access_token and query fields.",
                },
            },
            "required": ["app_name", "api_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "appworld_task",
        "description": (
            "Read the active task, the supervisor's profile/addresses/payment "
            "cards/app account passwords, and a short catalog of available apps "
            "in one call. Use this at the start of every task and whenever you "
            "need credentials or need to decide which apps are relevant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "appworld_api_docs",
        "description": (
            "Get AppWorld API documentation. If api_name is omitted, returns "
            "compact name+description pairs for every API in app_name. If "
            "api_name is given, returns the detailed doc (parameters and "
            "response schemas) for that one API. Use appworld_call with "
            "api_docs.search_api_docs for keyword search across apps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "api_name": {"type": "string"},
            },
            "required": ["app_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "appworld_complete",
        "description": (
            "Mark the active AppWorld task complete. Pass answer only for "
            "question tasks. The server converts only non-scalar answers that "
            "AppWorld would otherwise reject: JSON booleans become yes/no (or "
            "true/false when the instruction asks for true/false), and lists "
            "are sorted and joined with \" | \" exactly like the grader. "
            "None, numbers, and strings pass through unchanged; AppWorld's "
            "grader already normalizes them. Omit answer for action tasks. "
            "Call exactly "
            "once, after the requested state has been verified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": ["string", "number", "boolean", "array", "null"],
                    "description": "Concise answer for question tasks; omit or null for action tasks.",
                },
                "status": {
                    "type": "string",
                    "enum": ["success", "fail"],
                    "description": "Completion status; defaults to success.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


def _tool_call_result(name: str, arguments: dict) -> dict:
    if name == "appworld_execute":
        code = arguments.get("code", "")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("appworld_execute requires a non-empty 'code' string")
        data = asyncio.run(send_code(code))
        return {"content": [{"type": "text", "text": format_world_result(data)}]}

    if name == "appworld_call":
        app_name = arguments.get("app_name")
        api_name = arguments.get("api_name")
        params = arguments.get("params", {})
        if not isinstance(app_name, str) or not app_name.strip():
            raise ValueError("appworld_call requires 'app_name'")
        if not isinstance(api_name, str) or not api_name.strip():
            raise ValueError("appworld_call requires 'api_name'")
        if not isinstance(params, dict):
            raise ValueError("appworld_call 'params' must be an object")
        data = asyncio.run(send_code(_call_tool_code(app_name, api_name, params)))
        return {"content": [{"type": "text", "text": format_world_result(data)}]}

    if name == "appworld_task":
        data = asyncio.run(send_code(_task_tool_code()))
        return {"content": [{"type": "text", "text": format_world_result(data)}]}

    if name == "appworld_api_docs":
        app_name = arguments.get("app_name")
        api_name = arguments.get("api_name")
        if not isinstance(app_name, str) or not app_name.strip():
            raise ValueError("appworld_api_docs requires 'app_name'")
        if api_name is not None and (not isinstance(api_name, str) or not api_name.strip()):
            raise ValueError("appworld_api_docs 'api_name' must be a non-empty string when set")
        data = asyncio.run(send_code(_api_docs_tool_code(app_name, api_name)))
        return {"content": [{"type": "text", "text": format_world_result(data)}]}

    if name == "appworld_complete":
        answer = arguments.get("answer", None)
        status = arguments.get("status", "success")
        if status not in ("success", "fail"):
            raise ValueError("appworld_complete 'status' must be 'success' or 'fail'")
        data = asyncio.run(send_code(_complete_tool_code(answer, status)))
        return {"content": [{"type": "text", "text": format_world_result(data)}]}

    raise ValueError(f"Unknown tool: {name}")


def main():
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        request_id = request["id"]
        method = request.get("method")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": request["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "appworld", "version": "1.2.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = _tool_call_result(
                    request["params"]["name"], request["params"].get("arguments", {})
                )
            else:
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": "Method not found"},
                        }
                    ),
                    flush=True,
                )
                continue
        except Exception as error:
            result = {
                "content": [{"type": "text", "text": str(error)}],
                "isError": True,
            }
        print(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, default=str),
            flush=True,
        )


if __name__ == "__main__":
    main()
