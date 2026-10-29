"""Fixed subprocess loader. All harness imports resolve inside the selected copy."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import signal
import sys
from pathlib import Path


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


async def main(request):
    root = Path(request["home"]) / "python_core"
    if not (root / "__init__.py").is_file():
        raise ValueError("Selected Snapshot is missing python_core/__init__.py")
    # Compile selected modules before any model call, including modules whose
    # feature is currently disabled. Never resolve a host-package fallback.
    for path in root.rglob("*.py"):
        if not any(part.endswith("_assets") for part in path.relative_to(root).parts):
            compile(path.read_bytes(), str(path), "exec")
    spec = importlib.util.spec_from_file_location(
        "selected_codex_core",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from selected_codex_core.loop import run_session

    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    result = await run_session(request, emit)
    # History stays in the selected runtime; the adapter needs only this result.
    result.pop("history", None)
    emit({"type": "flashrsi.core.completed", **result})


if __name__ == "__main__":
    try:
        asyncio.run(main(json.load(sys.stdin)))
    except BaseException as error:
        emit(
            {
                "type": "flashrsi.core.completed",
                "status": "error",
                "output": "",
                "usage": {},
                "error_message": str(error) or type(error).__name__,
            }
        )
