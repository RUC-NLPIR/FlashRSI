"""Pi-compatible Snapshot resource discovery and system prompt construction."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools import tool_schemas


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str
    path: str
    disable_model_invocation: bool = False


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    description: str
    content: str
    path: str
    argument_hint: str | None = None


@dataclass
class ResourceBundle:
    system_prompt: str
    skills: list[Skill] = field(default_factory=list)
    templates: dict[str, PromptTemplate] = field(default_factory=dict)
    context_files: list[dict[str, str]] = field(default_factory=list)
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    # Pi normalizes line endings before parsing and trims the body only when a
    # frontmatter block is present.  Keep the no-frontmatter path byte-for-byte
    # (apart from BOM removal) because prompt contents without metadata are
    # passed through unchanged by the upstream loader.
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        import yaml

        value = yaml.safe_load(match.group(1)) or {}
        return (value if isinstance(value, dict) else {}), text[match.end() :].strip()
    except Exception as exc:
        # The upstream loader reports malformed frontmatter and skips that
        # resource.  Preserve the error so callers can add a diagnostic rather
        # than silently treating the file as metadata-free.
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc


def _skill_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result: list[Path] = []
    for current, directories, files in os.walk(root):
        directory = Path(current)
        declared = directory / "SKILL.md"
        # A declared skill owns its whole directory, even at the search root.
        # Do not discover separate skills or loose Markdown files inside it.
        if declared.is_file():
            result.append(declared)
            directories.clear()
            continue
        directories[:] = sorted(
            name
            for name in directories
            if not name.startswith(".") and name != "node_modules"
        )
        # Pi accepts loose Markdown skills only directly in the search root;
        # nested directories must declare their skill with SKILL.md.
        if directory == root:
            result.extend(
                directory / name
                for name in sorted(files)
                if not name.startswith(".")
                and name.endswith(".md")
                and (directory / name).is_file()
            )
    return result


def _load_skills(root: Path, diagnostics: list[str]) -> list[Skill]:
    result: list[Skill] = []
    for path in _skill_files(root):
        try:
            raw = path.read_text(encoding="utf-8")
            metadata, body = _parse_frontmatter(raw)
        except OSError as exc:
            diagnostics.append(f"Could not read skill {path}: {exc}")
            continue
        except ValueError as exc:
            diagnostics.append(f"Could not parse skill {path}: {exc}")
            continue
        name = str(metadata.get("name") or path.parent.name)
        description = metadata.get("description")
        valid_name = (
            bool(re.fullmatch(r"[a-z0-9-]{1,64}", name))
            and not name.startswith("-")
            and not name.endswith("-")
            and "--" not in name
        )
        valid_description = (
            isinstance(description, str)
            and bool(description.strip())
            and len(description) <= 1024
        )
        if not valid_name or not valid_description:
            diagnostics.append(f"Invalid skill metadata: {path}")
            continue
        result.append(
            Skill(
                name=name,
                description=description.strip(),
                content=body.strip(),
                path=str(path),
                disable_model_invocation=bool(
                    metadata.get("disable-model-invocation", False)
                ),
            )
        )
    return result


def _load_templates(root: Path, diagnostics: list[str]) -> dict[str, PromptTemplate]:
    result: dict[str, PromptTemplate] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
            metadata, body = _parse_frontmatter(raw)
        except OSError as exc:
            diagnostics.append(f"Could not read prompt template {path}: {exc}")
            continue
        except ValueError as exc:
            diagnostics.append(f"Could not parse prompt template {path}: {exc}")
            continue
        name = path.stem
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            first_line = next(
                (line.strip() for line in body.splitlines() if line.strip()), ""
            )
            description = first_line[:60] + ("..." if len(first_line) > 60 else "")
        argument_hint = metadata.get("argument-hint")
        if not isinstance(argument_hint, str) or not argument_hint:
            argument_hint = None
        result[name] = PromptTemplate(
            name=name,
            description=description,
            content=body,
            path=str(path),
            argument_hint=argument_hint,
        )
    return result


def substitute_template(content: str, arguments: list[str] | tuple[str, ...]) -> str:
    """Apply Pi's $1/$@/${N:-default}/${@:N} substitutions once."""

    args = list(arguments)
    all_args = " ".join(args)

    def replace(match: re.Match[str]) -> str:
        target, default, slice_start, slice_length, simple = match.groups()
        if target:
            value = (
                all_args
                if target in {"@", "ARGUMENTS"}
                else (args[int(target) - 1] if 1 <= int(target) <= len(args) else "")
            )
            return value or default
        if slice_start:
            start = max(0, int(slice_start) - 1)
            end = start + int(slice_length) if slice_length else None
            return " ".join(args[start:end])
        if simple in {"@", "ARGUMENTS"}:
            return all_args
        index = int(simple) - 1
        return args[index] if 0 <= index < len(args) else ""

    pattern = re.compile(
        r"\$\{([0-9]+|ARGUMENTS|@):-([^}]*)\}|\$\{@:([0-9]+)(?::([0-9]+))?\}|\$(ARGUMENTS|@|[0-9]+)"
    )
    return pattern.sub(replace, content)


def expand_prompt_template(
    text: str, templates: dict[str, PromptTemplate] | list[PromptTemplate]
) -> str:
    """Expand a Pi ``/name args`` prompt invocation when one is present."""

    match = re.match(r"^/([^\s]+)(?:\s+(.*))?$", text, re.DOTALL)
    if match is None:
        return text
    name, argument_text = match.group(1), match.group(2) or ""
    template = (
        templates.get(name)
        if isinstance(templates, dict)
        else next((item for item in templates if item.name == name), None)
    )
    if template is None:
        return text
    arguments = _parse_prompt_args(argument_text)
    return substitute_template(template.content, arguments)


def _parse_prompt_args(argument_text: str) -> list[str]:
    """Parse quoted prompt-template arguments like Pi's shell-style parser."""
    arguments: list[str] = []
    current: list[str] = []
    has_token = False
    quote: str | None = None
    for char in argument_text:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in {'"', "'"}:
            quote = char
            has_token = True
        elif char.isspace():
            if has_token:
                arguments.append("".join(current))
                current = []
                has_token = False
        else:
            current.append(char)
            has_token = True
    if has_token:
        arguments.append("".join(current))
    return arguments


def default_tools(files_dir: str | Path) -> list[str]:
    """Resolve Snapshot ``defaultTools`` like Pi's SettingsManager.

    Plain names replace the built-in defaults; a modifier-only list changes
    those defaults. Settings permit mixed names/modifiers (unlike the SDK's
    explicit ``tools`` option), and apply every modifier in source order.
    """
    defaults = ["read", "bash", "edit", "write"]
    path = Path(files_dir) / ".pi" / "agent" / "settings.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return defaults
    if not isinstance(value, dict) or "defaultTools" not in value:
        return defaults
    configured = value["defaultTools"]
    # Upstream deliberately tolerates malformed settings: a non-array is an
    # empty selection, and non-string array entries are ignored. Unknown names
    # are preserved here; the tool registry decides what can execute later.
    entries = (
        [item for item in configured if isinstance(item, str)]
        if isinstance(configured, list)
        else []
    )
    plain = [item for item in entries if item[:1] not in {"+", "-"}]
    selected = list(plain if plain or not entries else defaults)
    for item in entries:
        name = item[1:]
        if item.startswith("+") and name and name not in selected:
            selected.append(name)
        elif item.startswith("-") and name in selected:
            selected.remove(name)
    return selected


_CONTEXT_NAMES = (
    "AGENTS.override.md",
    "AGENTS.md",
    "AGENTS.MD",
    "CLAUDE.md",
    "CLAUDE.MD",
)


def _context_file(directory: Path) -> Path | None:
    for name in _CONTEXT_NAMES:
        path = directory / name
        if path.is_file():
            return path
    return None


def _context_files(cwd: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    chain = [cwd, *cwd.parents]
    for directory in reversed(chain):
        path = _context_file(directory)
        if path is None:
            continue
        try:
            result.append(
                {
                    "path": str(path),
                    "content": path.read_text(encoding="utf-8").removeprefix("\ufeff"),
                }
            )
        except OSError:
            pass
    return result


def _skills_prompt(skills: list[Skill], reader: str = "read") -> str:
    visible = [skill for skill in skills if not skill.disable_model_invocation]
    if not visible:
        return ""
    lines = [
        "The following skills provide specialized instructions for specific tasks.",
        (
            f"Use the {reader} tool to load a skill's file when the task matches its description."
            if reader in {"read", "bash"}
            else "Load a skill's file when the task matches its description."
        ),
        "When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md) and use that absolute path in tool commands.",
        "",
        "<available_skills>",
    ]
    for skill in visible:
        lines.extend(
            [
                "  <skill>",
                f"    <name>{_escape_xml(skill.name)}</name>",
                f"    <description>{_escape_xml(skill.description)}</description>",
                f"    <location>{_escape_xml(skill.path)}</location>",
                "  </skill>",
            ]
        )
    lines.append("</available_skills>")
    return "\n".join(lines)


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def load_resources(
    files_dir: str | Path,
    cwd: str | Path,
    *,
    selected_tools: list[str] | tuple[str, ...] | None = None,
    append_system_prompt: str = "",
) -> ResourceBundle:
    """Load only Snapshot resources plus project context visible to Pi."""

    root = Path(files_dir)
    work = Path(cwd).resolve()
    diagnostics: list[str] = []
    tools = list(
        ["read", "bash", "edit", "write"] if selected_tools is None else selected_tools
    )
    # Pi loads the selected agent directory's context before project ancestor
    # files.  Preserve that precedence and avoid adding the same path twice
    # when the Snapshot is itself inside the task tree.
    context: list[dict[str, str]] = []
    path = _context_file(root)
    if path is not None:
        try:
            context.append(
                {
                    "path": str(path),
                    "content": path.read_text(encoding="utf-8").removeprefix("\ufeff"),
                }
            )
        except OSError:
            pass
    for item in _context_files(work):
        if all(existing["path"] != item["path"] for existing in context):
            context.append(item)
    skills_root = root / ".pi" / "agent" / "skills"
    skills = _load_skills(skills_root, diagnostics)
    templates = _load_templates(
        root / ".pi" / "agent" / "prompt-templates", diagnostics
    )
    prompt_files = []
    prompt_dir = root / "prompts"
    if prompt_dir.is_dir():
        for path in sorted(prompt_dir.rglob("*.md")):
            try:
                prompt_files.append(
                    path.read_text(encoding="utf-8").removeprefix("\ufeff")
                )
            except OSError:
                pass
    snippets = {
        "read": "Read file contents",
        "bash": "Execute bash commands (ls, grep, find, etc.)",
        "edit": "Make precise file edits with exact text replacement, including multiple disjoint edits in one call",
        "write": "Create or overwrite files",
        "grep": "Search file contents for patterns (respects .gitignore)",
        "find": "Find files by glob pattern (respects .gitignore)",
        "ls": "List directory contents",
    }
    guidelines = {
        "read": ["Use read to examine files instead of cat or sed."],
        "bash": [
            "You can inspect PI_* environment variables for current model and session details."
        ],
        "edit": [
            "Use edit for precise changes (edits[].oldText must match exactly).",
            "When changing multiple separate locations in one file, use one edit call with multiple entries in edits[] instead of multiple edit calls.",
            "Each edits[].oldText is matched against the original file, not after earlier edits are applied. Do not emit overlapping or nested edits. Merge nearby changes into one edit.",
            "Keep edits[].oldText as small as possible while still being unique in the file. Do not pad with large unchanged regions.",
        ],
        "write": ["Use write only for new files or complete rewrites."],
    }
    if "bash" in tools and not any(name in tools for name in ("grep", "find", "ls")):
        guidelines["bash"].insert(0, "Use bash for file operations like ls, rg, find")
    lines = [
        "You are an expert coding assistant operating inside pi, a coding agent harness. You help users by reading files, executing commands, editing code, and writing new files.",
        "<tools>",
        "\n".join(f"- {name}: {snippets.get(name, name)}" for name in tools)
        + "\n\nIn addition to the tools above, you may have access to other custom tools depending on the project.",
        "</tools>",
        "<rules>",
        "\n".join(f"- {rule}" for name in tools for rule in guidelines.get(name, [])),
        "- Be concise in your responses",
        "- Show file paths clearly when working with files",
        "</rules>",
    ]
    if append_system_prompt.strip():
        lines.extend(["<addendum>", append_system_prompt.strip(), "</addendum>"])
    if context:
        lines.append("Project-specific instructions and guidelines:")
        lines.extend(
            f'<project_instructions path="{item["path"]}">\n{item["content"]}\n</project_instructions>'
            for item in context
        )
    skill_reader = "read" if "read" in tools else "bash" if "bash" in tools else None
    skill_text = _skills_prompt(skills, skill_reader) if skill_reader else ""
    if skill_text:
        lines.extend(["<skills>", skill_text, "</skills>"])
    if prompt_files:
        lines.extend(
            ["<snapshot_prompts>", "\n\n".join(prompt_files), "</snapshot_prompts>"]
        )
    lines.extend(["<cwd>", str(work).replace("\\", "/"), "</cwd>"])
    return ResourceBundle(
        system_prompt="\n\n".join(lines),
        skills=skills,
        templates=templates,
        context_files=context,
        tool_schemas=tool_schemas(tools),
        diagnostics=diagnostics,
    )


__all__ = [
    "PromptTemplate",
    "ResourceBundle",
    "Skill",
    "load_resources",
    "substitute_template",
    "expand_prompt_template",
    "default_tools",
]
