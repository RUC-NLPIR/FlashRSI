"""Per-task transport compatibility for historical AppWorld tools."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from flashrsi.integrations._appworld_client import call


@asynccontextmanager
async def bridge(working_dir, options):
    """Expose only execute over the historical newline-delimited Unix socket."""
    descriptor = Path(working_dir) / "appworld-connection.json"
    clients, forwards = {}, set()
    stopping = False

    def forwarded(task):
        forwards.discard(task)
        # The caller may disconnect before a failed HTTP request completes.
        # Retrieve its exception even when no handler remains to await it.
        if not task.cancelled():
            task.exception()

    async def handle(reader, writer):
        try:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=5)
                request = json.loads(raw)
                if (
                    not isinstance(request, dict)
                    or set(request) != {"operation", "code"}
                    or request["operation"] != "execute"
                    or not isinstance(request["code"], str)
                    or not request["code"].strip()
                ):
                    raise ValueError(
                        "Legacy AppWorld bridge accepts only execute and code"
                    )
                # AppWorld actions can mutate state. Never automatically retry them.
                forward = asyncio.create_task(
                    asyncio.to_thread(
                        call,
                        options["url"],
                        "execute",
                        code=request["code"],
                        timeout=options["timeout"],
                    )
                )
                forwards.add(forward)
                forward.add_done_callback(forwarded)
                response = await asyncio.shield(forward)
            except Exception as exc:
                response = {"error": str(exc), "error_type": type(exc).__name__}
            raw = json.dumps(response, ensure_ascii=False).encode() + b"\n"
            writer.write(raw)
            await asyncio.wait_for(writer.drain(), timeout=5)
        except (ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    def connected(reader, writer):
        if stopping:
            writer.close()
            return
        task = asyncio.create_task(handle(reader, writer))
        clients[task] = writer
        task.add_done_callback(lambda task: clients.pop(task, None))

    # Short socket names also work when task/output paths exceed AF_UNIX limits.
    with TemporaryDirectory(prefix="flashrsi-aw-") as directory:
        socket = Path(directory) / "world.sock"
        server = await asyncio.start_unix_server(
            connected,
            str(socket),
            limit=1024 * 1024,
        )
        created = False

        async def cleanup():
            nonlocal stopping
            stopping = True
            server.close()
            pending = list(clients.items())
            for task, writer in pending:
                writer.close()
                task.cancel()
            await asyncio.gather(*(task for task, _ in pending), return_exceptions=True)
            await server.wait_closed()
            # A disconnected caller must not leave a mutation racing the grader.
            await asyncio.gather(*forwards, return_exceptions=True)
            if created:
                descriptor.unlink(missing_ok=True)

        try:
            socket.chmod(0o600)
            # Never overwrite a task file or follow a pre-existing symlink.
            with descriptor.open("x", encoding="utf-8") as stream:
                created = True
                json.dump({"socket": str(socket)}, stream)
            descriptor.chmod(0o600)
            yield
        finally:
            closing = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await closing
                raise
