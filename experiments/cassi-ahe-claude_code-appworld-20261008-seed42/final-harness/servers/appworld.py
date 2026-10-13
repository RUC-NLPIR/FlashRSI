"""Run-local stdio MCP bridge; only execute is exposed, never controller grading."""
import asyncio
import json
from pathlib import Path
import re
import sys

# Actionable guidance appended whenever the AppWorld sandbox rejects an import of
# the pre-injected API client. Keep this general: it is about the execution
# contract, not about any one task.
_BLOCKED_IMPORT_HINT = (
    "The AppWorld API client `apis` is already pre-injected and available as a "
    "global object in the sandbox. Remove any `import apis...` statement and call "
    "`apis.<service>.<api>()` directly (for example, "
    "print(apis.api_docs.show_app_descriptions()))."
)

TOOL_DESCRIPTION = (
    "Execute Python code in the supplied persistent AppWorld shell and return its "
    "printed output. The AppWorld API client `apis` is already available as a "
    "pre-injected global object in that shell; call it directly, e.g. "
    "print(apis.api_docs.show_app_descriptions()). Do NOT use `import apis` or "
    "`import apis.api_docs`; those imports are blocked by the sandbox and will fail."
)

# Read the complete newline-delimited sidecar response instead of relying on
# StreamReader.readline(), whose configured buffer limit silently aborts over-long
# lines. AppWorld API-doc payloads are large; a clipped JSON object hides the API
# the agent needs and is indistinguishable from a clean early stop.
_RESPONSE_CHUNK_BYTES = 65536
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 15.0
_EXECUTE_TIMEOUT_SECONDS = 180.0

# Bound the decision-relevant portion of very large AppWorld results. The full
# response is still read from the sidecar; only the `output` string returned to
# the model is bounded, and the payload is explicitly marked as truncated so the
# model knows to re-query narrowly instead of proceeding on partial data.
_MAX_OUTPUT_CHARS = 24_000
_LARGE_OUTPUT_HINT = (
    "\n\n[... harness truncated this result: {omitted} characters omitted ...]\n"
    "This result was too large to return in full. Do not treat a truncated result "
    "as complete or as a reason to stop. Re-run a narrower query, e.g. "
    "print(apis.api_docs.show_api_doc(app_name=..., api_name=...)) for the exact "
    "API you need, or print a smaller slice of the data you are looking for."
)

# Discovery helpers. Broad ``show_*_descriptions`` calls are read-only and return
# large, mostly low-signal description text. When we can, we keep only the entry
# names so the model can still choose the exact API, then point it at
# ``show_api_doc`` for the full schema.
_NAME_KEYS = ("name", "api_name", "app_name")
_DISCOVERY_NAME = re.compile(
    r"""['"](?:name|api_name|app_name)['"]\s*:\s*['"]([^'"]+)['"]"""
)
_BROAD_DISCOVERY_CALL = re.compile(
    r"apis\.api_docs\.(?:show_app_descriptions|show_api_descriptions)\s*\("
)
_DISCOVERY_SUMMARY_HINT = (
    "\n\nUse print(apis.api_docs.show_api_doc(app_name=..., api_name=...)) for "
    "the exact schema/description of the API you need. Prefer targeted "
    "show_api_doc calls over broad discovery."
)

# Progress and auth guidance. These are based on two observed, general failure
# modes: runs that only perform read-only API discovery and never mutate world
# state, and runs that hit an authorization error but do not try the app's login
# API.
_READ_ONLY_CALL = re.compile(
    r"apis\.[A-Za-z_]\w*\.(?:show_|get_|search_|list_|find_|query_|read_)\w*\s*\("
)
_MUTATING_CALL = re.compile(
    r"apis\.[A-Za-z_]\w*\.(?!show_|get_|search_|list_|find_|query_|read_)\w+\s*\("
)
_AUTH_ERROR = re.compile(
    r"(?i)(401|not authorized|access token is missing, invalid or expired)"
)
_READ_ONLY_PROGRESS_HINT = (
    "\n\n[harness] This code only queried/read data; it did not change AppWorld "
    "state. A final text answer alone will not pass because AppWorld grades final "
    "world state. Use what you learned to make the required state-changing call(s), "
    "then call print(apis.supervisor.complete_task(status=\"success\")) and wait "
    "for its result before ending."
)
_INCOMPLETE_PROGRESS_HINT = (
    "\n\n[harness] AppWorld reports task_completed=false for this call, so the "
    "task is not finished yet. Continue with the next required world-state change, "
    "then call print(apis.supervisor.complete_task(status=\"success\")) and wait "
    "for its result before ending."
)
_AUTH_ERROR_HINT = (
    "\n\n[harness] This result is an authorization error (401 / missing, invalid, "
    "or expired access token). Most AppWorld apps require an explicit login before "
    "private APIs can be called. Call the relevant app's login API with the "
    "credentials supplied in the task, then retry the failing call."
)


def _collect_names(value, names):
    """Collect ``name``-like string values from parsed JSON or Python objects."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _NAME_KEYS and isinstance(child, str):
                names.append(child)
            _collect_names(child, names)
    elif isinstance(value, list):
        for child in value:
            _collect_names(child, names)


def _unique_names(names):
    seen = set()
    unique = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _summarize_discovery_output(output):
    """Return a compact entry-name summary for broad discovery output.

    Broad discovery results are dominated by long descriptions. The model only
    needs the available names at this stage; it can then fetch the exact
    ``show_api_doc`` for the one API it plans to use. If the output cannot be
    parsed as JSON or contains no names, return ``None`` and let the normal
    truncation path handle it.
    """
    names = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, (dict, list)):
        _collect_names(data, names)

    if not names:
        names = _DISCOVERY_NAME.findall(output)

    names = _unique_names(names)
    if not names:
        return None

    shown = names[:120]
    omitted = len(names) - len(shown)
    lines = [f"- {name}" for name in shown]
    if omitted > 0:
        lines.append(f"- ... and {omitted} more entries")
    return (
        f"AppWorld discovery summary ({len(names)} entries):\n"
        + "\n".join(lines)
        + _DISCOVERY_SUMMARY_HINT
    )


def make_execute_result(raw, code=None):
    """Forward AppWorld's response, adding actionable guidance and bounding size.

    AppWorld returns a JSON object such as
    {"output": "Execution failed. Traceback:\nUsage of the following module is not
    allowed: apis.", "task_completed": false}. The transformations are:
    - broad API-discovery output is compacted to entry names when possible,
    - blocked-import outputs get a direct-call hint,
    - authorization errors get a login hint,
    - non-completed tool results get a continue/progress hint,
    - very large outputs are truncated with an explicit marker.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(payload, dict):
        return raw

    output = payload.get("output", "")
    if not isinstance(output, str):
        return raw

    changed = False
    summarized = False

    if code and _BROAD_DISCOVERY_CALL.search(code):
        summary = _summarize_discovery_output(output)
        if summary:
            payload["output"] = summary
            payload["summarized"] = True
            payload["original_chars"] = len(output)
            output = summary
            changed = True
            summarized = True

    if not summarized and len(output) > _MAX_OUTPUT_CHARS:
        omitted = len(output) - _MAX_OUTPUT_CHARS
        output = output[:_MAX_OUTPUT_CHARS] + _LARGE_OUTPUT_HINT.format(
            omitted=omitted
        )
        payload["truncated"] = True
        payload["truncation_reason"] = "harness_output_limit"
        changed = True

    blocked_import = "not allowed" in output
    if blocked_import:
        output = output.rstrip() + "\n" + _BLOCKED_IMPORT_HINT
        changed = True

    if _AUTH_ERROR.search(output):
        output = output.rstrip() + "\n" + _AUTH_ERROR_HINT
        changed = True

    if payload.get("task_completed") is False:
        if code is not None and _READ_ONLY_CALL.search(code) and not _MUTATING_CALL.search(code):
            output = output.rstrip() + "\n" + _READ_ONLY_PROGRESS_HINT
        else:
            output = output.rstrip() + "\n" + _INCOMPLETE_PROGRESS_HINT
        changed = True

    if changed:
        payload["output"] = output
        return json.dumps(payload)
    return raw


async def _read_full_response_line(reader):
    """Read one newline-delimited response without silently truncating it.

    ``StreamReader.readline()`` uses the stream limit and raises/aborts when a line
    is longer than that limit. Reading fixed-size chunks preserves the whole JSON
    line. Returns ``(payload_bytes, complete)`` where ``complete`` is ``False`` only
    when the peer closed the stream before sending the trailing newline.
    """
    chunks = []
    total = 0
    while True:
        chunk = await reader.read(_RESPONSE_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks), False
        chunks.append(chunk)
        total += len(chunk)
        if chunk.endswith(b"\n"):
            return b"".join(chunks), True
        if total > _MAX_RESPONSE_BYTES:
            raise ValueError(
                "AppWorld response exceeded the harness safety limit "
                f"({_MAX_RESPONSE_BYTES} bytes) before a newline was received."
            )


async def execute(code):
    """Execute ``code`` and return ``(response_text, is_error)``.

    Every tool call gets exactly one result, even when the sidecar is missing,
    times out, or returns a malformed/empty response. Transport failures are
    returned as explicit JSON error payloads rather than being dropped.
    """
    try:
        connection = json.loads(Path("appworld-connection.json").read_text())
        socket_path = connection["socket"]
    except Exception as error:
        return (
            json.dumps(
                {
                    "output": "",
                    "error": f"Failed to read appworld-connection.json: {error}",
                }
            ),
            True,
        )

    reader = writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path, limit=_MAX_RESPONSE_BYTES),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
        writer.write(
            (json.dumps({"operation": "execute", "code": code}) + "\n").encode()
        )
        await asyncio.wait_for(writer.drain(), timeout=_CONNECT_TIMEOUT_SECONDS)
        raw, complete = await asyncio.wait_for(
            _read_full_response_line(reader), timeout=_EXECUTE_TIMEOUT_SECONDS
        )
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if not text:
            return (
                json.dumps(
                    {"output": "", "error": "AppWorld returned an empty response"}
                ),
                True,
            )
        if not complete:
            return (
                json.dumps(
                    {
                        "output": text,
                        "truncated": True,
                        "error": (
                            "AppWorld closed the connection before the response "
                            "newline was received; the payload above may be incomplete."
                        ),
                    }
                ),
                True,
            )
        return text, False
    except asyncio.TimeoutError:
        return (
            json.dumps(
                {"output": "", "error": "AppWorld execute timed out; the sidecar did not respond"}
            ),
            True,
        )
    except Exception as error:
        return (
            json.dumps({"output": "", "error": f"AppWorld execute failed: {error}"}),
            True,
        )
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


def _jsonrpc_error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(request_id, output, is_error=False, code=None):
    result = {"content": [{"type": "text", "text": make_execute_result(output, code=code)}]}
    if is_error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_request(request):
    """Handle one JSON-RPC request, returning a response or ``None`` for notifications."""
    if not isinstance(request, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")
    if "id" not in request:
        # JSON-RPC notification (for example, notifications/initialized). Never
        # respond to it.
        return None
    request_id = request.get("id")
    method = request.get("method")

    try:
        if method == "initialize":
            params = request.get("params") or {}
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "appworld", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "appworld_execute",
                            "description": TOOL_DESCRIPTION,
                            "inputSchema": {
                                "type": "object",
                                "properties": {"code": {"type": "string"}},
                                "required": ["code"],
                                "additionalProperties": False,
                            },
                        }
                    ]
                },
            }
        if method == "tools/call":
            params = request.get("params") or {}
            if params.get("name") != "appworld_execute":
                raise ValueError("Unknown tool")
            arguments = params.get("arguments") or {}
            code = arguments.get("code", "")
            if not isinstance(code, str):
                raise ValueError("`code` must be a string")
            output, is_error = asyncio.run(execute(code))
            return _tool_result(request_id, output, is_error, code)
        return _jsonrpc_error(request_id, -32601, "Method not found")
    except Exception as error:
        # Isolate per-request failures so one bad tool call can never crash the
        # bridge and strand its sibling requests.
        return _tool_result(request_id, str(error), True)


def _write(message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            _write(_jsonrpc_error(None, -32700, "Parse error"))
            continue

        if isinstance(data, list):
            # JSON-RPC batch: answer every request in the batch exactly once.
            if not data:
                _write(_jsonrpc_error(None, -32600, "Invalid Request"))
                continue
            responses = []
            for item in data:
                response = handle_request(item)
                if response is not None:
                    responses.append(response)
            if responses:
                _write(responses)
            continue

        response = handle_request(data)
        if response is not None:
            _write(response)


if __name__ == "__main__":
    main()
