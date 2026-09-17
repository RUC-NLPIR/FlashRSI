"""SkillOpt's private JSON edit protocol and protected slow-update section."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

_SOURCES = ("failure", "success")
_START = "<!-- SLOW_UPDATE_START -->"
_END = "<!-- SLOW_UPDATE_END -->"


class _PatchError(ValueError):
    """A Worker response is malformed or cannot safely edit the current skill."""


def _json(text: str) -> dict[str, Any]:
    """Accept the requested JSON object, optionally inside one Markdown fence."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.partition("\n")[2].removesuffix("```").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise _PatchError("Worker must return a valid JSON object") from error
    if not isinstance(value, dict):
        raise _PatchError("Worker must return a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class _Edit:
    op: str
    path: str
    content: str = ""
    target: str = ""
    support_count: int | None = None
    source_type: str = "failure"

    @classmethod
    def parse(cls, value: Mapping[str, Any], source_type: str = "") -> _Edit:
        path = value.get("path")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
            or ":" in path
            or "\x00" in path
        ):
            raise _PatchError("edit path must be a relative POSIX file path")
        op = value.get("op")
        if op not in ("append", "insert_after", "replace", "delete"):
            raise _PatchError("unsupported skill edit operation")
        content, target = value.get("content", ""), value.get("target", "")
        if not isinstance(content, str) or not isinstance(target, str):
            raise _PatchError("skill edit content and target must be strings")
        if op != "delete" and not content.strip():
            raise _PatchError(f"{op} edit requires non-empty content")
        if op != "append" and not target:
            raise _PatchError(f"{op} edit requires a non-empty target")
        support = value.get("support_count")
        if support is not None and (type(support) is not int or support < 0):
            raise _PatchError("support_count must be a non-negative integer")
        source = source_type or value.get("source_type", "failure")
        if source not in _SOURCES:
            raise _PatchError("source_type must be failure or success")
        return cls(op, path, content, target, support, source)

    def apply(self, text: str) -> str:
        """Apply one exact edit without changing protected guidance."""
        protected = _section(text)
        if self.op == "append":
            result = _append(text, self.content)
        else:
            start = text.find(self.target)
            if start < 0 or text.find(self.target, start + 1) >= 0:
                raise _PatchError("edit target must occur exactly once in the skill")
            end = start + len(self.target)
            if protected is not None:
                left = text.index(_START)
                right = text.index(_END) + len(_END)
                if start < right and end > left:
                    raise _PatchError(
                        "fast edits cannot target the SLOW_UPDATE section"
                    )
            if self.op == "insert_after":
                result = text[:end] + "\n" + self.content + text[end:]
            elif self.op == "replace":
                result = text[:start] + self.content + text[end:]
            else:  # delete
                result = text[:start] + text[end:]
        if _section(result) != protected:
            raise _PatchError("fast edits cannot change the SLOW_UPDATE section")
        return result


@dataclass(frozen=True, slots=True)
class _Patch:
    edits: tuple[_Edit, ...] = ()
    reasoning: str = ""

    @classmethod
    def parse(cls, text: str, source_type: str = "") -> _Patch:
        value = _json(text)
        body = value.get("patch", value)
        if not isinstance(body, dict):
            raise _PatchError("patch must be a JSON object")
        edits = body.get("edits")
        if not isinstance(edits, list) or any(
            not isinstance(edit, dict) for edit in edits
        ):
            raise _PatchError("patch requires an edits list of objects")
        reasoning = body.get("reasoning", value.get("reasoning", ""))
        if not isinstance(reasoning, str):
            raise _PatchError("patch reasoning must be a string")
        return cls(tuple(_Edit.parse(edit, source_type) for edit in edits), reasoning)

    def apply(self, files: Mapping[str, str], budget: int) -> dict[str, str]:
        """Calculate all edits before the caller writes or commits any files."""
        if type(budget) is not int or budget < 1:
            raise ValueError("edit budget must be a positive integer")
        if len(self.edits) > budget:
            raise _PatchError("patch exceeds the edit budget")
        result = dict(files)
        for edit in self.edits:
            if edit.path not in result and edit.op != "append":
                raise _PatchError("only append may create a new skill file")
            result[edit.path] = edit.apply(result.get(edit.path, ""))
        return result

    def select(self, indices: Sequence[int]) -> _Patch:
        return _Patch(tuple(self.edits[index] for index in indices), self.reasoning)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "reasoning": self.reasoning,
            "edits": [asdict(edit) for edit in self.edits],
        }


def _append(text: str, content: str) -> str:
    separator = "" if not text else "\n" if text.endswith("\n") else "\n\n"
    ending = "" if content.endswith("\n") else "\n"
    return text + separator + content + ending


def _section(text: str) -> str | None:
    """Return the exact protected region, rejecting duplicate or unpaired markers."""
    starts, ends = text.count(_START), text.count(_END)
    if starts == ends == 0:
        return None
    if starts != 1 or ends != 1 or text.index(_START) > text.index(_END):
        raise _PatchError("skill must contain one balanced SLOW_UPDATE section")
    return text[text.index(_START) : text.index(_END) + len(_END)]


def _replace_section(text: str, content: str) -> str:
    """Only the slow update may replace this region or create it when absent."""
    if _START in content or _END in content:
        raise _PatchError("slow_update_content must omit the SLOW_UPDATE markers")
    current = _section(text)
    body = content.strip()
    replacement = f"{_START}\n{body}\n{_END}" if body else f"{_START}\n{_END}"
    return (
        text.replace(current, replacement, 1)
        if current is not None
        else _append(text, replacement)
    )


def _field(text: str, name: str) -> str:
    value = _json(text).get(name)
    if not isinstance(value, str):
        raise _PatchError(f"Worker response requires a string {name}")
    return value.strip()


def _apply_guidance(files: Mapping[str, str], reply: str) -> dict[str, str]:
    """Read the slow-update response and rewrite its selected protected regions."""
    guidance = _json(reply).get("guidance")
    if not isinstance(guidance, list):
        raise _PatchError("slow update requires a guidance list")
    result = dict(files)
    seen = set()
    for item in guidance:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or item["path"] not in files
            or not isinstance(item.get("content"), str)
        ):
            raise _PatchError(
                "slow guidance requires an existing text path and string content"
            )
        path = item["path"]
        if path in seen:
            raise _PatchError("slow guidance paths must be unique")
        seen.add(path)
        result[path] = _replace_section(files[path], item["content"])
    return result


def _ranked(text: str, *, size: int, limit: int) -> tuple[int, ...]:
    indices = _json(text).get("selected_indices")
    if not isinstance(indices, list) or any(
        type(index) is not int or not 0 <= index < size for index in indices
    ):
        raise _PatchError("selected_indices must contain valid edit indices")
    if len(indices) > limit or len(set(indices)) != len(indices):
        raise _PatchError("selected_indices must be unique and within the edit budget")
    return tuple(indices)
