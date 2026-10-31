"""Python port of codex apply-patch at rust-v0.147.0 (be6e8eac).

Sources: apply-patch/src/{invocation,parser,streaming_parser,seek_sequence,lib,
standalone_executable}.rs.
The model tool verifies all hunks before execution; filesystem failures during
execution may still leave partial changes, as in the upstream implementation.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable


class PatchError(ValueError):
    pass


# Exact APPLY_PATCH_QUERY from apply-patch/src/invocation.rs. Both ports use
# tree-sitter-bash 0.25.1; matching is against the complete script AST.
APPLY_PATCH_QUERY = r"""
            (
              program
                . (redirected_statement
                    body: (command
                            name: (command_name (word) @apply_name) .)
                    (#any-of? @apply_name "apply_patch" "applypatch")
                    redirect: (heredoc_redirect
                                . (heredoc_start)
                                . (heredoc_body) @heredoc
                                . (heredoc_end)
                                .))
                .)

            (
              program
                . (redirected_statement
                    body: (list
                            . (command
                                name: (command_name (word) @cd_name) .
                                argument: [
                                  (word) @cd_path
                                  (string (string_content) @cd_path)
                                  (raw_string) @cd_raw_string
                                ] .)
                            "&&"
                            . (command
                                name: (command_name (word) @apply_name))
                            .)
                    (#eq? @cd_name "cd")
                    (#any-of? @apply_name "apply_patch" "applypatch")
                    redirect: (heredoc_redirect
                                . (heredoc_start)
                                . (heredoc_body) @heredoc
                                . (heredoc_end)
                                .))
                .)
            """


@lru_cache(maxsize=1)
def _bash_query():
    import tree_sitter_bash
    from tree_sitter import Language, Query

    language = Language(tree_sitter_bash.language())
    return language, Query(language, APPLY_PATCH_QUERY)


def _shell_script(argv: list[str]) -> str | None:
    if len(argv) not in {3, 4}:
        return None
    shell = Path(argv[0]).stem.lower()
    flag = argv[1]
    if len(argv) == 4:
        if shell not in {"pwsh", "powershell"} or flag.lower() != "-noprofile":
            return None
        flag = argv[2]
    if (
        shell in {"bash", "zsh", "sh"}
        and flag in {"-lc", "-c"}
        or shell in {"pwsh", "powershell"}
        and flag.lower() == "-command"
        or shell == "cmd"
        and flag.lower() == "/c"
    ):
        return argv[-1]
    return None


def patch_command(argv: list[str], cwd: Path) -> tuple[str, Path] | None:
    """invocation::maybe_parse_apply_patch: explicit argv or whole heredoc script.

    Only the single-statement forms intercepted upstream enter this path;
    compound scripts continue through the shell's ordinary execution path.
    """
    if len(argv) == 2 and argv[0] in {"apply_patch", "applypatch"}:
        return argv[1], cwd
    script = _shell_script(argv)
    raw = argv[0] if len(argv) == 1 else script
    if raw is None:
        return None
    try:
        parse_patch(raw)
    except PatchError:
        pass
    else:
        raise PatchError(
            'patch detected without explicit call to apply_patch. Rerun as ["apply_patch", "<patch>"]'
        )
    if script is None:
        return None
    from tree_sitter import Parser, QueryCursor

    language, query = _bash_query()
    source = script.encode("utf-8")
    tree = Parser(language).parse(source)
    for _, captures in QueryCursor(query).matches(tree.root_node):
        heredoc = None
        selected_cwd = cwd
        for name, nodes in captures.items():
            for node in nodes:
                text = source[node.start_byte : node.end_byte].decode("utf-8")
                if name == "heredoc":
                    heredoc = text.rstrip("\n")
                elif name == "cd_path":
                    selected_cwd = cwd / text
                elif name == "cd_raw_string":
                    selected_cwd = cwd / text.removeprefix("'").removesuffix("'")
        if heredoc is not None:
            return heredoc, selected_cwd
    return None


@dataclass
class Chunk:
    context: str | None = None
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    eof: bool = False


@dataclass
class Hunk:
    kind: str
    path: str
    contents: str = ""
    move: str | None = None
    chunks: list[Chunk] = field(default_factory=list)
    line: int = 0


def _invalid_hunk(number: int, message: str):
    raise PatchError(f"invalid hunk at line {number}, {message}")


def parse_patch(text: str) -> tuple[list[Hunk], str | None]:
    """parser::parse_patch_text + StreamingPatchParser::process_line."""
    stripped = text.strip()
    lines = (
        [line.removesuffix("\r") for line in stripped.split("\n")] if stripped else []
    )
    if (
        len(lines) >= 4
        and lines[0] in {"<<EOF", "<<'EOF'", '<<"EOF"'}
        and lines[-1].endswith("EOF")
    ):
        lines = lines[1:-1]
    if lines and lines[0].strip() != "*** Begin Patch":
        raise PatchError(
            "invalid patch: The first line of the patch must be '*** Begin Patch'"
        )
    if not lines or lines[-1].strip() != "*** End Patch":
        raise PatchError(
            "invalid patch: The last line of the patch must be '*** End Patch'"
        )
    hunks: list[Hunk] = []
    environment_id = None
    ended = False

    def ensure_update(number, line):
        if not hunks or hunks[-1].kind != "update":
            return
        hunk = hunks[-1]
        if not hunk.chunks:
            _invalid_hunk(
                hunk.line, f"Update file hunk for path '{hunk.path}' is empty"
            )
        if not hunk.chunks[-1].old and not hunk.chunks[-1].new:
            if line == "*** End Patch":
                _invalid_hunk(number, "Update hunk does not contain any lines")
            _invalid_hunk(number, _unexpected(line))

    for number, line in enumerate(lines[1:], 2):
        trimmed = line.strip()
        if ended:
            if trimmed:
                raise PatchError(
                    "invalid patch: The last line of the patch must be '*** End Patch'"
                )
            continue
        if not hunks and trimmed.startswith("*** Environment ID:"):
            if environment_id is not None:
                raise PatchError(
                    "invalid patch: apply_patch environment_id cannot be specified more than once"
                )
            environment_id = trimmed[len("*** Environment ID:") :].strip()
            if not environment_id:
                raise PatchError(
                    "invalid patch: apply_patch environment_id cannot be empty"
                )
            continue
        # UpdateFile headers trim only trailing space. Other modes trim both.
        header = line.rstrip() if hunks and hunks[-1].kind == "update" else trimmed
        if header == "*** End Patch":
            ensure_update(number, header)
            ended = True
            continue
        header_matched = False
        for marker, kind in (
            ("*** Add File: ", "add"),
            ("*** Delete File: ", "delete"),
            ("*** Update File: ", "update"),
        ):
            if header.startswith(marker):
                ensure_update(number, header)
                hunks.append(Hunk(kind, header[len(marker) :], line=number))
                header_matched = True
                break
        if header_matched:
            continue
        if not hunks or hunks[-1].kind in {"add", "delete"}:
            if hunks and hunks[-1].kind == "add" and line.startswith("+"):
                hunks[-1].contents += line[1:] + "\n"
                continue
            _invalid_hunk(
                number,
                f"'{trimmed}' is not a valid hunk header. Valid hunk headers: '*** Add File: {{path}}', '*** Delete File: {{path}}', '*** Update File: {{path}}'",
            )
        hunk = hunks[-1]
        update_line = line.rstrip()
        if hunk.chunks and hunk.chunks[-1].eof:
            if not update_line:
                continue
            if update_line != "@@" and not update_line.startswith("@@ "):
                _invalid_hunk(
                    number,
                    f"Expected update hunk to start with a @@ context marker, got: '{line}'",
                )
        if (
            not hunk.chunks
            and hunk.move is None
            and update_line.startswith("*** Move to: ")
        ):
            hunk.move = update_line[len("*** Move to: ") :]
            continue
        if update_line == "@@" or update_line.startswith("@@ "):
            if hunk.chunks and not hunk.chunks[-1].old and not hunk.chunks[-1].new:
                _invalid_hunk(number, _unexpected(line))
            hunk.chunks.append(
                Chunk(
                    context=update_line[3:] if update_line.startswith("@@ ") else None
                )
            )
            continue
        if update_line == "*** End of File":
            if hunk.chunks:
                if not hunk.chunks[-1].old and not hunk.chunks[-1].new:
                    _invalid_hunk(number, "Update hunk does not contain any lines")
                hunk.chunks[-1].eof = True
            continue
        if not line or line[0] in " +-":
            if not hunk.chunks:
                hunk.chunks.append(Chunk())
            chunk = hunk.chunks[-1]
            prefix, value = (line[0], line[1:]) if line else (" ", "")
            if prefix in " -":
                chunk.old.append(value)
            if prefix in " +":
                chunk.new.append(value)
            continue
        if hunk.chunks and (hunk.chunks[-1].old or hunk.chunks[-1].new):
            _invalid_hunk(
                number,
                f"Expected update hunk to start with a @@ context marker, got: '{line}'",
            )
        _invalid_hunk(number, _unexpected(line))
    return hunks, environment_id


def _unexpected(line):
    return f"Unexpected line found in update hunk: '{line}'. Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)"


_UNICODE_NORMALIZATION = str.maketrans(
    {
        **dict.fromkeys("‐‑‒–—―−", "-"),
        **dict.fromkeys("‘’‚‛", "'"),
        **dict.fromkeys("“”„‟", '"'),
        **dict.fromkeys(
            "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000",
            " ",
        ),
    }
)


def seek_sequence(
    lines: list[str], pattern: list[str], start: int, eof: bool
) -> int | None:
    """seek_sequence::seek_sequence, including its EOF search semantics."""
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None
    first = len(lines) - len(pattern) if eof else start
    normalizers = (
        lambda s: s,
        str.rstrip,
        str.strip,
        lambda s: s.strip().translate(_UNICODE_NORMALIZATION),
    )
    for normalize in normalizers:
        normalized_pattern = [normalize(s) for s in pattern]
        for index in range(first, len(lines) - len(pattern) + 1):
            if [
                normalize(s) for s in lines[index : index + len(pattern)]
            ] == normalized_pattern:
                return index
    return None


def updated_contents(original: str, path: Path, chunks: list[Chunk]) -> str:
    """lib::compute_replacements + apply_replacements."""
    lines = original.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    replacements = []
    line_index = 0
    for chunk in chunks:
        if chunk.context is not None:
            index = seek_sequence(lines, [chunk.context], line_index, False)
            if index is None:
                raise PatchError(f"Failed to find context '{chunk.context}' in {path}")
            line_index = index + 1
        if not chunk.old:
            insertion = len(lines) - 1 if lines and not lines[-1] else len(lines)
            replacements.append((insertion, 0, chunk.new))
            continue
        pattern, new_lines = chunk.old, chunk.new
        index = seek_sequence(lines, pattern, line_index, chunk.eof)
        if index is None and not pattern[-1]:
            pattern = pattern[:-1]
            if new_lines and not new_lines[-1]:
                new_lines = new_lines[:-1]
            index = seek_sequence(lines, pattern, line_index, chunk.eof)
        if index is None:
            raise PatchError(
                f"Failed to find expected lines in {path}:\n" + "\n".join(chunk.old)
            )
        replacements.append((index, len(pattern), new_lines))
        line_index = index + len(pattern)
    for index, length, new_lines in reversed(sorted(replacements, key=lambda r: r[0])):
        lines[index : index + length] = new_lines
    if not lines or lines[-1]:
        lines.append("")
    return "\n".join(lines)


def apply_patch_sync(
    text: str,
    cwd: Path,
    authorize: Callable[[Path, bool], None] | None = None,
    *,
    verify: bool = True,
) -> tuple[str, bool]:
    """Verify first, then lib::apply_hunks_to_files in input order."""
    try:
        hunks, environment_id = parse_patch(text)
        if environment_id is not None and verify:
            raise PatchError(
                "apply_patch environment_id is only supported when multiple environments are available"
            )
        if not hunks:
            raise PatchError("No files were modified.")
        operations = []
        for hunk in hunks:
            path = cwd / hunk.path
            destination = cwd / hunk.move if hunk.move else path
            if authorize:
                authorize(path, True)
                authorize(destination, True)
            if hunk.kind == "update" and verify:
                original = _read_text(path, "Failed to read file to update")
                updated_contents(original, path, hunk.chunks)
            elif hunk.kind == "delete" and verify:
                _read_text(path, "Failed to read")
            operations.append((hunk, path, destination))
    except (PatchError, OSError, PermissionError) as error:
        if not verify:
            message = str(error)
            if message.startswith("invalid patch: "):
                message = "Invalid patch: " + message.removeprefix("invalid patch: ")
            elif message.startswith("invalid hunk at line "):
                number, _, detail = message.removeprefix(
                    "invalid hunk at line "
                ).partition(", ")
                message = f"Invalid patch hunk on line {number}: {detail}"
            return message + "\n", False
        return f"apply_patch verification failed: {error}", False
    affected = {"add": [], "update": [], "delete": []}
    try:
        for hunk, path, destination in operations:
            if hunk.kind == "delete":
                if path.is_dir():
                    raise OSError(f"Failed to delete file {path}: path is a directory")
                path.unlink()
            else:
                contents = (
                    updated_contents(
                        _read_text(path, "Failed to read file to update"),
                        path,
                        hunk.chunks,
                    )
                    if hunk.kind == "update"
                    else hunk.contents
                )
                if hunk.kind == "add" or hunk.move:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents.encode("utf-8"))
                if hunk.move:
                    path.unlink()
            affected[hunk.kind].append(hunk.move or hunk.path)
    except (OSError, PatchError) as error:
        return f"{error}\n", False
    output = ["Success. Updated the following files:"]
    for kind, marker in (("add", "A"), ("update", "M"), ("delete", "D")):
        output.extend(f"{marker} {path}" for path in affected[kind])
    return "\n".join(output) + "\n", True


def _read_text(path, prefix):
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        detail = (
            f"incomplete utf-8 byte sequence from index {error.start}"
            if error.reason == "unexpected end of data"
            else f"invalid utf-8 sequence of {error.end - error.start} bytes from index {error.start}"
        )
        raise PatchError(f"{prefix} {path}: {detail}") from error
    except OSError as error:
        detail = (
            f"{os.strerror(error.errno)} (os error {error.errno})"
            if error.errno is not None
            else str(error)
        )
        raise PatchError(f"{prefix} {path}: {detail}") from error


async def apply_patch(text: str, cwd: Path, authorize=None) -> tuple[str, bool]:
    return await asyncio.to_thread(apply_patch_sync, text, cwd, authorize)


def standalone_main(arguments: list[str]) -> int:
    """standalone_executable::run_main using the same Python patch core."""
    import sys

    if len(arguments) > 1:
        print("Error: apply_patch accepts exactly one argument.", file=sys.stderr)
        return 2
    if arguments:
        text = arguments[0]
        if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            print(
                "Error: apply_patch requires a UTF-8 PATCH argument.", file=sys.stderr
            )
            return 1
    else:
        try:
            text = sys.stdin.buffer.read().decode("utf-8")
        except (UnicodeError, OSError):
            print(
                "Error: Failed to read PATCH from stdin.\nstream did not contain valid UTF-8",
                file=sys.stderr,
            )
            return 1
        if not text:
            print(
                "Usage: apply_patch 'PATCH'\n       echo 'PATCH' | apply_patch",
                file=sys.stderr,
            )
            return 2
    output, success = apply_patch_sync(text, Path.cwd(), verify=False)
    print(output, end="", file=sys.stdout if success else sys.stderr)
    return 0 if success else 1


if __name__ == "__main__":
    # The router runs this same Python implementation under the OS sandbox.
    # Keeping filesystem writes inside the sandbox also closes authorization /
    # symlink races between a model-provided path and the eventual write.
    import json
    import sys

    if sys.argv[1:2] == ["--standalone"]:
        raise SystemExit(standalone_main(sys.argv[2:]))
    print(
        json.dumps(apply_patch_sync(sys.stdin.read(), Path.cwd()), ensure_ascii=False)
    )
