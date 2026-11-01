"""Explicit route/tool inputs and private temporary files for native HTTP."""

import tempfile
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

settings = ContextVar("hermes_anthropic_settings", default={})


def _nous_inference_env_override():
    return settings.get().get("nous_inference_base_url", "")


class _ToolRegistry:
    def get_entry(self, name):
        return name in settings.get().get("registered_tools", ())


tool_registry = _ToolRegistry()


def _secure_cache_dir(*args):
    # Conversion cleans both transient files in its finally block. The parent
    # directory is private and owned by this process, with no user profile I/O.
    return Path(tempfile.mkdtemp(prefix="flashrsi-hermes-vision-"))


def _write_private_bytes(path, data):
    Path(path).write_bytes(data)
    Path(path).chmod(0o600)


def get_version_info():
    return SimpleNamespace(base_version="0.22.5")
