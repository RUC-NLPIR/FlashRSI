"""Pi-compatible Snapshot resource discovery and system prompt construction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ignore import IgnoreRules
from .prompt_builder import build_system_prompt_sections, render_sections
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
    system_sections: dict[str, str] | None = None
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
    end = text.find("\n---", 3) if text.startswith("---") else -1
    if end == -1:
        return {}, text
    try:
        import yaml

        class CoreLoader(yaml.SafeLoader):
            # Upstream's yaml package uses YAML 1.2 core, while PyYAML's
            # SafeLoader defaults to YAML 1.1 (yes/on and leading-zero octals).
            yaml_implicit_resolvers = {
                char: [
                    (tag, pattern)
                    for tag, pattern in resolvers
                    if tag
                    not in {
                        "tag:yaml.org,2002:bool",
                        "tag:yaml.org,2002:int",
                        "tag:yaml.org,2002:timestamp",
                    }
                ]
                for char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
            }

        CoreLoader.add_implicit_resolver(
            "tag:yaml.org,2002:bool",
            re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
            list("tTfF"),
        )
        CoreLoader.add_implicit_resolver(
            "tag:yaml.org,2002:int",
            re.compile(r"^[-+]?(?:[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"),
            list("-+0123456789"),
        )

        def integer(loader, node):
            value = loader.construct_scalar(node)
            sign = -1 if value.startswith("-") else 1
            value = value.lstrip("-+")
            return sign * int(
                value,
                8 if value.startswith("0o") else 16 if value.startswith("0x") else 10,
            )

        def mapping(loader, node):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node)
                if key in result:
                    raise ValueError(f"Map keys must be unique: {key}")
                result[key] = loader.construct_object(value_node)
            return result

        CoreLoader.add_constructor("tag:yaml.org,2002:int", integer)
        CoreLoader.add_constructor("tag:yaml.org,2002:map", mapping)
        raw = text[4:end]
        value = yaml.load(raw, Loader=CoreLoader) if raw else {}
        return (value if isinstance(value, dict) else {}), text[end + 4 :].strip()
    except Exception as exc:
        # The upstream loader reports malformed frontmatter and skips that
        # resource.  Preserve the error so callers can add a diagnostic rather
        # than silently treating the file as metadata-free.
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc


def _skill_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result: list[Path] = []
    ignore = IgnoreRules(
        root,
        names=(".gitignore", ".ignore", ".fdignore"),
        ignore_case=True,
        prefix_rules=True,
    )

    def walk(directory):
        try:
            entries = sorted(directory.iterdir())
            declared = directory / "SKILL.md"
            if declared.is_file() and not ignore.is_ignored(declared, is_dir=False):
                result.append(declared)
                return
            for entry in entries:
                if entry.name.startswith(".") or entry.name == "node_modules":
                    continue
                is_directory = entry.is_dir()
                if ignore.is_ignored(entry, is_dir=is_directory):
                    continue
                if is_directory:
                    walk(entry)
                elif (
                    directory == root and entry.is_file() and entry.name.endswith(".md")
                ):
                    result.append(entry)
        except OSError:
            return

    walk(root)
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
        # Upstream emits warnings for malformed names / long descriptions,
        # but still loads any skill with a nonempty string description.
        if not isinstance(description, str) or not description.strip():
            continue
        result.append(
            Skill(
                name=name,
                description=description,
                content=body.strip(),
                path=str(path),
                disable_model_invocation=metadata.get("disable-model-invocation")
                is True,
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
        if not isinstance(description, str) or not description:
            first_line = next((line for line in body.splitlines() if line.strip()), "")
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
    shadowed = _shadowed_context_file(cwd)
    chain = [cwd, *cwd.parents]
    for directory in reversed(chain):
        path = _context_file(directory)
        if path is None:
            continue
        if shadowed is not None and directory.resolve() / path.name == shadowed:
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


def _shadowed_context_file(cwd: Path) -> Path | None:
    """A nested linked worktree shadows its main repository's context copy."""
    for directory in (cwd, *cwd.parents):
        marker = directory / ".git"
        if marker.is_dir():
            return None
        if not marker.is_file():
            continue
        try:
            raw = marker.read_text().strip()
            if not raw.startswith("gitdir:"):
                return None
            git_dir = (directory / raw[7:].strip()).resolve()
            common = git_dir / "commondir"
            if not common.is_file():
                return None
            common_git = (git_dir / common.read_text().strip()).resolve()
            main = common_git.parent
            worktree = directory.resolve()
            if worktree == main or not worktree.is_relative_to(main):
                return None
            if (main / ".git").resolve() != common_git:
                return None
            context = _context_file(worktree)
            return main / context.name if context else None
        except (OSError, ValueError):
            return None
    return None


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
    custom_system_prompt: str | None = None,
    force_system_prompt: str | None = None,
    hidden_tools: list[str] | tuple[str, ...] = (),
    prompt_guidelines: list[str] | tuple[str, ...] = (),
    sections: dict[str, str] | None = None,
    project_trusted: bool = True,
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
    if project_trusted:
        skills.extend(_load_skills(work / ".pi" / "skills", diagnostics))
    unique_skills: dict[str, Skill] = {}
    seen_paths: set[str] = set()
    for skill in skills:
        canonical = str(Path(skill.path).resolve())
        if canonical in seen_paths:
            continue
        if skill.name in unique_skills:
            diagnostics.append(f'Skill name "{skill.name}" collision: {skill.path}')
            continue
        unique_skills[skill.name] = skill
        seen_paths.add(canonical)
    skills = list(unique_skills.values())
    templates = _load_templates(
        root / ".pi" / "agent" / "prompt-templates", diagnostics
    )
    # Pi's canonical user prompts directory is agentDir/prompts. The legacy
    # Snapshot prompt-templates directory remains an explicit resource alias.
    for folder in (
        root / ".pi" / "agent" / "prompts",
        *([work / ".pi" / "prompts"] if project_trusted else []),
    ):
        for name, template in _load_templates(folder, diagnostics).items():
            if name in templates:
                diagnostics.append(f'Prompt name "{name}" collision: {template.path}')
            else:
                templates[name] = template
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

    def discover_prompt(filename):
        candidates = ([work / ".pi" / filename] if project_trusted else []) + [
            root / filename,
            root / ".pi" / "agent" / filename,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").removeprefix("\ufeff")
        return None

    custom = (
        custom_system_prompt
        if custom_system_prompt is not None
        else discover_prompt("SYSTEM.md")
    )
    appended = discover_prompt("APPEND_SYSTEM.md")
    # Explicit appended prompt text has the same precedence as upstream's
    # appendSystemPrompt option over a discovered APPEND_SYSTEM.md.
    append_text = append_system_prompt if append_system_prompt else appended or ""
    if prompt_files:
        sections = {**(sections or {}), "snapshot_prompts": "\n\n".join(prompt_files)}
    manifest = json.loads((Path(__file__).parent / "tool_manifest.json").read_text())
    system_sections = (
        None
        if force_system_prompt is not None
        else build_system_prompt_sections(
            cwd=work,
            selected_tools=tools,
            hidden_tools=hidden_tools,
            tool_snippets={name: item["snippet"] for name, item in manifest.items()},
            tool_guidelines={
                name: item.get("guidelines", []) for name, item in manifest.items()
            },
            prompt_guidelines=prompt_guidelines,
            custom_prompt=custom,
            append_system_prompt=append_text,
            sections=sections,
            context_files=context,
            skills=skills,
            reference_root=root / "runtime" / "pi_native" / "reference",
        )
    )
    system_prompt = (
        force_system_prompt
        if force_system_prompt is not None
        else render_sections(system_sections)
    )
    return ResourceBundle(
        system_prompt=system_prompt,
        system_sections=system_sections,
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
