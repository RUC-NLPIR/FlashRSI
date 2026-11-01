"""Native glob/ignore matching shared by Pi resources and local search tools.

Git wildmatch's slash boundaries, globstars, escaped markers and directory
negation rules are implemented here, without spawning git/rg/fd or npm code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _glob_regex(pattern: str) -> str:
    result = ""
    index = 0
    while index < len(pattern):
        character = pattern[index]
        index += 1
        if character == "\\" and index < len(pattern):
            result += re.escape(pattern[index])
            index += 1
        elif character == "*":
            if index < len(pattern) and pattern[index] == "*":
                while index < len(pattern) and pattern[index] == "*":
                    index += 1
                if index < len(pattern) and pattern[index] == "/":
                    result += "(?:.*/)?"
                    index += 1
                else:
                    result += ".*"
            else:
                result += "[^/]*"
        elif character == "?":
            result += "[^/]"
        elif character == "[":
            end = pattern.find(
                "]", index + int(pattern[index : index + 1] in {"!", "^"})
            )
            if end < 0:
                result += r"\["
            else:
                body = pattern[index:end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                result += "[" + body.replace("\\", "\\\\") + "]"
                index = end + 1
        else:
            result += re.escape(character)
    return result


def matches_glob(
    path: str, pattern: str, *, basename: bool = False, ignore_case: bool = False
) -> bool:
    candidate = path.rsplit("/", 1)[-1] if basename else path
    try:
        return (
            re.fullmatch(_glob_regex(pattern), candidate, re.I if ignore_case else 0)
            is not None
        )
    except re.error:
        return candidate == pattern


class IgnoreRules:
    def __init__(
        self,
        root: Path | str,
        names=(".gitignore", ".ignore", ".fdignore"),
        *,
        ignore_case: bool = False,
        prefix_rules: bool = False,
        exclude_git: bool = True,
        boundary: Path | str | None = None,
    ):
        self.root = Path(os.path.abspath(root))
        self.names = names
        self.ignore_case = ignore_case
        self.prefix_rules = prefix_rules
        self.exclude_git = exclude_git
        self.boundary = (
            Path(os.path.abspath(boundary)) if boundary is not None else self.root
        )
        self._cache: dict[Path, list[tuple[str, bool, bool, bool]]] = {}

    def _rules(self, directory: Path):
        if directory in self._cache:
            return self._cache[directory]
        rules = []
        for name in self.names:
            try:
                lines = (directory / name).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line in lines:
                # Git ignores unescaped trailing spaces, preserving escaped ones.
                line = re.sub(r"(?<!\\) +$", "", line)
                if not line or line.startswith("#"):
                    continue
                negated = line.startswith("!")
                if negated:
                    line = line[1:]
                elif self.prefix_rules and line.startswith("\\!"):
                    # skills.ts removes this escape before passing its
                    # prefixed pattern to ignore; at root it becomes negation.
                    line = line[1:]
                    if directory == self.root:
                        negated, line = True, line[1:]
                anchored = line.startswith("/") and not self.prefix_rules
                line = line.lstrip("/")
                directory_only = line.endswith("/")
                line = line.rstrip("/")
                if line:
                    rules.append((line, negated, directory_only, anchored))
        self._cache[directory] = rules
        return rules

    def is_ignored(self, path: Path | str, is_dir: bool | None = None) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            return False
        if not relative.parts:
            return False
        try:
            boundary_depth = len(self.boundary.relative_to(self.root).parts)
        except ValueError:
            boundary_depth = 0
        if self.exclude_git and ".git" in relative.parts[boundary_depth:]:
            return True
        if is_dir is None:
            is_dir = candidate.is_dir()
        # A negation cannot resurrect a path inside an ignored parent directory.
        for depth in range(boundary_depth + 1, len(relative.parts) + 1):
            current = self.root.joinpath(*relative.parts[:depth])
            current_is_dir = depth < len(relative.parts) or is_dir
            ignored = False
            for scope in range(depth):
                directory = self.root.joinpath(*relative.parts[:scope])
                local = current.relative_to(directory).as_posix()
                for pattern, negated, directory_only, anchored in self._rules(
                    directory
                ):
                    if directory_only and not current_is_dir:
                        continue
                    # skills.ts prefixes nested patterns before handing them to
                    # npm ignore; that deliberately anchors them to the scope.
                    basename = (
                        "/" not in pattern
                        and not anchored
                        and not (self.prefix_rules and scope)
                    )
                    if matches_glob(
                        local, pattern, basename=basename, ignore_case=self.ignore_case
                    ):
                        ignored = not negated
            if ignored:
                return True
        return False


def walk_lifo(root: Path, rules: IgnoreRules, *, include_hidden: bool = True,
              include_ignored: bool = False, directories: bool = False, symlinks: bool = False):
    """Use ignore::WalkParallel's local depth-first LIFO work queue.

    Both rg and fd enqueue readdir entries in OS order and consume the local
    queue from its end. Worker stealing can interleave subtrees upstream; this
    preserves each worker's actual traversal order without alphabetic sorting.
    """
    pending = [Path(root)]
    while pending:
        path = pending.pop()
        is_link = path.is_symlink()
        is_dir = path.is_dir() and not is_link
        if path != root:
            if path.name == ".git" or (not include_hidden and path.name.startswith(".")):
                continue
            if not include_ignored and rules.is_ignored(path, is_dir=is_dir):
                continue
            if is_link and not symlinks:
                continue
            if (is_dir and directories) or not is_dir:
                yield path
        if is_dir:
            try:
                with os.scandir(path) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
            except OSError:
                continue
