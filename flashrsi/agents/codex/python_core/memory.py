"""Memory read extension from Codex rust-v0.147.0, commit be6e8eac029b.

Sources: ext/memories/src/{extension,prompts,backend,local,tools}.rs and
memories/read/src/citations.rs. The pinned extension reads existing memories
and appends explicit update notes; it does not run a model extraction pipeline.
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

from .history import truncate_text
from .hooks import message
from .shell import ToolError


def _function(name, description, properties, required=()):
    parameters = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = list(required)
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": False,
        "parameters": parameters,
    }


def memory_specs():
    """Responses schemas from the pinned tool argument structs after sanitation."""
    string, integer = {"type": "string"}, {"type": "integer"}
    match_modes = []
    for kind in ("any", "all_on_same_line", "all_within_lines"):
        properties = {"type": {"type": "string", "enum": [kind]}}
        required = ["type"]
        if kind == "all_within_lines":
            properties["line_count"] = integer
            required.insert(0, "line_count")
        match_modes.append(
            {"type": "object", "properties": properties, "required": required}
        )
    tools = [
        _function(
            "add_ad_hoc_note",
            "Create one append-only ad-hoc memory note after the user explicitly asks Codex to remember, forget, or update something.",
            {
                "filename": {
                    "type": "string",
                    "description": "Name of the note file to create, in YYYY-MM-DDTHH-MM-SS-<slug>.md format. The slug must use only lowercase ASCII letters, digits, and hyphens.",
                },
                "note": {
                    "type": "string",
                    "description": "Verbatim Markdown note to append to the ad-hoc memory notes.",
                },
            },
            ("filename", "note"),
        ),
        _function(
            "list",
            "List immediate files and directories under a path in the Codex memories store.",
            {"cursor": string, "max_results": integer, "path": string},
        ),
        _function(
            "read",
            "Read a Codex memory file by relative path, optionally starting at a 1-indexed line offset and limiting the number of lines returned.",
            {"line_offset": integer, "max_lines": integer, "path": string},
            ("path",),
        ),
        _function(
            "search",
            "Search Codex memory files for substring matches, optionally normalizing separators or requiring all query substrings on the same line or within a line window.",
            {
                "case_sensitive": {"type": "boolean"},
                "context_lines": integer,
                "cursor": string,
                "match_mode": {"oneOf": match_modes},
                "max_results": integer,
                "normalized": {"type": "boolean"},
                "path": string,
                "queries": {"type": "array", "items": string},
            },
            ("queries",),
        ),
    ]
    return {
        "type": "namespace",
        "name": "memories",
        "description": "Tools in the memories namespace.",
        "tools": tools,
    }


def memory_output_schemas():
    """Un-sanitized output schemas used by native Code Mode TypeScript definitions."""

    def obj(properties, required=None):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False,
        }

    def array(item):
        return {"type": "array", "items": item}

    string = {"type": "string"}
    nullable_string = {"type": ["string", "null"]}
    integer = {"type": "integer", "format": "uint", "minimum": 0.0}
    boolean = {"type": "boolean"}
    modes = memory_specs()["tools"][-1]["parameters"]["properties"]["match_mode"]
    modes = json.loads(json.dumps(modes))
    modes["oneOf"][-1]["properties"]["line_count"] = {
        "type": "integer",
        "format": "uint",
        "minimum": 1.0,
    }
    return {
        "add_ad_hoc_note": {"type": "object", "additionalProperties": False},
        "list": obj(
            {
                "path": nullable_string,
                "entries": array(
                    obj(
                        {
                            "path": string,
                            "entry_type": {
                                "type": "string",
                                "enum": ["file", "directory"],
                            },
                        }
                    )
                ),
                "next_cursor": nullable_string,
                "truncated": boolean,
            },
            ["entries", "truncated"],
        ),
        "read": obj(
            {
                "path": string,
                "start_line_number": integer,
                "content": string,
                "truncated": boolean,
            }
        ),
        "search": obj(
            {
                "queries": array(string),
                "match_mode": modes,
                "path": nullable_string,
                "matches": array(
                    obj(
                        {
                            "path": string,
                            "match_line_number": integer,
                            "content_start_line_number": integer,
                            "content": string,
                            "matched_queries": array(string),
                        }
                    )
                ),
                "next_cursor": nullable_string,
                "truncated": boolean,
            },
            ["queries", "match_mode", "matches", "truncated"],
        ),
    }


def _invalid_path(path, reason):
    raise ToolError(f"path '{path}' {reason}")


def _metadata(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _cursor(value):
    if value is None:
        return 0
    # Rust usize parsing accepts a leading '+' but no whitespace or minus.
    if not re.fullmatch(r"\+?[0-9]+", value) or int(value) > (1 << 64) - 1:
        raise ToolError(f"cursor '{value}' must be a non-negative integer")
    return int(value)


def _page(items, cursor, max_results):
    start = _cursor(cursor)
    if start > len(items):
        raise ToolError(f"cursor '{start}' exceeds result count")
    end = min(start + max_results, len(items))
    next_cursor = str(end) if end < len(items) else None
    return items[start:end], next_cursor, next_cursor is not None


def _rust_lines(text):
    # str::lines splits only LF/CRLF and suppresses the final empty line.
    lines = text.split("\n")
    terminated = text.endswith("\n")
    if terminated:
        lines.pop()
    return (
        [
            line[:-1]
            if line.endswith("\r") and (terminated or index + 1 < len(lines))
            else line
            for index, line in enumerate(lines)
        ]
        if text
        else []
    )


def _result_limit(args, maximum):
    requested = args.get("max_results")
    return min(maximum, max(1, maximum if requested is None else requested))


class MemoryFatalError(RuntimeError):
    """The native extension makes storage I/O failures fatal to the turn."""


class Memories:
    def __init__(self, home, settings):
        self.home, self.settings = Path(home), settings
        self.root = self.home / "memories"

    @property
    def enabled(self):
        features = self.settings.get("features", {})
        return features.get(
            "memories", features.get("memory_tool", False)
        ) and self.settings.get("memories", {}).get("use_memories", True)

    def context(self):
        if not self.enabled:
            return None
        try:
            summary = (
                (self.root / "memory_summary.md").read_bytes().decode("utf-8").strip()
            )
        except (OSError, UnicodeError):
            return None
        summary = truncate_text(summary, "tokens", 2500)
        if not summary:
            return None
        template = (self.home / "python_core/memory_assets/read_path.md").read_text()
        # Template replacement is one pass: data containing template syntax is literal.
        text = re.sub(
            r"\{\{\s*(base_path|memory_summary)\s*\}\}",
            lambda match: str(self.root) if match[1] == "base_path" else summary,
            template,
        )
        return message(text)

    async def start(self, router):
        if self.enabled and self.settings.get("memories", {}).get(
            "dedicated_tools", False
        ):
            namespace = memory_specs()
            for tool in namespace["tools"]:
                name = tool["name"]

                def handle(arguments, name=name):
                    self._validate(name, arguments)
                    try:
                        result = getattr(self, name)(arguments)
                    except UnicodeError:
                        raise MemoryFatalError(
                            "I/O error while reading memories: stream did not contain valid UTF-8"
                        ) from None
                    except OSError as error:
                        raise MemoryFatalError(
                            f"I/O error while reading memories: {error.strerror} (os error {error.errno})"
                        ) from None
                    # The pinned workspace enables serde_json preserve_order.
                    return result

                router.register(
                    f"memories.{name}", {**namespace, "tools": [tool]}, handle
                )
        context = self.context()
        return [context] if context else []

    def _validate(self, name, arguments):
        spec = next(tool for tool in memory_specs()["tools"] if tool["name"] == name)
        props = spec["parameters"]["properties"]
        order = {
            "add_ad_hoc_note": ["filename", "note"],
            "list": ["path", "cursor", "max_results"],
            "read": ["path", "line_offset", "max_lines"],
            "search": [
                "queries",
                "match_mode",
                "path",
                "cursor",
                "context_lines",
                "case_sensitive",
                "normalized",
                "max_results",
            ],
        }[name]
        for key, value in arguments.items():
            if key not in props:
                expected = ", ".join(f"`{field}`" for field in order)
                raise ToolError(f"unknown field `{key}`, expected one of {expected}")
            if value is None and key not in spec["parameters"].get("required", []):
                continue
            kind = props[key].get("type")
            valid = {
                "string": isinstance(value, str),
                "integer": type(value) is int and 0 <= value <= (1 << 64) - 1,
                "boolean": isinstance(value, bool),
                "array": isinstance(value, list)
                and all(isinstance(item, str) for item in value),
            }
            if kind and not valid[kind]:
                raise ToolError(f"invalid type for `{key}`: expected {kind}")
        for key in spec["parameters"].get("required", []):
            if key not in arguments:
                raise ToolError(f"missing field `{key}`")
        mode = arguments.get("match_mode")
        if mode is not None:
            if not isinstance(mode, dict) or mode.get("type") not in {
                "any",
                "all_on_same_line",
                "all_within_lines",
            }:
                raise ToolError("invalid memory search match_mode")
            if mode["type"] == "all_within_lines" and (
                type(mode.get("line_count")) is not int or mode["line_count"] < 0
            ):
                raise ToolError("invalid memory search line_count")

    def _resolve(self, relative):
        if relative is None:
            return self.root
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts:
            _invalid_path(relative, "must stay within the memories root")
        if any(part.startswith(".") and part != "." for part in parts):
            raise ToolError(f"path '{relative}' was not found")
        path = self.root
        for index, part in enumerate(parts):
            path /= part
            metadata = _metadata(path)
            if metadata is None:
                return path.joinpath(*parts[index + 1 :])
            if stat.S_ISLNK(metadata.st_mode):
                _invalid_path(
                    path.relative_to(self.root).as_posix(), "must not be a symlink"
                )
            if index + 1 < len(parts) and not stat.S_ISDIR(metadata.st_mode):
                _invalid_path(
                    relative, "traverses through a non-directory path component"
                )
        return path

    def _existing(self, relative):
        path = self._resolve(relative)
        metadata = _metadata(path)
        if metadata is None:
            raise ToolError(f"path '{relative or ''}' was not found")
        if stat.S_ISLNK(metadata.st_mode):
            _invalid_path(
                path.relative_to(self.root).as_posix(), "must not be a symlink"
            )
        return path, metadata

    @staticmethod
    def _entries(path):
        try:
            entries = sorted(path.iterdir())
        except FileNotFoundError:
            return []
        return [
            (entry, metadata)
            for entry in entries
            if (metadata := _metadata(entry)) is not None
        ]

    def list(self, args):
        relative = args.get("path")
        path, metadata = self._existing(relative)
        candidates = (
            [(path, metadata)]
            if stat.S_ISREG(metadata.st_mode)
            else self._entries(path)
            if stat.S_ISDIR(metadata.st_mode)
            else []
        )
        entries = []
        for child, info in candidates:
            if child.name.startswith(".") or stat.S_ISLNK(info.st_mode):
                continue
            kind = (
                "directory"
                if stat.S_ISDIR(info.st_mode)
                else "file"
                if stat.S_ISREG(info.st_mode)
                else None
            )
            if kind:
                entries.append(
                    {
                        "path": child.relative_to(self.root).as_posix(),
                        "entry_type": kind,
                    }
                )
        page, cursor, truncated = _page(
            entries,
            args.get("cursor"),
            _result_limit(args, 2000),
        )
        return {
            "path": relative,
            "entries": page,
            "next_cursor": cursor,
            "truncated": truncated,
        }

    def read(self, args, *, max_tokens=20000):
        relative = args["path"]
        offset = args.get("line_offset")
        offset = 1 if offset is None else offset
        maximum = args.get("max_lines")
        if offset == 0:
            raise ToolError("line_offset must be a 1-indexed line number")
        if maximum == 0:
            raise ToolError("max_lines must be a positive integer")
        path, metadata = self._existing(relative)
        if not stat.S_ISREG(metadata.st_mode):
            raise ToolError(f"path '{relative}' is not a file")
        original = path.read_bytes().decode("utf-8")
        start = 0
        for _ in range(offset - 1):
            newline = original.find("\n", start)
            if newline == -1:
                raise ToolError("line_offset exceeds file length")
            start = newline + 1
        end = len(original)
        if maximum is not None:
            position = start
            for _ in range(maximum):
                newline = original.find("\n", position)
                if newline == -1:
                    break
                position = newline + 1
            else:
                end = position
        selected = original[start:end]
        content = truncate_text(selected, "tokens", max_tokens or 20000)
        return {
            "path": relative,
            "start_line_number": offset,
            "content": content,
            "truncated": end < len(original) or content != selected,
        }

    def search(self, args):
        queries = [query.strip() for query in args["queries"]]
        if not queries or any(not query for query in queries):
            raise ToolError("queries must not be empty or contain empty strings")
        requested_mode = args.get("match_mode") or {"type": "any"}
        mode = {"type": requested_mode["type"]}
        if mode["type"] == "all_within_lines":
            mode["line_count"] = requested_mode["line_count"]
        if mode["type"] == "all_within_lines" and mode["line_count"] == 0:
            raise ToolError("all_within_lines.line_count must be a positive integer")
        relative = args.get("path")
        path, metadata = self._existing(relative)
        sensitive = args.get("case_sensitive")
        sensitive = True if sensitive is None else sensitive
        normalized = args.get("normalized") or False

        def prepare(value):
            value = value if sensitive else value.lower()
            return (
                "".join(char for char in value if char.isalnum())
                if normalized
                else value
            )

        prepared = [prepare(query) for query in queries]
        if any(not query for query in prepared):
            raise ToolError("queries must not be empty or contain empty strings")
        files = []
        pending = [path]
        if stat.S_ISREG(metadata.st_mode):
            files.append(path)
            pending.clear()
        elif not stat.S_ISDIR(metadata.st_mode):
            pending.clear()
        while pending:
            for child, info in self._entries(pending.pop()):
                if child.name.startswith(".") or stat.S_ISLNK(info.st_mode):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    pending.append(child)
                elif stat.S_ISREG(info.st_mode):
                    files.append(child)
        matches = []
        for file in files:
            try:
                lines = _rust_lines(file.read_bytes().decode("utf-8"))
            except UnicodeError:
                continue
            flags = [[query in prepare(line) for query in prepared] for line in lines]
            windows = []
            if mode["type"] in {"any", "all_on_same_line"}:
                check = any if mode["type"] == "any" else all
                windows = [(i, i, row) for i, row in enumerate(flags) if check(row)]
            else:
                for start, row in enumerate(flags):
                    if not any(row):
                        continue
                    combined = [False] * len(queries)
                    for end in range(
                        start, min(len(lines), start + mode["line_count"])
                    ):
                        combined = [
                            left or right
                            for left, right in zip(combined, flags[end], strict=True)
                        ]
                        if all(combined):
                            windows.append((start, end, combined))
                            break
                windows = [
                    (start, end, row)
                    for start, end, row in windows
                    if not any(
                        start <= other_start
                        and end >= other_end
                        and (start, end) != (other_start, other_end)
                        for other_start, other_end, _ in windows
                    )
                ]
            context = args.get("context_lines") or 0
            for start, end, row in windows:
                content_start = max(0, start - context)
                matches.append(
                    {
                        "path": file.relative_to(self.root).as_posix(),
                        "match_line_number": start + 1,
                        "content_start_line_number": content_start + 1,
                        "content": "\n".join(
                            lines[content_start : min(len(lines), end + context + 1)]
                        ),
                        "matched_queries": [
                            query
                            for query, matched in zip(queries, row, strict=True)
                            if matched
                        ],
                    }
                )
        matches.sort(key=lambda match: (match["path"], match["match_line_number"]))
        page, cursor, truncated = _page(
            matches,
            args.get("cursor"),
            _result_limit(args, 200),
        )
        return {
            "queries": queries,
            "match_mode": mode,
            "path": relative,
            "matches": page,
            "next_cursor": cursor,
            "truncated": truncated,
        }

    def add_ad_hoc_note(self, args):
        filename, note = args["filename"], args["note"]
        reason = None
        if len(filename.encode()) > 128:
            reason = "must be at most 128 bytes"
        elif not filename.endswith(".md"):
            reason = "must end with .md"
        elif not re.match(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}-.", filename[:-3]
        ):
            reason = "must use YYYY-MM-DDTHH-MM-SS-<slug>.md"
        else:
            slug = filename[20:-3]
            if not 1 <= len(slug.encode()) <= 80:
                reason = "slug must be 1 to 80 bytes"
            elif not re.fullmatch(r"[a-z0-9-]+", slug):
                reason = (
                    "slug must contain only lowercase ASCII letters, digits, or hyphens"
                )
        if reason:
            raise ToolError(f"filename '{filename}' {reason}")
        if not note.strip():
            raise ToolError("ad-hoc note must not be empty")
        directory = self.root
        for component in (None, "extensions", "ad_hoc", "notes"):
            if component:
                directory /= component
            info = _metadata(directory)
            if info is None:
                directory.mkdir()
                info = directory.lstat()
            if stat.S_ISLNK(info.st_mode):
                _invalid_path(directory, "must not be a symlink")
            if not stat.S_ISDIR(info.st_mode):
                _invalid_path(directory, "must be a directory")
        try:
            with (directory / filename).open("xb") as file:
                file.write(note.encode())
        except FileExistsError:
            raise ToolError(f"ad-hoc note '{filename}' already exists") from None
        return {}


def parse_memory_citation(citations):
    """Parse the pinned rendering envelope; UUID validation belongs to the caller."""
    entries, rollout_ids = [], []

    def block(text, name):
        opening, closing = f"<{name}>", f"</{name}>"
        return (
            text.split(opening, 1)[1].split(closing, 1)[0]
            if opening in text and closing in text.split(opening, 1)[1]
            else None
        )

    for citation in citations:
        for line in (block(citation, "citation_entries") or "").splitlines():
            try:
                location, note = line.strip().rsplit("|note=[", 1)
                if not note.endswith("]"):
                    continue
                path, numbers = location.rsplit(":", 1)
                start, end = numbers.split("-", 1)
                if not re.fullmatch(r"\+?[0-9]+", start.strip()) or not re.fullmatch(
                    r"\+?[0-9]+", end.strip()
                ):
                    continue
                start, end = int(start), int(end)
                if max(start, end) > (1 << 32) - 1:
                    continue
                entries.append(
                    {
                        "path": path.strip(),
                        "line_start": start,
                        "line_end": end,
                        "note": note[:-1].strip(),
                    }
                )
            except ValueError:
                continue
        ids = block(citation, "rollout_ids")
        if ids is None:
            ids = block(citation, "thread_ids")
        for identity in (ids or "").splitlines():
            identity = identity.strip()
            if identity and identity not in rollout_ids:
                rollout_ids.append(identity)
    return (
        {"entries": entries, "rollout_ids": rollout_ids}
        if entries or rollout_ids
        else None
    )
