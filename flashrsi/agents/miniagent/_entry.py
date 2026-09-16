"""Private process bridge. This adapter is deliberately outside Snapshot rules."""

import asyncio
import json
import os
import sys


async def _main():
    request = json.load(sys.stdin)
    # Reserve stdout for the result; harness/tool output goes to stderr.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8") as result_stream:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        # -I excludes cwd/PYTHONPATH. Only the selected version provides runtime.
        sys.path.insert(0, request["workspace_dir"])
        from runtime.agent import run

        result = await run(**request)
        print(json.dumps(result, ensure_ascii=False), file=result_stream)


if __name__ == "__main__":
    asyncio.run(_main())
