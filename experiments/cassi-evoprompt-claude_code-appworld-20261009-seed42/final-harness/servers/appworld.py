"""Run-local stdio MCP bridge; only execute is exposed, never controller grading."""
import asyncio
import json
from pathlib import Path
import sys


async def execute(code):
    socket = json.loads(Path('appworld-connection.json').read_text())['socket']
    reader, writer = await asyncio.open_unix_connection(socket, limit=8 * 1024 * 1024)
    try:
        writer.write((json.dumps({'operation': 'execute', 'code': code}) + '\n').encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request['method']
        try:
            if method == 'initialize':
                result = {'protocolVersion': request['params']['protocolVersion'],
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'appworld', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'appworld_execute',
                          'description': 'Execute Python in the supplied persistent AppWorld shell. Print outputs; discover app APIs through apis.api_docs.',
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
