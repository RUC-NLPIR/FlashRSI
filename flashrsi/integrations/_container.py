"""Private container entry point for a pinned Agent execution, without Harbor."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path

import yaml

from flashrsi._records import _config_record, _redact, _secrets, _trajectory_record
from flashrsi.config import _ConfigLoader
from flashrsi.core import Agent, Snapshot, Trajectory


def _agent_class(import_path: str) -> type[Agent]:
    """Resolve an importable adapter without a registry of harness names."""
    if not isinstance(import_path, str) or import_path.count(":") != 1:
        raise ValueError("agent_class must be an importable module:qualname")
    module_name, qualname = import_path.split(":")
    if module_name == "__main__" or not all(
        part.isidentifier() for part in (*module_name.split("."), *qualname.split("."))
    ):
        raise ValueError("agent_class must be an importable module:qualname")
    try:
        adapter = importlib.import_module(module_name)
        for name in qualname.split("."):
            adapter = getattr(adapter, name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ValueError(f"Cannot import agent_class {import_path!r}") from exc
    if (
        not isinstance(adapter, type)
        or not issubclass(adapter, Agent)
        or adapter is Agent
    ):
        raise ValueError("agent_class must refer to an Agent subclass")
    return adapter


async def _run(request_path: Path, output_path: Path) -> int:
    request = {}
    config = {}
    snapshot = None
    try:
        # This file carries credentials. Remove it before parsing or starting
        # the harness so task tools cannot discover it while solving the task.
        try:
            raw = request_path.read_text(encoding="utf-8")
        finally:
            request_path.unlink(missing_ok=True)
        request = json.loads(raw)
        try:
            config = dict(yaml.load(request["config_yaml"], Loader=_ConfigLoader))
        except yaml.YAMLError:
            raise ValueError("Invalid container config YAML") from None
        adapter = _agent_class(request["agent_class"])
        if "name" in config and config["name"] != adapter.name:
            raise ValueError("container config name does not match agent_class")
        config.pop("source_dir", None)
        snapshot = Snapshot.load(Path(request["snapshot_path"]))
        if snapshot.agent_type != adapter.name:
            raise ValueError("container Snapshot agent_type does not match agent_class")

        agent = adapter(config)
        agent._check_container()
        # This process receives a complete, validated version from the host.
        # Recapturing its files as a seed would discard the original lineage.
        agent._snapshot = snapshot
        result = await agent.run(request["prompt"], working_dir=Path.cwd())
    except Exception as exc:
        result = Trajectory(
            status="error",
            messages=(
                {
                    "type": "RunConfig",
                    "config": _config_record(config),
                    "snapshot_id": snapshot.id if snapshot is not None else None,
                },
            ),
            error_message=str(exc) or type(exc).__name__,
        )

    secrets = sorted(
        set(_secrets(config) + _secrets(request) + _secrets(os.environ)),
        key=len,
        reverse=True,
    )
    record = _redact(_trajectory_record(result), secrets)
    output_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return int(result.status == "error")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    return asyncio.run(_run(args.request_path, args.output_path))


if __name__ == "__main__":
    raise SystemExit(_main())
