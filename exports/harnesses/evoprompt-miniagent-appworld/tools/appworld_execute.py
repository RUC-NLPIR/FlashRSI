"""MiniAgent workspace tool: execute code in the official AppWorld shell."""
import asyncio
import json

async def call(args, ctx):
    endpoint = json.loads((ctx.working_dir / 'appworld-connection.json').read_text())['socket']
    reader, writer = await asyncio.open_unix_connection(endpoint, limit=8 * 1024 * 1024)
    try:
        writer.write((json.dumps({'operation': 'execute', 'code': args['code']}) + '\n').encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()
        await writer.wait_closed()
