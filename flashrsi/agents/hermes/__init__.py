"""Hermes Target/Worker adapter backed by the selected Python Snapshot."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import inspect
import math
import sys
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any, Iterator

from flashrsi._records import _redact, _secrets
from flashrsi.core import Agent, Trajectory


class Hermes(Agent):
    """Execute Hermes's supported headless semantics from versioned Python files."""

    name = "hermes"
    description = "Hermes with a versioned Python runtime, prompts, skills and tools."
    instruction_file = "SOUL.md"
    _container_dependencies = ("httpx", "Pillow", "regexrs-py")

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        secrets = sorted(set(_secrets(self.config)), key=len, reverse=True)
        try:
            _validate(self.config, self.files_dir)
            config = _plain(self.config)
            with TemporaryDirectory(prefix="flashrsi-hermes-") as temporary:
                task_dir = working_dir or Path(temporary) / "work"
                task_dir.mkdir(parents=True, exist_ok=True)
                with _native_runtime(self.files_dir) as native:
                    state = {}
                    options = (
                        {"_state": state}
                        if "_state" in inspect.signature(native.run).parameters
                        else {}
                    )
                    try:
                        result = await asyncio.wait_for(
                            native.run(
                                config, prompt, task_dir, self.files_dir, **options
                            ),
                            timeout=float(config.get("timeout", 300)),
                        )
                    except TimeoutError:
                        result = state.get("result")
                        if result is None:
                            raise
                        result = dict(
                            result if isinstance(result, Mapping) else vars(result)
                        )
                        result.update(
                            status="error",
                            error_message=f"Hermes timed out after {config.get('timeout', 300):g}s",
                        )
            if not isinstance(result, Mapping):
                result = vars(result)
            error = result.get("error_message")
            failed = result.get("status", "finished") != "finished" or bool(error)
            return Trajectory(
                status="error" if failed else "finished",
                output=_redact(str(result.get("output", "") or ""), secrets),
                messages=_redact(list(result.get("events", [])), secrets),
                usage=_redact(dict(result.get("usage", {})), secrets),
                error_message=(
                    _redact(str(error or "Hermes runtime failed"), secrets)
                    if failed
                    else None
                ),
            )
        except TimeoutError:
            return Trajectory(
                status="error",
                error_message=f"Hermes timed out after {self.config.get('timeout', 300):g}s",
            )
        except Exception as exc:
            return Trajectory(status="error", error_message=_redact(str(exc), secrets))


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return copy.deepcopy(value)


def _runtime(root: Path) -> Path:
    runtime = root / "runtime" / "hermes_native"
    if not (runtime / "__init__.py").is_file():
        raise ValueError("Hermes Snapshot is missing runtime/hermes_native/__init__.py")
    return runtime.resolve()


def _validate(config: Mapping[str, Any], files_dir: Path | None = None) -> None:
    if config.get("cli_path") or config.get("node_path"):
        raise ValueError(
            "Hermes executes the Snapshot's Python runtime; cli_path/node_path are unsupported"
        )
    llm = config.get("llm", {})
    model = llm.get("model_name")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Hermes llm.model_name must be a non-empty string")
    key = llm.get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Hermes llm.api_key is required for this role")
    mode = (
        llm.get("model_api")
        or llm.get("api_mode")
        or config.get("api_mode", "chat_completions")
    )
    if mode not in {
        "chat_completions",
        "openai-completions",
        "responses",
        "openai-responses",
        "codex_responses",
        "anthropic_messages",
        "anthropic-messages",
    }:
        raise ValueError(
            "Hermes supports Chat Completions, Responses and Anthropic Messages APIs"
        )
    timeout = config.get("timeout", 300)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("Hermes timeout must be a finite positive number")
    if "max_iterations" in config and "max_turns" in config:
        raise ValueError("Set only one of Hermes max_iterations and max_turns")
    limit = config.get("max_iterations", config.get("max_turns", sys.maxsize))
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("Hermes max_iterations must be a positive integer")
    root = files_dir
    if root is None:
        root = Path(config.get("source_dir", Path(__file__).parent)).expanduser()
    _runtime(root)


@contextmanager
def _native_runtime(files_dir: Path) -> Iterator[ModuleType]:
    root = _runtime(files_dir)
    name = "flashrsi_hermes_native_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(
        name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    if spec is None or spec.loader is None:
        raise ValueError("Hermes Snapshot runtime could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for imported in list(sys.modules):
            if imported == name or imported.startswith(name + "."):
                sys.modules.pop(imported, None)


__all__ = ["Hermes"]
