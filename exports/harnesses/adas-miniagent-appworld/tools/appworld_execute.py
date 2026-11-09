"""MiniAgent workspace tool: execute code in the official AppWorld shell."""
import asyncio
import json


def _format_bool(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def call(args, ctx):
    endpoint = json.loads((ctx.working_dir / 'appworld-connection.json').read_text())['socket']
    reader, writer = await asyncio.open_unix_connection(endpoint, limit=8 * 1024 * 1024)
    try:
        writer.write((json.dumps({'operation': 'execute', 'code': args['code']}) + '\n').encode())
        await writer.drain()
        raw = (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()

    # The shell replies with one JSON object. Surface the fields the agent
    # actually needs (especially `task_completed`) instead of forcing the LLM
    # to parse compact JSON in the middle of a long trace.
    try:
        data = json.loads(raw)
    except Exception:
        return raw

    if not isinstance(data, dict):
        return raw

    lines = []
    output = data.get("output", "")
    if output:
        lines.append("OUTPUT:\n" + str(output))
    lines.append("TASK_COMPLETED: " + _format_bool(data.get("task_completed")))
    for key, value in data.items():
        if key in {"output", "task_completed"}:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
