"""Task-local execution of Hermes v0.22.5's headless Python tool contracts.

Native file-read, fuzzy matching, result records, TodoStore and shell session
scripts are retained from upstream in ``_vendor``. This module supplies local
I/O and call-local state without importing a host Hermes installation/config.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ._vendor import file_operations_native
from ._vendor import limits as output_limits
from ._vendor.ansi_strip import strip_ansi
from ._vendor.binary_extensions import (
    has_binary_extension,
    has_opaque_document_extension,
)
from ._vendor.file_operations_common import (
    ExecuteResult,
    LintResult,
    PatchResult,
    ReadResult,
    SearchMatch,
    SearchResult,
    WriteResult,
    _detect_line_ending,
    _has_bom,
    _normalize_line_endings,
    _strip_bom,
    normalize_read_pagination,
    normalize_search_pagination,
)
from ._vendor.file_read_core import NativeReadCore, describe_binary_file
from ._vendor.fuzzy_match import boundary_note, fuzzy_find_and_replace
from ._vendor.inproc_lint import (
    _lint_json_inproc,
    _lint_python_inproc,
    _lint_toml_inproc,
    _lint_yaml_inproc,
)
from ._vendor.native_ignore import IgnoreRules, matches_glob, walk_lifo
from ._vendor.output_collector import _BoundedOutputCollector
from ._vendor.patch_parser import apply_v4a_operations, parse_v4a_patch
from ._vendor.patch_paths import (
    _collect_v4a_header_paths,
    _rewrite_v4a_patch_paths_for_host,
)
from ._vendor.read_budget import _apply_char_budget
from ._vendor.read_extract_stdlib import (
    EXTRACTABLE_EXTENSIONS,
    ExtractionError,
    extract_document_bytes,
)
from ._vendor.read_tracking import (
    _bump_consecutive,
    _cap_read_tracker_data,
    _dedup_stub_or_block,
    _file_metadata,
)
from ._vendor.search_regex import SearchRegexError, compile_search
from ._vendor.spill_safety import write_text_exclusive
from ._vendor.terminal_exit import _interpret_exit_code
from ._vendor.terminal_hints import annotate_failure, annotate_masked_success
from ._vendor.terminal_session import (
    _cwd_marker,
    _snapshot_bootstrap_script,
    _split_cwd_marker,
    _wrap_command_script,
)
from ._vendor.todo import TODO_SCHEMA, TodoStore, todo_tool
from ._vendor.tool_output_truncate import truncate_head_tail
from ._vendor.write_binary_guard import _check_binary_document_write

DEFAULT_TOOLS = (
    "terminal",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "todo_list",
    "skills_list",
    "skill_view",
)

_SCHEMAS = json.loads(
    (Path(__file__).parent / "_vendor/schemas.json").read_text(encoding="utf-8")
)
_V4A_PARAMS = _SCHEMAS.pop("patch_v4a_parameters")
_V4A_DESCRIPTION = _SCHEMAS.pop("patch_v4a_description")
_SCHEMAS["todo_list"] = TODO_SCHEMA
_SCHEMAS["session_search"] = {
    "name": "session_search",
    "description": (
        "Recover original messages archived by context compression in this session. "
        "Search with query, or omit it to inspect recent archived messages. "
        "This searches the current run or its explicitly resumed session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "session_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    },
}
_SCHEMAS["terminal"] = {
    "name": "terminal",
    "description": (
        "Execute a shell command in the local task environment. Exported environment "
        "variables and the working directory persist across foreground calls. "
        "Output is bounded with the Hermes head/tail truncation rule. "
        "This headless runtime supports foreground commands only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum seconds; default 180, foreground maximum 600.",
            },
            "workdir": {
                "type": "string",
                "description": "Absolute working directory for this command only.",
            },
        },
        "required": ["command"],
    },
}
# Retain upstream parameter names; avoid promising optional document/vision,
# provider-managed ripgrep or LSP integrations that this local runtime omits.
_SCHEMAS["read_file"]["description"] = (
    "Read a text file with line numbers and pagination. Output format: "
    "'LINE_NUM|CONTENT'. Suggests similar filenames if not found. Use offset and "
    "limit for large files. Reads exceeding 100K characters are truncated on a "
    "line boundary and return next_offset. Binary files are not displayed."
)
_SCHEMAS["search_files"]["description"] = (
    "Search file contents with a regular expression, or find files by glob name. "
    "Use target='content' for line matches, file paths, or counts; target='files' "
    "for file discovery. Supports pagination, file_glob and context lines."
)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _error(message: Any, **extra: Any) -> str:
    return _json({"error": str(message), **extra})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _syntax(path: str, content: str) -> LintResult:
    """In-process syntax tier from file_operations_lint; no managed Node/LSP."""
    ext = Path(path).suffix.lower()
    linter = {
        ".py": _lint_python_inproc,
        ".json": _lint_json_inproc,
        ".toml": _lint_toml_inproc,
        ".yaml": _lint_yaml_inproc,
        ".yml": _lint_yaml_inproc,
    }.get(ext)
    if linter is None:
        return LintResult(skipped=True, message=f"No linter for {ext} files")
    success, error = linter(content)
    if error == "__SKIP__":
        return LintResult(
            skipped=True, message=f"No linter available for {ext} (missing dependency)"
        )
    return LintResult(success=success, output="" if success else error)


def _lint_delta(path: str, before: str | None, after: str) -> LintResult:
    post = _syntax(path, after)
    if post.success or post.skipped or before is None:
        return post
    pre = _syntax(path, before)
    if pre.success or pre.skipped or not pre.output:
        return post
    previous = {line.strip() for line in pre.output.splitlines() if line.strip()}
    added = [
        line
        for line in post.output.splitlines()
        if line.strip() and line.strip() not in previous
    ]
    if not added:
        return LintResult(
            success=False,
            output=post.output,
            message="Pre-existing lint errors — this edit didn't introduce new ones but the file is still broken.",
        )
    return LintResult(
        success=False,
        output="New lint errors introduced by this edit (pre-existing errors filtered out):\n"
        + "\n".join(added),
    )


class _LocalFiles(NativeReadCore):
    def __init__(self, owner: HermesTools):
        self.owner = owner

    @property
    def cwd(self) -> str:
        return str(self.owner.cwd)

    def _expand_path(self, path: str) -> str:
        value = Path(path).expanduser()
        return str((value if value.is_absolute() else self.owner.cwd / value).resolve())

    def _escape_shell_arg(self, value: str) -> str:
        return shlex.quote(value)

    def _exec(self, command: str, **kwargs: Any) -> ExecuteResult:
        result = self.owner._run_shell(
            command, cwd=self.owner.cwd, timeout=kwargs.get("timeout", 30)
        )
        return ExecuteResult(result["output"], result["returncode"])

    def _python_interpreter_cmd(self) -> str:
        return shlex.quote(sys.executable)

    def _read_file_sequential(self, path: str, offset: int, limit: int):
        # Original native reader reaches here only for an OS/transport failure.
        from ._vendor.file_operations_common import ReadResult

        return ReadResult(error=f"Failed to read file: {path}")

    def read_file(self, path: str, offset: Any = 1, limit: Any = 2000):
        offset, limit = normalize_read_pagination(offset, limit)
        return self._read_file_native(self._expand_path(path), offset, limit)

    def read_file_raw(self, path: str) -> ReadResult:
        path = self._expand_path(path)
        target = Path(path)
        if not target.exists():
            return self._suggest_similar_files(path)
        if not target.is_file():
            return self._not_regular_error(path)
        data = target.read_bytes()
        if self._is_image(path):
            return ReadResult(is_image=True, is_binary=True, file_size=len(data))
        if has_binary_extension(path) or self._is_likely_binary_bytes(data[:1000]):
            return ReadResult(
                is_binary=True,
                file_size=len(data),
                error=describe_binary_file(data[:1000], len(data)),
            )
        content, _ = _strip_bom(data.decode("utf-8", "surrogateescape"))
        return ReadResult(
            content=content,
            file_size=len(data),
            _content_sha256=hashlib.sha256(data).hexdigest(),
        )

    def delete_file(self, path: str) -> WriteResult:
        target = Path(path)
        if not target.is_absolute():
            target = self.owner.cwd / target
        try:
            target.unlink(missing_ok=True)
            return WriteResult()
        except OSError as exc:
            return WriteResult(error=f"Failed to delete {target}: {exc}")

    def move_file(self, src: str, dst: str) -> WriteResult:
        source, destination = Path(src), Path(dst)
        if not source.is_absolute():
            source = self.owner.cwd / source
        if not destination.is_absolute():
            destination = self.owner.cwd / destination
        try:
            source.rename(destination)
            return WriteResult()
        except OSError as exc:
            return WriteResult(error=f"Failed to move {source} -> {destination}: {exc}")

    def patch_v4a(self, patch: str) -> PatchResult:
        operations, error = parse_v4a_patch(patch)
        if error:
            return PatchResult(error=f"Failed to parse patch: {error}")
        return apply_v4a_operations(operations, self)

    def write_file(
        self, path: str, content: str, pre_content: str | None = None
    ) -> WriteResult:
        path = self._expand_path(path)
        target = Path(path)
        if has_opaque_document_extension(path):
            return WriteResult(error=f"Cannot write text into binary document: {path}")
        if target.exists() and not target.is_file():
            return WriteResult(error=f"Cannot write '{path}': not a regular file")
        bad = re.search(r"[\ud800-\udc7f\udd00-\udfff]", content)
        if bad:
            return WriteResult(
                error=f"Refusing to write '{path}': content contains a lone surrogate character "
                f"({bad.group(0)!r}) that cannot be encoded as UTF-8. The file was NOT created or modified."
            )
        ext = target.suffix.lower()
        checked = _syntax(path, content)
        if ext in {".json", ".yaml", ".yml", ".toml"} and not checked.success:
            return WriteResult(
                error=f"Refusing to write '{path}': candidate content fails {ext} syntax validation "
                f"({checked.output}). The file was NOT created or modified. Fix the content and retry."
            )
        previous = (
            target.read_bytes().decode("utf-8", "surrogateescape")
            if target.is_file()
            else None
        )
        if ext == ".json":
            constants: list[str] = []
            json.loads(content, parse_constant=lambda value: constants.append(value))
            if constants:
                old_constants: list[str] = []
                if previous:
                    try:
                        json.loads(
                            _strip_bom(previous)[0],
                            parse_constant=lambda value: old_constants.append(value),
                        )
                    except (ValueError, RecursionError):
                        pass
                if not old_constants:
                    return WriteResult(
                        error=f"Refusing to write '{path}': candidate content uses {constants[0]}, "
                        "which is not valid JSON. The file was NOT created or modified. "
                        "Use null or a string instead and retry."
                    )
        if _detect_line_ending(previous or "") == "\r\n":
            content = _normalize_line_endings(content, "\r\n")
        if _has_bom(previous) and not _has_bom(content):
            content = "\ufeff" + content
        data = content.encode("utf-8", "surrogateescape")
        target.parent.mkdir(parents=True, exist_ok=True)
        error = file_operations_native.atomic_write(path, data)
        if error:
            return WriteResult(error=f"Failed to write file: {error}")
        if target.read_bytes() != data:
            return WriteResult(error=f"Post-write verification failed for {path}")
        return WriteResult(
            bytes_written=len(data),
            dirs_created=bool(os.path.dirname(path)),
            verified=True,
            _content_sha256=hashlib.sha256(data).hexdigest(),
            lint=_lint_delta(path, previous, content).to_dict(),
        )

    def patch_replace(
        self, path: str, old: str, new: str, replace_all: bool = False
    ) -> PatchResult:
        path = self._expand_path(path)
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return PatchResult(error=f"Failed to read file: {path}")
        content, _ = _strip_bom(raw.decode("utf-8", "surrogateescape"))
        notes: list[str] = []
        changed, count, strategy, error = fuzzy_find_and_replace(
            content, old, new, replace_all, correction_notes=notes
        )
        if error or count == 0:
            return self._no_match_result(path, content, old, new, count, error)
        ending = _detect_line_ending(content)
        if ending:
            changed = _normalize_line_endings(changed, ending)
        written = self.write_file(path, changed)
        if written.error:
            return PatchResult(error=f"Failed to write changes: {written.error}")
        return PatchResult(
            success=True,
            diff=self._unified_diff(content, changed, path),
            files_modified=[path],
            lint=written.lint,
            note="\n".join(note for note in (*notes, boundary_note([strategy])) if note)
            or None,
            _writes=[(path, hashlib.sha256(raw).hexdigest(), written._content_sha256)],
        )


class HermesTools:
    """One invocation's tools and state, independently loadable from a Snapshot."""

    def __init__(
        self,
        cwd: Path,
        snapshot_root: Path,
        enabled_tools: list[str] | None = None,
    ):
        self.cwd = Path(cwd).resolve()
        self.snapshot_root = Path(snapshot_root).resolve()
        selected = list(DEFAULT_TOOLS if enabled_tools is None else enabled_tools)
        unknown = set(selected) - set(_SCHEMAS)
        if unknown:
            raise ValueError("Unsupported Hermes tools: " + ", ".join(sorted(unknown)))
        self.schemas = [
            {"type": "function", "function": copy.deepcopy(_SCHEMAS[name])}
            for name in dict.fromkeys(selected)
        ]
        self.enabled = set(selected)
        self.files = _LocalFiles(self)
        self.todos = TodoStore()
        self._baselines: dict[str, str] = {}
        self._coverage: dict[str, tuple[str, set[int]]] = {}
        self._blind_patches: set[str] = set()
        self._read_state: dict[str, Any] = {
            "last_key": None,
            "consecutive": 0,
            "dedup": {},
            "dedup_hits": {},
            "dedup_generation_reads": set(),
        }
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._active_condition = threading.Condition()
        self._active_calls = 0
        self._process_lock = threading.Lock()
        self._processes: set[subprocess.Popen] = set()
        self._closed = False
        self._temporary = tempfile.TemporaryDirectory(prefix="flashrsi-hermes-shell-")
        self.scratch_dir = Path(self._temporary.name) / "scratch"
        self.scratch_dir.mkdir(mode=0o700)
        self._shell_snapshot = Path(self._temporary.name) / "session.sh"
        self._marker = _cwd_marker(uuid.uuid4().hex)
        self._snapshot_ready = False
        self._output_limits = output_limits.resolve_limits({})
        self._read_max_chars = 100_000
        self._history_search = None
        self._output_dir = Path(self._temporary.name) / "terminal-output"
        self._role_secrets: list[str] = []

    def enable_history_search(self, callback) -> None:
        self._history_search = callback
        if "session_search" not in self.enabled:
            self.enabled.add("session_search")
            self.schemas.append(
                {
                    "type": "function",
                    "function": copy.deepcopy(_SCHEMAS["session_search"]),
                }
            )

    def configure_settings(self, settings: dict) -> None:
        configured_scratch = settings.get("scratch_dir")
        if not configured_scratch and settings.get("session_file"):
            state_path = Path(settings["session_file"]).expanduser().resolve()
            configured_scratch = (
                state_path.parent / (state_path.name + ".artifacts") / "scratch"
            )
        self.scratch_dir = (
            Path(configured_scratch).expanduser()
            if configured_scratch
            else Path(self._temporary.name) / "scratch"
        )
        if not self.scratch_dir.is_absolute():
            self.scratch_dir = self.cwd / self.scratch_dir
        self.scratch_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._output_limits = output_limits.resolve_limits(settings)
        value = settings.get("file_read_max_chars")
        self._read_max_chars = (
            int(value) if isinstance(value, (int, float)) and value > 0 else 100_000
        )
        if settings.get("session_file"):
            state_path = Path(settings["session_file"]).expanduser().resolve()
            self._output_dir = state_path.parent / (state_path.name + ".artifacts")

        def collect(value):
            if isinstance(value, dict):
                for name, item in value.items():
                    if (
                        name
                        in {
                            "api_key",
                            "access_token",
                            "refresh_token",
                            "password",
                            "secret",
                        }
                        and isinstance(item, str)
                        and item
                    ):
                        self._role_secrets.append(item)
                    else:
                        collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        collect(settings)

    def configure_model(self, model: str, provider: str = "") -> None:
        """Apply upstream's model-family gate to the advertised V4A layer.

        Both patch modes remain executable for replay compatibility, as in
        Hermes; only OpenAI-family mains receive the extra schema fields.
        """
        model, provider = (
            str(model or "").strip().lower(),
            str(provider or "").strip().lower(),
        )
        slug = model.split("/", 1)[-1]
        show_v4a = (
            provider
            in {"openai", "openai-chat", "openai-codex", "azure-openai", "codex"}
            or slug.startswith(
                ("gpt-", "gpt.", "chatgpt", "codex", "o1", "o3", "o4", "o5")
            )
            or "openai/" in model
        )
        for item in self.schemas:
            if item["function"]["name"] != "patch":
                continue
            schema = copy.deepcopy(_SCHEMAS["patch"])
            if show_v4a:
                schema["description"] = _V4A_DESCRIPTION
                schema["parameters"]["properties"] = {
                    "mode": copy.deepcopy(_V4A_PARAMS["mode"]),
                    **schema["parameters"]["properties"],
                    "patch": copy.deepcopy(_V4A_PARAMS["patch"]),
                }
                schema["parameters"]["required"] = ["mode"]
            item["function"] = schema

    def _shell_kwargs(self, cwd: Path) -> dict[str, Any]:
        return {
            "quoted_cwd": shlex.quote(str(cwd)),
            "quoted_snap": shlex.quote(str(self._shell_snapshot)),
            "snap_tmp_template": shlex.quote(
                str(self._shell_snapshot) + ".tmp.XXXXXXXXXX"
            ),
            "cwd_marker": self._marker,
        }

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def _run_shell(
        self, command: str, *, cwd: Path, timeout: float, bounded_capture=False
    ) -> dict[str, Any]:
        shell = shutil.which("bash")
        if not shell:
            raise ValueError("Hermes terminal requires bash")
        if self._closed:
            raise RuntimeError("Hermes tools are closed")
        process = subprocess.Popen(
            [shell, "-c", command],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name == "posix",
            env={
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key not in {"BASH_ENV", "ENV"}
                },
                "TMPDIR": str(self.scratch_dir),
                "TMP": str(self.scratch_dir),
                "TEMP": str(self.scratch_dir),
            },
        )
        with self._process_lock:
            self._processes.add(process)
            if self._closed:
                self._kill(process)
        try:
            if bounded_capture:
                collector = _BoundedOutputCollector(
                    self._output_limits["max_bytes"],
                    spill_path=self._output_dir / ("out-" + uuid.uuid4().hex + ".log"),
                )

                def drain():
                    try:
                        while chunk := process.stdout.read(8192):
                            collector.append(chunk)
                    finally:
                        process.stdout.close()

                reader = threading.Thread(target=drain, daemon=True)
                started = time.monotonic()
                reader.start()
                timed_out = False
                try:
                    reader.join(timeout)
                    if reader.is_alive():
                        raise subprocess.TimeoutExpired(command, timeout)
                    process.wait(timeout=max(0, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill(process)
                    process.wait()
                    reader.join()
                suffix = (
                    f"\n[Command timed out after {timeout:g}s]" if timed_out else ""
                )
                data = {
                    "output": collector.render(suffix=suffix),
                    "returncode": 124 if timed_out else process.returncode,
                }
                spill = collector.close_spill()
                if spill:
                    data.update(
                        full_output_path=spill, output_total_chars=collector.total_chars
                    )
                return data
            output, _ = process.communicate(timeout=timeout)
            return {"output": output, "returncode": process.returncode}
        except subprocess.TimeoutExpired:
            self._kill(process)
            output, _ = process.communicate()
            return {"output": output, "returncode": 124, "timed_out": True}
        finally:
            with self._process_lock:
                self._processes.discard(process)

    def execute(self, name: str, args: dict[str, Any]) -> str:
        with self._active_condition:
            if self._closed:
                return _error("Hermes tools are closed")
            self._active_calls += 1
        limit_token = output_limits._limits.set(self._output_limits)
        try:
            return self._execute(name, args)
        except Exception as exc:
            return _error(exc)
        finally:
            output_limits._limits.reset(limit_token)
            with self._active_condition:
                self._active_calls -= 1
                self._active_condition.notify_all()

    def _execute(self, name: str, args: dict[str, Any]) -> str:
        if name not in self.enabled:
            return _error(f"Unknown or disabled tool: {name}")
        if not isinstance(args, dict):
            return _error("Tool arguments must be a JSON object")
        if name == "session_search":
            if self._history_search is None:
                return _error("No compression archive has been bound to this session")
            return _json(self._history_search(**args))
        if name not in {"read_file", "search_files"}:
            with self._lock:
                self._read_state["last_key"] = None
                self._read_state["consecutive"] = 0
                self._read_state["dedup_hits"].clear()
        if name == "terminal":
            with self._state_lock:
                if self._closed:
                    return _error("Hermes tools are closed")
                return self._terminal(args)
        if name == "read_file":
            return self._read(args)
        if name == "write_file":
            return self._write(args)
        if name == "patch":
            return self._patch(args)
        if name == "search_files":
            return self._search(args)
        if name == "todo_list":
            with self._state_lock:
                return todo_tool(
                    todos=args.get("todos"),
                    merge=args.get("merge", False),
                    store=self.todos,
                )
        from .resources import skill_view, skills_list

        if name == "skills_list":
            return skills_list(self.snapshot_root, category=args.get("category"))
        return skill_view(
            self.snapshot_root,
            args.get("name"),
            file_path=args.get("file_path"),
        )

    def _path(self, args: dict[str, Any]) -> str:
        path = args.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("path required")
        return self.files._expand_path(path)

    def _read(self, args: dict[str, Any]) -> str:
        path = self._path(args)
        offset, limit = normalize_read_pagination(
            args.get("offset", 1), args.get("limit", 2000)
        )
        if Path(path).suffix.lower() in EXTRACTABLE_EXTENSIONS:
            extracted = self._read_document(path, args["path"], offset, limit)
            if extracted is not None:
                return extracted
        if has_binary_extension(path):
            return _error(
                f"Cannot read binary file '{args['path']}' ({Path(path).suffix.lower()}). "
                "Use vision_analyze for images, or terminal to inspect binary files."
            )
        key = (path, offset, limit)
        version_before = _file_metadata(path)
        with self._lock:
            state = self._read_state
            if (
                version_before is not None
                and state["dedup"].get(key) == version_before
                and key in state["dedup_generation_reads"]
            ):
                return _dedup_stub_or_block(state, key, args["path"])
        result = self.files.read_file(path, offset, limit)
        data = result.to_dict()
        if result.is_image:
            data["hint"] = (
                "Image file detected. This runtime supports text files only; "
                "use an image-capable tool to inspect its contents."
            )
        with self._lock:
            self._remember_read(path, offset, limit, result, data)
            if not result.error and not result.is_binary:
                count = _bump_consecutive(state, ("read", args["path"], offset, limit))
                state["dedup_hits"].pop(key, None)
                state["dedup_generation_reads"].add(key)
                if (
                    version_before is not None
                    and _file_metadata(path) == version_before
                    and count < 4
                ):
                    state["dedup"][key] = version_before
                else:
                    state["dedup"].pop(key, None)
                    state["dedup_generation_reads"].discard(key)
                _cap_read_tracker_data(state)
                if count >= 4:
                    self._baselines.pop(path, None)
                    return _error(
                        f"BLOCKED: You have read this exact file region {count} times in a row. "
                        "The content has NOT changed. You already have this information. "
                        "STOP re-reading and proceed with your task.",
                        path=args["path"],
                        already_read=count,
                        guardrail_refusal=True,
                    )
                if count >= 3:
                    data["_warning"] = (
                        f"You have read this exact file region {count} times consecutively. "
                        "The content has not changed since your last read. Use the information you already have. "
                        "If you are stuck in a loop, stop reading and proceed with writing or responding."
                    )
        return _json(data)

    def _read_document(
        self, path: str, display_path: str, offset: int, limit: int
    ) -> str | None:
        try:
            raw = Path(path).read_bytes()
            extracted = extract_document_bytes(raw, path)
        except (ExtractionError, OSError, ValueError) as exc:
            if Path(path).suffix.lower() != ".ipynb" and isinstance(
                exc, ExtractionError
            ):
                return _error(
                    f"Cannot read '{display_path}' ({Path(path).suffix.lower()}): document "
                    f"extraction failed — {exc}. Use terminal utilities to inspect or convert the file."
                )
            return None
        lines = extracted.splitlines()
        end_line = offset + limit - 1
        page_text = "\n".join(lines[offset - 1 : end_line])
        truncated_lines = any(
            len(line) > self._output_limits["max_line_length"]
            for line in page_text.split("\n")
        )
        data = {
            "content": self.files._add_line_numbers(page_text, offset)
            if page_text
            else "",
            "total_lines": len(lines),
            "file_size": len(raw),
            "truncated": len(lines) > end_line,
            "extracted_document": True,
        }
        if data["truncated"]:
            data["hint"] = (
                f"Use offset={end_line + 1} to continue reading (showing {offset}-{min(end_line, len(lines))} of {len(lines)} lines)"
            )
        if len(data["content"]) > self._read_max_chars:
            _apply_char_budget(
                data, data["content"], offset, len(lines), self._read_max_chars
            )
        if (
            offset == 1
            and not data["truncated"]
            and not truncated_lines
            and not data.get("truncated_lines")
        ):
            with self._lock:
                self._baselines[path] = hashlib.sha256(raw).hexdigest()
        return _json(data)

    def reset_read_dedup(self) -> None:
        """A compressed conversation must recover one full read per file region."""
        with self._lock:
            self._read_state["dedup_generation_reads"].clear()
            self._read_state["dedup_hits"].clear()

    def _invalidate_read(self, path: str) -> None:
        for key in tuple(self._read_state["dedup"]):
            if key[0] == path:
                self._read_state["dedup"].pop(key, None)

    def _remember_read(self, path, offset, limit, result, data) -> None:
        if not result.error and not result.is_binary and Path(path).is_file():
            digest = (
                result._snapshot[-1].hex()
                if result._snapshot is not None
                else _sha(Path(path))
            )
            previous, coverage = self._coverage.get(path, (digest, set()))
            if previous != digest:
                coverage = set()
            if not result.truncated_lines:
                coverage.update(
                    range(offset, min(offset + limit, result.total_lines + 1))
                )
            self._coverage[path] = (digest, coverage)
            if not result.truncated_lines and len(coverage) >= result.total_lines:
                self._baselines[path] = digest
            if len(result.content) > self._read_max_chars:
                _apply_char_budget(
                    data,
                    result.content,
                    offset,
                    result.total_lines,
                    self._read_max_chars,
                )
                next_offset = data["next_offset"]
                self._baselines.pop(path, None)
                # The read covered only the displayed prefix. Counting hidden
                # lines would incorrectly authorize a later full-file write.
                coverage.difference_update(range(next_offset, offset + limit))
                if data.get("truncated_lines"):
                    coverage.discard(offset)

    def _write(self, args: dict[str, Any]) -> str:
        path = self._path(args)
        if error := _check_binary_document_write(args["path"], str(self.cwd)):
            return _error(error)
        content = args.get("content")
        if not isinstance(content, str):
            return _error("content required")
        target = Path(path)
        reason = None
        with self._lock:
            baseline = self._baselines.get(path)
            blind_patch = path in self._blind_patches
        if target.is_file():
            if baseline is not None and baseline != _sha(target):
                reason = f"{path} was modified since you last read it on disk (external edit or unrecorded writer). Re-read the file before writing."
            elif baseline is None:
                reason = (
                    "Your patch changed this file without a full view of its current content. Read the current file in full before a whole-file overwrite, or continue with targeted patches."
                    if blind_patch
                    else f"{path} exists but this task has not seen its full current content "
                    "(never read, patched without a prior full read, or only a redacted/partial view). "
                    "Read the file — every page of it, if it needs offset/limit — or use patch for a "
                    "targeted edit; a stale conversation copy must not overwrite the current disk content."
                )
        if reason:
            return _error(
                f"Refusing to overwrite {args['path']}: {reason} "
                "The file was NOT modified. Reload the current contents with read_file "
                "(every page, for a file that needs offset/limit), merge the requested "
                "change, then call write_file again. For small edits, prefer patch so "
                "existing unrelated changes are preserved.",
                stale_write_blocked=True,
                path=args["path"],
                resolved_path=path,
            )
        nonempty = [line for line in content.splitlines() if line.strip()]
        numbered = [
            int(line.lstrip().partition("|")[0])
            for line in nonempty
            if line.lstrip().partition("|")[0].isdigit() and "|" in line
        ]
        if (
            len(numbered) >= 2
            and len(numbered) / len(nonempty) >= 0.6
            and all(
                current == previous + 1
                for previous, current in zip(numbered, numbered[1:])
            )
        ):
            return _error(
                "Refusing to write internal read_file display text as file content. "
                "Strip read_file line-number prefixes or reconstruct the intended file contents before writing."
            )
        result = self.files.write_file(path, content)
        data = result.to_dict()
        data["resolved_path"] = path
        if not result.error:
            data["files_modified"] = [path]
            digest = result._content_sha256
            with self._lock:
                self._invalidate_read(path)
                self._baselines[path] = digest
                self._blind_patches.discard(path)
        return _json(data)

    def _patch(self, args: dict[str, Any]) -> str:
        mode = args.get("mode", "replace")
        if mode == "patch":
            return self._patch_v4a(args)
        if mode != "replace":
            return _error(f"Unknown mode: {mode}")
        path = self._path(args)
        if error := _check_binary_document_write(args["path"], str(self.cwd)):
            return _error(error)
        old, new = args.get("old_string"), args.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return _error("old_string and new_string required")
        with self._lock:
            baseline = self._baselines.get(path)
        known = bool(baseline and Path(path).is_file() and baseline == _sha(Path(path)))
        result = self.files.patch_replace(
            path, old, new, args.get("replace_all", False)
        )
        data = result.to_dict()
        if not result.error:
            data["files_modified"] = [path]
            data["resolved_path"] = path
            digest = _sha(Path(path))
            with self._lock:
                self._invalidate_read(path)
                if known:
                    self._baselines[path] = digest
                else:
                    self._blind_patches.add(path)
        elif (
            "Could not find" in result.error
            and "Did you mean one of these sections?" not in result.error
        ):
            data["_hint"] = (
                "old_string not found. Use read_file to verify the current content, or search_files to locate the text."
            )
        return _json(data)

    def _patch_v4a(self, args: dict[str, Any]) -> str:
        patch = args.get("patch")
        if not isinstance(patch, str) or not patch:
            return _error("patch content required")
        collected = _collect_v4a_header_paths(patch)
        if isinstance(collected, str):
            return collected
        paths, content_paths, entries = collected
        for raw in content_paths:
            if error := _check_binary_document_write(raw, str(self.cwd)):
                return _error(error)
        resolved = {raw: self.files._expand_path(raw) for raw in paths}
        entry_paths = {}
        for raw in entries:
            entry = Path(raw)
            if not entry.is_absolute():
                entry = self.cwd / entry
            entry_paths[raw] = str(entry.parent.resolve() / entry.name)
        with self._lock:
            known = {path: self._baselines.get(path) for path in resolved.values()}
        result = self.files.patch_v4a(
            _rewrite_v4a_patch_paths_for_host(patch, resolved, entry_paths, self.files)
        )
        data = result.to_dict()
        if not result.error:
            modified = [entry_paths.get(raw) or resolved[raw] for raw in paths]
            data["files_modified"] = modified
            if len(modified) == 1:
                data["resolved_path"] = modified[0]
            with self._lock:
                for path in modified:
                    self._invalidate_read(path)
                    if not Path(path).is_file():
                        self._baselines.pop(path, None)
                for path, read_sha, written_sha in result._writes:
                    if written_sha is None:
                        continue
                    vouched = read_sha == "" or (
                        read_sha is not None and read_sha == known.get(path)
                    )
                    known[path] = written_sha if vouched else None
                    if (
                        vouched
                        and Path(path).is_file()
                        and _sha(Path(path)) == written_sha
                    ):
                        self._baselines[path] = written_sha
                        self._blind_patches.discard(path)
                    else:
                        self._baselines.pop(path, None)
                        self._blind_patches.add(path)
        return _json(data)

    def _search(self, args: dict[str, Any]) -> str:
        pattern = args.get("pattern")
        if not isinstance(pattern, str):
            return _error("pattern required")
        target = {"grep": "content", "find": "files"}.get(
            args.get("target"), args.get("target", "content")
        )
        if target not in {"content", "files"}:
            return _error(f"Unknown search target: {target}")
        raw_path = args.get("path") or "."
        if isinstance(raw_path, str) and not raw_path.strip():
            raw_path = "."
        root = Path(self.files._expand_path(raw_path))
        if not root.exists():
            return _json(SearchResult(error=f"Path not found: {root}").to_dict())
        offset, limit = normalize_search_pagination(
            args.get("offset", 0), args.get("limit", 50)
        )
        order = args.get("order", "discovery")
        if target == "files" and order not in {"discovery", "modified"}:
            return _json(
                SearchResult(
                    error=f"Invalid file search order {order!r}; expected 'discovery' or 'modified'."
                ).to_dict()
            )
        search_key = (
            "search",
            pattern,
            target,
            str(raw_path),
            args.get("file_glob") or "",
            limit,
            offset,
            order,
        )
        with self._lock:
            count = _bump_consecutive(self._read_state, search_key)
        if count >= 4:
            return _error(
                f"BLOCKED: You have run this exact search {count} times in a row. "
                "The results have NOT changed. You already have this information. "
                "STOP re-searching and proceed with your task.",
                pattern=pattern,
                already_searched=count,
                guardrail_refusal=True,
            )

        def displayed(path: Path) -> str:
            if Path(raw_path).is_absolute() or str(raw_path).startswith("~"):
                return str(path)
            if root.is_file():
                return str(raw_path)
            return os.path.join(str(raw_path), str(path.relative_to(root)))

        file_glob = args.get("file_glob")
        files = (
            [root]
            if root.is_file()
            else list(
                self._search_walk(
                    root, include_hidden=target == "files" or bool(file_glob)
                )
            )
        )
        if target == "files":
            search_pattern = pattern.rsplit("/", 1)[-1]
            if not search_pattern.startswith("*"):
                search_pattern = "*" + search_pattern
            matches = [
                path for path in files if matches_glob(path.name, search_pattern)
            ]
            if order == "modified":
                matches.sort(key=lambda path: (-path.stat().st_mtime, str(path)))
            result = SearchResult(
                files=[displayed(path) for path in matches[offset : offset + limit]],
                total_count=min(len(matches), offset + limit + 1),
                truncated=len(matches) > offset + limit,
            )
        else:
            try:
                regex = compile_search(pattern, multiline=True)
            except SearchRegexError as exc:
                return _json(SearchResult(error=f"Search failed: {exc}").to_dict())
            multiline = "\n" in pattern or bool(
                re.search(r"(?<!\\)(?:\\\\)*\\n", pattern)
            )
            warning = (
                "Pattern contains \\n — multiline mode (-U) was enabled automatically so the regex can match across line boundaries."
                if multiline
                else None
            )
            found: list[SearchMatch] = []
            counts: dict[str, int] = {}
            context = max(0, int(args.get("context", 0)))
            for path in files:
                relative = (
                    path.name if root.is_file() else path.relative_to(root).as_posix()
                )
                if file_glob and not matches_glob(
                    relative, file_glob, basename="/" not in file_glob
                ):
                    continue
                try:
                    raw = path.read_bytes()
                    if b"\x00" in raw:
                        continue
                    content = raw.decode("utf-8", errors="replace")
                except OSError:
                    continue
                lines = content.splitlines()
                if multiline:
                    hits = sorted(
                        {
                            index
                            for match in regex.finditer(content)
                            for index in range(
                                content.count("\n", 0, match.start()),
                                content.count(
                                    "\n", 0, max(match.start(), match.end() - 1)
                                )
                                + 1,
                            )
                        }
                    )
                else:
                    hits = [i for i, line in enumerate(lines) if regex.search(line)]
                if not hits:
                    continue
                counts[displayed(path)] = len(hits)
                selected = sorted(
                    {
                        j
                        for i in hits
                        for j in range(
                            max(0, i - context), min(len(lines), i + context + 1)
                        )
                    }
                )
                found.extend(
                    SearchMatch(displayed(path), i + 1, lines[i][:500])
                    for i in selected
                )
            mode = args.get("output_mode", "content")
            if mode == "content":
                found = found[: offset + limit + (200 if context > 0 else 0)]
                result = SearchResult(
                    matches=found[offset : offset + limit],
                    total_count=len(found),
                    truncated=len(found) > offset + limit,
                )
            elif mode == "files_only":
                keys = list(counts)[: offset + limit]
                result = SearchResult(
                    files=keys[offset : offset + limit],
                    total_count=len(keys),
                )
            elif mode == "count":
                keys = list(counts)[: offset + limit]
                selected_counts = {key: counts[key] for key in keys}
                result = SearchResult(
                    counts=selected_counts,
                    total_count=sum(selected_counts.values()),
                )
            else:
                return _error(f"Unknown output mode: {mode}")
            if warning:
                result.warning = warning
            elif not result.total_count:
                result.warning = self._zero_match_hint(
                    root, pattern, file_glob, displayed
                )
        data = result.to_dict(densify=True)
        if count >= 3:
            data["_warning"] = (
                f"You have run this exact search {count} times consecutively. The results have not changed. Use the information you already have."
            )
        if result.truncated:
            data["_hint"] = (
                f"Results truncated. Use offset={offset + limit} to see more, or narrow with a more specific pattern or file_glob."
            )
        return _json(data)

    def _search_walk(self, root: Path, *, include_hidden: bool = False):
        repository = next(
            (parent for parent in (root, *root.parents) if (parent / ".git").exists()),
            None,
        )
        matcher = IgnoreRules(
            repository or root,
            names=(".gitignore", ".ignore") if repository else (".ignore",),
            boundary=root,
        )
        yield from walk_lifo(
            root, matcher, include_hidden=include_hidden, include_ignored=include_hidden
        )

    def _zero_match_hint(self, root, pattern, file_glob, displayed):
        probes = [
            (
                compile_search(pattern, ignore_case=True, multiline=True),
                False,
                "0 exact matches, but {total} case-insensitive match(es) in {n} file(s): {paths} — the pattern's casing may be wrong.",
            ),
            (
                compile_search(pattern, multiline=True),
                True,
                "0 matches in visible files, but {total} match(es) in {n} hidden or gitignored file(s): {paths} — these are excluded by default.",
            ),
        ]
        if re.search(r"[.\[\](){}?*+^$\\|]", pattern):
            probes.append(
                (
                    compile_search(pattern, literal=True, multiline=True),
                    False,
                    "0 regex matches, but {total} literal match(es) in {n} file(s): {paths} — the pattern contains regex metacharacters that likely need escaping (or pass a simpler substring).",
                )
            )
        for regex, hidden, template in probes:
            candidates = (
                [root]
                if root.is_file()
                else self._search_walk(root, include_hidden=hidden or bool(file_glob))
            )
            counts = []
            for path in candidates:
                relative = (
                    path.name if root.is_file() else path.relative_to(root).as_posix()
                )
                if file_glob and not matches_glob(
                    relative, file_glob, basename="/" not in file_glob
                ):
                    continue
                try:
                    raw = path.read_bytes()
                    if b"\x00" in raw:
                        continue
                    hits = sum(
                        len(list(regex.finditer(line)))
                        for line in raw.decode("utf-8", errors="replace").splitlines()
                    )
                except OSError:
                    continue
                if hits:
                    counts.append((displayed(path), hits))
                    if len(counts) >= 50:
                        break
            if counts:
                paths = ", ".join(path for path, _ in counts[:5])
                if len(counts) > 5:
                    paths += f" (+{len(counts) - 5} more)"
                return template.format(
                    total=sum(count for _, count in counts), n=len(counts), paths=paths
                )
        return None

    def _terminal(self, args: dict[str, Any]) -> str:
        if "command" not in args and "code" in args:
            return _error(
                "terminal received a 'code' parameter, but it requires a shell command in 'command'. Use execute_code(code=...) for Python; for shell, retry as terminal(command=...)."
            )
        command = args.get("command")
        if not isinstance(command, str):
            return _json(
                {
                    "output": "",
                    "exit_code": -1,
                    "error": f"Invalid command: expected string, got {type(command).__name__}",
                    "status": "error",
                }
            )
        if any(
            args.get(key)
            for key in (
                "background",
                "pty",
                "notify",
                "notify_on_complete",
                "watch_patterns",
                "persist_on_release",
            )
        ):
            return _error(
                "This headless Hermes runtime supports foreground terminal calls only; background, PTY and notifications are unsupported."
            )
        timeout = args.get("timeout")
        if timeout is None:
            timeout = 180
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            return _error(
                f"timeout must be a positive number of seconds (got {timeout})."
            )
        if timeout > 600:
            return _error(
                "Foreground timeout exceeds 600 seconds; tracked background execution is unsupported in this runtime."
            )
        workdir = args.get("workdir")
        cwd = self.cwd
        if workdir:
            if not isinstance(workdir, str):
                return _error("workdir must be a string")
            cwd = Path(workdir)
        if not self._snapshot_ready:
            boot = _snapshot_bootstrap_script(
                excluded_names=(), **self._shell_kwargs(self.cwd)
            )
            initialized = self._run_shell(boot, cwd=self.cwd, timeout=10)
            self._snapshot_ready = initialized["returncode"] == 0
        wrapped = _wrap_command_script(
            command,
            snapshot_ready=self._snapshot_ready,
            persist_env=True,
            passthrough_names=(),
            **self._shell_kwargs(cwd),
        )
        # The wrapper's builtin cd handles cwd overrides. Spawning from the
        # session cwd also preserves the upstream result for a missing workdir.
        result = self._run_shell(
            wrapped, cwd=self.cwd, timeout=float(timeout), bounded_capture=True
        )
        output = result["output"]
        observed = _split_cwd_marker(output, self._marker)
        changed_cwd = None
        if observed:
            observed_cwd, output = observed
            if observed_cwd and Path(observed_cwd).is_dir():
                if Path(observed_cwd).resolve() != cwd:
                    changed_cwd = observed_cwd
                if workdir is None:
                    self.cwd = Path(observed_cwd).resolve()
        data: dict[str, Any] = {
            "output": strip_ansi(
                truncate_head_tail(output, self._output_limits["max_bytes"])
            ).strip(),
            "exit_code": result["returncode"],
            "error": None,
        }
        if result.get("full_output_path"):
            spill = Path(result["full_output_path"])
            try:
                from .upstream_compaction.redact import redact_sensitive_text

                full = strip_ansi(
                    spill.read_text(encoding="utf-8-sig", errors="replace")
                )
                for secret in self._role_secrets:
                    full = full.replace(secret, "[redacted]")
                full = redact_sensitive_text(full, force=True, code_file=True)
                write_text_exclusive(
                    spill, full, private=True, overwrite=True, errors="replace"
                )
                total = result["output_total_chars"]
                data.update(
                    output_total_chars=total,
                    full_output_path=str(spill),
                    truncation_note=(
                        "Output exceeded the capture window (head+tail shown). "
                        f"Full output ({total:,} chars) saved to {spill} — search it with "
                        "search_files or page it with read_file instead of re-running the command."
                    ),
                )
            except Exception:
                spill.unlink(missing_ok=True)
        if changed_cwd:
            data["cwd"] = changed_cwd
        if result.get("timed_out"):
            data["output"] = (
                data["output"] + f"\n[Command timed out after {timeout:g}s]"
            ).strip()
        exit_note = _interpret_exit_code(command, result["returncode"])
        if exit_note:
            data["exit_code_meaning"] = exit_note
        hint = (
            annotate_masked_success(command, data["output"])
            if result["returncode"] == 0
            else annotate_failure(command, result["returncode"], data["output"])
            if not exit_note
            else None
        )
        if hint:
            data["hint"] = hint
        return _json(data)

    def close(self) -> None:
        with self._active_condition:
            self._closed = True
        with self._process_lock:
            processes = tuple(self._processes)
        for process in processes:
            self._kill(process)
        # File calls can run concurrently. Wait for their active references and
        # any killed terminal call before removing invocation-owned state.
        with self._active_condition:
            self._active_condition.wait_for(lambda: self._active_calls == 0)
            self._temporary.cleanup()
