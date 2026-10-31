"""Pure-Python adapter for the Pi coding-agent contract.

The selected Agent Snapshot contains the Python runtime under
``runtime/pi_native``. The adapter loads that package from the checked-out
Snapshot, so changing a Snapshot changes the code, prompts, skills, and tools
that actually execute.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any, Iterator

from flashrsi._records import _redact, _secrets
from flashrsi.core import Agent, Trajectory

_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}


class Pi(Agent):
    """Run the selected pure-Python Pi-compatible runtime."""

    name = "pi"
    description = (
        "Pi-compatible Python coding agent with versioned resources and tools."
    )
    instruction_file = "AGENTS.md"
    _container_dependencies = ("httpx",)

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        config = self.config
        timeout = config.get("timeout", 300)
        if type(timeout) not in (int, float) or timeout <= 0:
            return Trajectory(
                status="error", error_message="Pi timeout must be positive"
            )
        try:
            provider, model = _model(config["llm"])
            _thinking(config)
            _runtime(self.files_dir)
            native_config = _plain_config(config)
        except (KeyError, TypeError, ValueError) as exc:
            return Trajectory(status="error", error_message=str(exc))

        secrets = sorted(set(_secrets(config)), key=len, reverse=True)
        with TemporaryDirectory(prefix="flashrsi-pi-") as temporary:
            task_dir = working_dir or Path(temporary) / "work"
            task_dir.mkdir(parents=True, exist_ok=True)
            try:
                with _native_runtime(self.files_dir) as native:
                    result = await asyncio.wait_for(
                        native.run(native_config, prompt, task_dir, self.files_dir),
                        timeout=float(timeout),
                    )
            except TimeoutError:
                return Trajectory(
                    status="error",
                    error_message=f"Pi timed out after {timeout:g}s",
                )
            except Exception as exc:
                return Trajectory(
                    status="error",
                    error_message=_redact(str(exc), secrets),
                )

        events = _value(result, "events", [])
        output = _value(result, "output", "")
        usage = _value(result, "usage", {})
        status = _value(result, "status", "finished")
        error = _value(result, "error_message", _value(result, "error", None))
        if not isinstance(events, list):
            events = list(events) if isinstance(events, (tuple, list)) else []
        if not isinstance(output, str):
            output = str(output or "")
        if not isinstance(usage, Mapping):
            usage = {}
        if error or status != "finished":
            diagnostic = str(error or "Pi runtime failed")
            return Trajectory(
                status="error",
                messages=_redact(events, secrets),
                usage=_redact(dict(usage), secrets),
                error_message=_redact(diagnostic, secrets),
            )
        return Trajectory(
            status="finished",
            output=_redact(output, secrets),
            messages=_redact(events, secrets),
            usage=_redact(dict(usage), secrets),
        )


PiAgent = Pi


def _plain_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Detach the call-local Config object before handing it to Snapshot code."""

    def plain(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): plain(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(value) for value in item]
        if isinstance(item, Path):
            return str(item)
        return copy.deepcopy(item)

    value = plain(config)
    return json.loads(json.dumps(value, default=str))


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


@contextmanager
def _native_runtime(files_dir: Path) -> Iterator[ModuleType]:
    root = _runtime(files_dir)
    module_name = f"flashrsi_pi_native_{abs(hash(root))}_{id(root)}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise ValueError("Pi Snapshot runtime could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in list(sys.modules):
            if name == module_name or name.startswith(module_name + "."):
                sys.modules.pop(name, None)


def _runtime(files_dir: Path) -> Path:
    runtime = files_dir / "runtime" / "pi_native"
    if not runtime.is_dir() or not (runtime / "__init__.py").is_file():
        raise ValueError("Pi Snapshot is missing runtime/pi_native/__init__.py")
    return runtime


def _source_dir(config: Mapping[str, Any]) -> Path:
    value = config.get("source_dir")
    source = (
        Path(value).expanduser()
        if value is not None
        else Path(__file__).resolve().parent
    )
    if not source.is_dir():
        raise ValueError("Pi source_dir must be an existing directory")
    return source.resolve()


def _executable(config: Mapping[str, Any], files_dir: Path | None = None) -> str:
    """Return the native Python runtime entry point for compatibility checks."""
    return str(_runtime(files_dir or _source_dir(config)))


def _model(llm: Mapping[str, Any]) -> tuple[str, str]:
    value = llm.get("model_name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Pi llm.model_name must be a non-empty string")
    value = value.strip()
    configured_provider = llm.get("provider_name")
    if "/" in value:
        provider, model = value.split("/", 1)
    else:
        provider, model = configured_provider, value
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(
            "Pi llm.model_name must use provider/model, or set llm.provider_name"
        )
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Pi llm.model_name must include a model id")
    return provider.strip(), model.strip()


def _thinking(config: Mapping[str, Any]) -> str | None:
    llm = config.get("llm", {})
    value = config.get(
        "thinking",
        config.get(
            "reasoning_effort",
            llm.get("thinking", llm.get("reasoning_effort", llm.get("effort"))),
        ),
    )
    if value == "none":
        value = "off"
    if value is None:
        return None
    if not isinstance(value, str) or value not in _THINKING_LEVELS:
        raise ValueError(
            "Pi thinking must be one of: " + ", ".join(sorted(_THINKING_LEVELS))
        )
    return value


__all__ = ["Pi", "PiAgent"]
