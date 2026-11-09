"""MiniAgent workspace tool: execute code in the official AppWorld shell."""

import asyncio
import json

# Keep tool output bounded for the LLM. AppWorld API-doc calls can return very
# large payloads, and unbounded output consumes the model's context before any
# task-relevant call is made.
_OUTPUT_LIMIT_CHARS = 32 * 1024
_STREAM_LIMIT_BYTES = 8 * 1024 * 1024

_TRUNCATION_NOTE = (
    "\n[appworld: output truncated to {limit} characters; "
    "{omitted} characters omitted]"
)


def _stringify(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _first_present(mapping: dict, keys) -> object:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_LIMIT_CHARS:
        return text
    omitted = len(text) - _OUTPUT_LIMIT_CHARS
    return text[:_OUTPUT_LIMIT_CHARS] + _TRUNCATION_NOTE.format(
        limit=_OUTPUT_LIMIT_CHARS, omitted=omitted
    )


def _module_hint(text: str) -> str:
    """Turn opaque sandbox import denials into an actionable next step."""
    if "Usage of the following module is not allowed: apis" in text:
        return (
            "\n[appworld hint] `apis` is already injected as a global in this shell. "
            "Remove `import apis` and call it directly, e.g. "
            "`apis.api_docs.show_app_descriptions()`."
        )
    if "Usage of the following modules is not allowed: importlib and sys" in text:
        return (
            "\n[appworld hint] `import sys`/`importlib` are blocked in this shell. "
            "Use the pre-injected `apis` and `requester` globals instead."
        )
    if "module is not allowed" in text:
        return (
            "\n[appworld hint] That import is blocked in this shell. "
            "Use the pre-injected `apis`/`requester` globals instead of importing modules."
        )
    return ""


def _format_response(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _truncate(raw) if raw else "(no output)"

    if isinstance(data, str):
        return _truncate(data) if data else "(no output)"

    if isinstance(data, dict):
        output = _first_present(data, ("output", "stdout", "result"))
        error = _first_present(data, ("error", "traceback", "exception", "stderr"))
        task_completed = data.get("task_completed")

        parts: list[str] = []
        if output is not None:
            parts.append(_stringify(output).rstrip())
        if error is not None:
            err_text = _stringify(error).strip()
            if err_text:
                parts.append(err_text)
        full_text = "\n".join(parts) if parts else _stringify(data)

        hint = _module_hint(full_text)
        text = _truncate(full_text)
        if hint:
            text += hint
        if task_completed is not None:
            text += f"\n[appworld task_completed: {json.dumps(task_completed)}]"
        return text

    return _truncate(_stringify(data))


async def call(args, ctx):
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")

    endpoint = json.loads(
        (ctx.working_dir / "appworld-connection.json").read_text()
    )["socket"]

    reader, writer = await asyncio.open_unix_connection(
        endpoint, limit=_STREAM_LIMIT_BYTES
    )
    try:
        payload = json.dumps({"operation": "execute", "code": code}) + "\n"
        writer.write(payload.encode())
        await writer.drain()
        raw = (await reader.readline()).decode("utf-8", errors="replace").strip()
    finally:
        writer.close()
        await writer.wait_closed()

    return _format_response(raw)
