"""Run-local stdio MCP bridge; only execute is exposed, never controller grading."""
import asyncio
import json
from pathlib import Path
import sys

CONNECT_TIMEOUT = 15.0
EXECUTE_TIMEOUT = 180.0

TOOL_DESCRIPTION = (
    "Execute Python in the supplied persistent AppWorld shell. "
    "`apis` is already imported; never write `import apis`. "
    "Print everything you need returned. "
    "Use page_limit=20 and paginate with page_index until a page returns fewer than 20 items. "
    "For action tasks finish with `apis.supervisor.complete_task(status=\"success\")`; "
    "pass `answer` only when the instruction is a direct question (What/How many/How much/How long/Name/Which)."
)

# Enforce the AppWorld supervisor contract for complete_task:
# 1. For non-question (action) tasks, do not submit a status-report string as
#    the task answer.
# 2. For question tasks, normalize numeric answers by removing a single leading
#    "$" and thousands separators. Text answers are left untouched.
COMPLETE_TASK_GUARD = '''
try:
    if not getattr(apis.supervisor.complete_task, "_appworld_guarded", False):
        _orig_complete_task = apis.supervisor.complete_task

        def _is_question(instruction):
            try:
                instr = str(instruction).strip()
            except Exception:
                return True
            if not instr:
                return False
            lowered = instr.lower()
            if lowered.endswith("?"):
                return True
            starts = (
                "what ", "what is", "what was", "what are",
                "how many", "how much", "how long",
                "which ", "name the", "who ", "when ", "where ", "why ",
                "list ", "tell me",
            )
            return lowered.startswith(starts)

        def _normalize_answer(answer):
            if isinstance(answer, str):
                value = answer.strip()
                if value.startswith("$"):
                    value = value[1:].strip()
                candidate = value.replace(",", "")
                try:
                    float(candidate)
                    return candidate
                except ValueError:
                    return value
            return answer

        def _guarded_complete_task(answer=None, status="success"):
            if answer is not None:
                try:
                    task = apis.supervisor.show_active_task()
                    instruction = task.get("instruction") if hasattr(task, "get") else getattr(task, "instruction", None)
                except Exception:
                    instruction = None
                if instruction and not _is_question(instruction):
                    answer = None
                    if status is None:
                        status = "success"
                else:
                    answer = _normalize_answer(answer)
            return _orig_complete_task(answer=answer, status=status)

        _guarded_complete_task._appworld_guarded = True
        apis.supervisor.complete_task = _guarded_complete_task
except Exception:
    pass
'''


def _maybe_guard(code):
    if 'complete_task' in code:
        return COMPLETE_TASK_GUARD + code
    return code


async def execute(code):
    socket = json.loads(Path('appworld-connection.json').read_text())['socket']
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(socket, limit=8 * 1024 * 1024),
        timeout=CONNECT_TIMEOUT,
    )
    try:
        guarded_code = _maybe_guard(code)
        writer.write((json.dumps({'operation': 'execute', 'code': guarded_code}) + '\n').encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=EXECUTE_TIMEOUT)
        return line.decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if 'id' not in request:
            continue
        method = request['method']
        try:
            if method == 'initialize':
                result = {'protocolVersion': request['params']['protocolVersion'],
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'appworld', 'version': '1.2.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'appworld_execute',
                          'description': TOOL_DESCRIPTION,
                          'inputSchema': {'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code'], 'additionalProperties': False}}]}
            elif method == 'tools/call':
                if request['params']['name'] != 'appworld_execute':
                    raise ValueError('Unknown tool')
                output = asyncio.run(execute(request['params']['arguments']['code']))
                result = {'content': [{'type': 'text', 'text': output}]}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                continue
        except Exception as error:
            result = {'content': [{'type': 'text', 'text': str(error)}], 'isError': True}
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


if __name__ == '__main__':
    main()
